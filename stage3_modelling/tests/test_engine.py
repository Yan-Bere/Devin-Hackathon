"""Engine stack tests: geometry, CAD, hydraulics, thermal, evaluate."""

import json
import math
from pathlib import Path

import numpy as np
import pytest

from coldplate import units
from coldplate.evaluate import bulk_temperature_rise, evaluate
from coldplate.extraction_schema import RequirementsExtraction
from coldplate.geometry import (
    ChannelDesign, FinZone, GeometryError, baseline_design,
    build_layout, check_connectivity, derive_zone_bands,
)
from coldplate.hydraulics import f_darcy_re, solve_hydraulics
from coldplate.normalize import normalize_extraction
from coldplate.power_map import UniformPowerMap, Footprint
from coldplate.spec import EngineInputs
from scipy import ndimage

FIXTURES = Path(__file__).parent / "fixtures"
GOLDEN = json.loads((FIXTURES / "golden" / "A_canonical.extraction.json").read_text(encoding="utf-8"))
DOCS = {p.stem: p.read_text(encoding="utf-8") for p in FIXTURES.glob("*.md")}
REF = {"power_map_W_per_mm2.csv": (FIXTURES / "reference_files" / "power_map_W_per_mm2.csv").read_bytes()}


@pytest.fixture(scope="module")
def inputs_A():
    ex = RequirementsExtraction.model_validate(GOLDEN)
    res = normalize_extraction(ex, document=DOCS["A_canonical"], reference_files=REF)
    assert res.status == "ok"
    return res.spec.engine_inputs()


@pytest.fixture(scope="module")
def layout_A(inputs_A):
    return build_layout(inputs_A, baseline_design(inputs_A))


# ----------------------------------------------------------------- geometry


def test_zone_bands_itherm(inputs_A):
    bands = derive_zone_bands(inputs_A, "x")
    assert bands == pytest.approx([
        ("HBM", 12.925, 23.925), ("GPU", 23.925, 54.075), ("HBM", 54.075, 65.075)
    ], rel=0, abs=1e-6)


def test_baseline_tiling_exact(inputs_A, layout_A):
    la = layout_A
    fins_v = [f for f in la.fins]
    # every fin spans the full u extent
    u0, u1 = la.u_range
    for f in la.fins:
        assert f.x0 == pytest.approx(u0) and f.x1 == pytest.approx(u1)
    # tiling fills exactly: fins+channels cover [v0,v1] with no gaps/overlaps
    v0, v1 = la.v_range
    spans = sorted([(f.y0, f.y1, "f") for f in la.fins] +
                   [(c["v_lo"], c["v_hi"], "c") for c in la.channels])
    cursor = v0
    for a, b, _ in spans:
        assert a == pytest.approx(cursor, abs=1e-6)
        cursor = b
    assert cursor == pytest.approx(v1, abs=1e-6)
    assert la.channels[0]["width_mm"] == pytest.approx(0.3029, abs=1e-3)


def test_geometry_rejections(inputs_A):
    ei = inputs_A
    base = baseline_design(ei)
    v0, v1 = 12.925, 65.075
    def mk(zones, **kw):
        return ChannelDesign(zones=zones, **{**dict(
            design_id="t", arrangement=base.arrangement, flow_axis="x",
            fin_height_mm=kw.get("h", 2.0), inlet_opening_mm=kw.get("io", 11.0),
            outlet_opening_mm=kw.get("oo", 6.0))})
    with pytest.raises(GeometryError):
        build_layout(ei, mk((FinZone("z", v0, v1, 0.05, 0.3),)))  # t too thin
    with pytest.raises(GeometryError):
        build_layout(ei, mk((FinZone("z", v0, v1, 0.3, 0.6),)))   # w too wide
    with pytest.raises(GeometryError):
        build_layout(ei, mk((FinZone("z", v0, v1, 0.3, 0.3),), h=3.0))  # H > max
    with pytest.raises(GeometryError):
        build_layout(ei, mk((FinZone("z", v0, v1, 0.3, 0.3),), io=40.0, oo=20.0))
    with pytest.raises(GeometryError):
        build_layout(ei, ChannelDesign(
            design_id="t", arrangement="serpentine", flow_axis="x", fin_height_mm=2.0,
            zones=(FinZone("z", v0, v1, 0.3, 0.3),), inlet_opening_mm=11.0,
            outlet_opening_mm=6.0))


def test_flood_fill_connectivity(inputs_A, layout_A):
    la = layout_A
    dx = 0.05
    nx = int(round(inputs_A.plate_lx_mm / dx))
    ny = int(round(inputs_A.plate_ly_mm / dx))
    occ = np.zeros((ny, nx), dtype=bool)  # True = solid fin
    for f in la.fins:
        i0 = int(f.x0 / dx); i1 = int(f.x1 / dx)
        j0 = int(f.y0 / dx); j1 = int(f.y1 / dx)
        occ[j0:j1, i0:i1] = True
    fluid = ~occ
    lab, n = ndimage.label(fluid)
    # flood from each inlet footprint
    inlet_labels = set()
    for r in la.openings["inlet"]:
        j0 = int(r.y0 / dx); j1 = int(r.y1 / dx)
        i0 = int(r.x0 / dx); i1 = int(r.x1 / dx)
        inlet_labels.update(lab[j0:j1, i0:i1].ravel().tolist())
    inlet_labels.discard(0)
    reached = np.isin(lab, list(inlet_labels))
    # every channel cell and every outlet cell reached
    for ch in la.channels:
        j0 = int(ch["v_lo"] / dx); j1 = int(ch["v_hi"] / dx)
        u0, u1 = la.u_range
        i0 = int(u0 / dx); i1 = int(u1 / dx)
        cells = fluid[j0:j1, i0:i1]
        assert reached[j0:j1, i0:i1][cells].all(), f"channel {ch['index']} not reached"
    for r in la.openings["outlet"]:
        j0 = int(r.y0 / dx); j1 = int(r.y1 / dx)
        i0 = int(r.x0 / dx); i1 = int(r.x1 / dx)
        cells = fluid[j0:j1, i0:i1]
        assert reached[j0:j1, i0:i1][cells].all()


def test_D_layout_inside_regions():
    ex = RequirementsExtraction.model_validate(json.loads(json.dumps(GOLDEN)))
    # reuse the D fixture doc via the pipeline test variant
    from tests.test_parser_pipeline import variant_D
    res = normalize_extraction(
        RequirementsExtraction.model_validate(variant_D()),
        document=DOCS["D_plate_90x84"], reference_files=REF)
    ei = res.spec.engine_inputs()
    la = build_layout(ei, baseline_design(ei))
    for f in la.fins:
        assert 0 <= f.x0 and f.x1 <= 90.0 and 0 <= f.y0 and f.y1 <= 84.0
    assert check_connectivity(la)


# ----------------------------------------------------------------------- CAD


@pytest.mark.slow
def test_cad_baseline(inputs_A, layout_A, tmp_path):
    from coldplate.cad import export_design
    art = export_design(layout_A, str(tmp_path))
    assert art.bbox_mm == pytest.approx((78.0, 78.0, 4.0), abs=0.05)
    assert abs(art.volume_mm3 - art.model_volume_mm3) / art.model_volume_mm3 < 0.001
    assert art.is_valid and art.fin_count == len(layout_A.fins)
    for p in (art.step_path, art.stl_path, art.glb_path):
        assert Path(p).stat().st_size > 1000
    with open(art.glb_path, "rb") as f:
        assert f.read(4) == b"glTF"


# --------------------------------------------------------------- hydraulics


def test_fre_limits():
    assert f_darcy_re(1e-6, 100) * 100 == pytest.approx(96.0, rel=1e-3)
    assert f_darcy_re(1.0, 100) * 100 == pytest.approx(56.9, rel=1e-3)


def test_hydraulics_baseline(inputs_A, layout_A):
    Q = 2.0e-3 / 60.0
    h = solve_hydraulics(layout_A, inputs_A.rho_kg_m3, inputs_A.mu_Pa_s, Q)
    tot = sum(z.n_paths * z.q_per_channel_m3s for z in h.zones)
    assert tot == pytest.approx(Q, rel=1e-6)
    assert h.dP_total_Pa > 0
    z = h.zones[0]
    assert z.V_m_s == pytest.approx(0.320, rel=0.05)
    assert z.Re == pytest.approx(209, rel=0.1)
    h3 = solve_hydraulics(layout_A, inputs_A.rho_kg_m3, inputs_A.mu_Pa_s, 3.0e-3 / 60.0)
    assert h3.dP_total_Pa > h.dP_total_Pa


def test_narrow_channels_get_less_flow(inputs_A):
    ei = inputs_A
    zones = (
        FinZone("wide", 12.925, 39.0, 0.3, 0.3),
        FinZone("narrow", 39.0, 65.075, 0.1, 0.1),
    )
    d = ChannelDesign(design_id="tw", arrangement=ei.arrangement, flow_axis="x",
                      fin_height_mm=2.0, zones=zones,
                      inlet_opening_mm=ei.inlet_opening_mm,
                      outlet_opening_mm=ei.outlet_opening_mm)
    la = build_layout(ei, d)
    h = solve_hydraulics(la, ei.rho_kg_m3, ei.mu_Pa_s, 2.0e-3 / 60.0)
    zw = next(z for z in h.zones if z.zone == "wide")
    zn = next(z for z in h.zones if z.zone == "narrow")
    assert zn.q_per_channel_m3s < zw.q_per_channel_m3s


# ------------------------------------------------------------------ thermal


def test_bulk_rise():
    assert bulk_temperature_rise(1492.8, 2.0, 997, 4180) == pytest.approx(10.75, abs=0.01)
    assert bulk_temperature_rise(1492.8, 1.0, 997, 4180) == pytest.approx(21.49, abs=0.01)


def test_energy_conservation(inputs_A):
    ev = evaluate(inputs_A, baseline_design(inputs_A))
    t = ev.thermal
    assert t.heat_to_fluid_W == pytest.approx(1492.8, rel=1e-6)
    mdot = ev.hydraulics.Q_m3s * inputs_A.rho_kg_m3
    assert mdot * inputs_A.cp_J_kgK * t.rise_K == pytest.approx(1492.8, rel=1e-6)


def _uniform_inputs(ei):
    from dataclasses import replace
    fps = tuple(
        Footprint(s.name, s.type, s.x0_mm, s.y0_mm, s.x0_mm + s.width_mm,
                  s.y0_mm + s.height_mm, s.power_W)
        for s in ei.sources
    )
    return replace(ei, power_map=UniformPowerMap(fps))


def test_uniform_mirror_symmetry(inputs_A):
    ev = evaluate(_uniform_inputs(inputs_A), baseline_design(inputs_A))
    comps = {c["name"]: c["max_C"] for c in ev.thermal.components}
    assert comps["GPU1"] == pytest.approx(comps["GPU2"], abs=1e-6)
    for grp in (("H1", "H4", "H5", "H8"), ("H2", "H3", "H6", "H7")):
        vals = [comps[n] for n in grp]
        assert max(vals) - min(vals) < 1e-6


def test_csv_near_symmetry(inputs_A):
    ev = evaluate(inputs_A, baseline_design(inputs_A))
    comps = {c["name"]: c["max_C"] for c in ev.thermal.components}
    for grp in (("H1", "H4", "H5", "H8"), ("H2", "H3", "H6", "H7")):
        vals = [comps[n] for n in grp]
        assert max(vals) - min(vals) < 0.5


def test_inlet_shift(inputs_A):
    d = baseline_design(inputs_A)
    a = evaluate(inputs_A, d, inlet_C=30.0)
    b = evaluate(inputs_A, d, inlet_C=35.0)
    for ca, cb in zip(a.thermal.components, b.thermal.components):
        assert cb["max_C"] == pytest.approx(ca["max_C"] + 5.0, abs=1e-6)


def test_grid_convergence(inputs_A):
    d = baseline_design(inputs_A)
    ei_u = _uniform_inputs(inputs_A)
    a = evaluate(ei_u, d, grid_mm=0.5)
    b = evaluate(ei_u, d, grid_mm=0.25)
    ma = max(c["max_C"] for c in a.thermal.components)
    mb = max(c["max_C"] for c in b.thermal.components)
    assert abs(ma - mb) < 1.0


def test_finer_pitch_more_U_and_dP(inputs_A):
    ei = inputs_A
    v0, v1 = 12.925, 65.075
    fine = ChannelDesign(design_id="f", arrangement=ei.arrangement, flow_axis="x",
                         fin_height_mm=2.0,
                         zones=(FinZone("z", v0, v1, 0.1, 0.1),),
                         inlet_opening_mm=ei.inlet_opening_mm,
                         outlet_opening_mm=ei.outlet_opening_mm)
    a = evaluate(ei, baseline_design(ei))
    b = evaluate(ei, fine)
    assert b.hydraulics.dP_total_Pa > a.hydraulics.dP_total_Pa
    # finer pitch -> lower max temp (higher U)
    assert max(c["max_C"] for c in b.thermal.components) < max(
        c["max_C"] for c in a.thermal.components)


def test_analytic_straight():
    # straight arrangement, uniform flux over the whole fin region, uniform zone:
    # covered region must show T_s - T_f ~= q''/U and T_f linear in u
    ei = EngineInputs(
        plate_lx_mm=60.0, plate_ly_mm=60.0, base_thickness_mm=2.0, k_solid_W_mK=391.0,
        fin_region_x0_mm=10.0, fin_region_y0_mm=10.0,
        fin_region_lx_mm=40.0, fin_region_ly_mm=40.0, fin_height_max_mm=2.0,
        sources=tuple(), power_map=None,
        rho_kg_m3=997.0, cp_J_kgK=4180.0, mu_Pa_s=7.97e-4, k_fluid_W_mK=0.615,
        inlet_C=30.0, flow_Lpm=2.0,
        arrangement="straight", flow_axis="x",
        inlet_opening_mm=8.0, outlet_opening_mm=8.0,
    )
    from coldplate.power_map import UniformPowerMap
    fp = Footprint("U", "GPU", 10.0, 10.0, 50.0, 50.0, 400.0)
    object.__setattr__(ei, "power_map", UniformPowerMap((fp,)))
    d = ChannelDesign(design_id="s", arrangement="straight", flow_axis="x",
                      fin_height_mm=2.0, zones=(FinZone("z", 10.0, 50.0, 0.3, 0.3),),
                      inlet_opening_mm=8.0, outlet_opening_mm=8.0)
    ev = evaluate(ei, d, want_fields=True)
    t = ev.thermal
    assert t.energy_residual < 1e-9
    g = t.grid
    ue, ve = g["u_edges"], g["v_edges"]
    uc = 0.5 * (ue[:-1] + ue[1:])
    vc = 0.5 * (ve[:-1] + ve[1:])
    qpp = 400.0 / (40e-3 * 40e-3)  # W/m2 uniform
    U = t.zones[0]["U"]
    j_mid = int(np.argmin(np.abs(vc - 30.0)))
    i_mid = int(np.argmin(np.abs(uc - 30.0)))
    covered = (uc >= 18.0) & (uc <= 42.0)
    # T_s - T_f ~= q''/U mid-channel (within 3%)
    assert (t.T_s[j_mid, i_mid] - t.T_f[j_mid, i_mid]) == pytest.approx(
        qpp / U, rel=0.03)
    # T_f linear in u over the covered region
    tf = t.T_f[j_mid, covered]
    xs = uc[covered]
    coeff = np.polyfit(xs, tf, 1)
    resid = tf - np.polyval(coeff, xs)
    ss_res = float((resid**2).sum())
    ss_tot = float(((tf - tf.mean())**2).sum())
    assert 1 - ss_res / ss_tot > 0.999


# ------------------------------------------------- zone-instance regressions


def _zoned_design(ei, w_hbm=0.3, w_gpu=0.3, t=0.3):
    bands = derive_zone_bands(ei, "x")
    zones = tuple(
        FinZone(l, v0, v1, t, w_hbm if l == "HBM" else w_gpu)
        for l, v0, v1 in bands
    )
    return ChannelDesign(design_id="zoned", arrangement=ei.arrangement,
                         flow_axis="x", fin_height_mm=2.0, zones=zones,
                         inlet_opening_mm=ei.inlet_opening_mm,
                         outlet_opening_mm=ei.outlet_opening_mm)


def test_zoned_matches_single_zone_baseline(inputs_A):
    ei_u = _uniform_inputs(inputs_A)
    a = evaluate(ei_u, baseline_design(ei_u))
    b = evaluate(ei_u, _zoned_design(ei_u))
    ca = {c["name"]: c["max_C"] for c in a.thermal.components}
    cb = {c["name"]: c["max_C"] for c in b.thermal.components}
    for n in ca:
        assert abs(ca[n] - cb[n]) < 0.5, n


def test_zoned_uniform_mirror_symmetry(inputs_A):
    ei_u = _uniform_inputs(inputs_A)
    ev = evaluate(ei_u, _zoned_design(ei_u, w_hbm=0.25))
    comps = {c["name"]: c["max_C"] for c in ev.thermal.components}
    for pair in (("H1", "H5"), ("H2", "H6"), ("H3", "H7"), ("H4", "H8"),
                 ("H1", "H4"), ("GPU1", "GPU2")):
        assert abs(comps[pair[0]] - comps[pair[1]]) < 1e-6, pair


def test_zoned_fluid_mass_flow(inputs_A):
    ev = evaluate(inputs_A, _zoned_design(inputs_A))
    assert ev.thermal.mdot_total_kg_s == pytest.approx(
        inputs_A.rho_kg_m3 * ev.hydraulics.Q_m3s, rel=1e-9)


def test_B_and_C_behaviour():
    from tests.test_parser_pipeline import variant_B, variant_C
    for var, stem, check in (
        (variant_B, "B_flow_3lpm", "B"),
        (variant_C, "C_gpu1_power_plus20", "C"),
    ):
        res = normalize_extraction(
            RequirementsExtraction.model_validate(var()),
            document=DOCS[stem], reference_files=REF)
        ei = res.spec.engine_inputs()
        ev = evaluate(ei, baseline_design(ei))
        if check == "B":
            assert ev.thermal.rise_K == pytest.approx(7.16, abs=0.05)
        else:
            g1 = next(c for c in ev.thermal.components if c["name"] == "GPU1")
            assert g1["max_C"] > 90.0  # hotter than A's GPU1
