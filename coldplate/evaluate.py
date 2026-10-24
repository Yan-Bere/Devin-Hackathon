"""evaluate(): layout -> hydraulics -> thermal -> constraint report + fields."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Optional

import numpy as np

from coldplate.geometry import ChannelDesign, build_layout, check_connectivity
from coldplate.hydraulics import HydraulicResult, solve_hydraulics
from coldplate.spec import EngineInputs
from coldplate.thermal import ThermalResult, solve_thermal

SIMULATION_METADATA = {
    "name": "coldplate-rom/1",
    "label": "Low-fidelity reduced-order thermohydraulic estimate — not validated 3D CFD",
    "correlations": [
        "f*Re laminar, parallel plates: Shah & London polynomial in aspect ratio",
        "K_inf Hagenbach developing-flow polynomial (Shah & London)",
        "Turbulent friction: Petukhov; linear blend 2300 < Re < 4000",
        "Nu_fd H1 four-sided correlation (Shah & London); developing Gz correction",
        "Turbulent Nusselt: Gnielinski; fin efficiency eta = tanh(mH)/(mH)",
        "Opening/manifold losses: lumped K = 1 per opening and per channel turn",
    ],
    "assumptions": [
        "constant coolant and solid properties at the nominal point",
        "2-D lumped base (mid-plane node), adiabatic fin tips and plate edges",
        "channels smeared into a per-zone continuum along the stacking axis",
        "lumped K factors for manifold turns and opening losses",
        "manifold openings default to the ITherm competition proportions",
        "power-map flux smeared over source footprints / grid cells",
    ],
}


def bulk_temperature_rise(power_W: float, flow_Lpm: float, rho: float, cp: float) -> float:
    Q = flow_Lpm * 1e-3 / 60.0
    return power_W / (rho * Q * cp) if rho * Q * cp > 0 else 0.0


@dataclass
class Evaluation:
    design_id: str
    flow_Lpm: float
    inlet_C: float
    hydraulics: HydraulicResult
    thermal: ThermalResult
    layout: object
    constraints: dict
    fields: Optional[dict] = None
    runtime_s: float = 0.0


def evaluate(
    inputs: EngineInputs,
    design: ChannelDesign,
    *,
    flow_Lpm: Optional[float] = None,
    inlet_C: Optional[float] = None,
    grid_mm: float = 0.5,
    want_fields: bool = False,
) -> Evaluation:
    t0 = time.perf_counter()
    flow = inputs.flow_Lpm if flow_Lpm is None else flow_Lpm
    tin = inputs.inlet_C if inlet_C is None else inlet_C
    layout = build_layout(inputs, design)
    Q = flow * 1e-3 / 60.0
    hydro = solve_hydraulics(layout, inputs.rho_kg_m3, inputs.mu_Pa_s, Q)
    th = solve_thermal(
        layout, inputs, hydro, inputs.power_map,
        inputs.rho_kg_m3, inputs.mu_Pa_s, inputs.cp_J_kgK, inputs.k_fluid_W_mK,
        tin, grid_mm=grid_mm, want_fields=want_fields,
    )
    # constraint report
    cons = {"per_component": [], "dp": {}, "rise_K": th.rise_K, "ok": True}
    lim = inputs.limits_C or {}
    tgt = inputs.targets_C or {}
    strc = inputs.stretch_C or {}
    worst = float("inf")
    for c in th.components:
        hard = lim.get(c["type"])
        entry = {"name": c["name"], "type": c["type"], "max_C": c["max_C"]}
        if hard is not None:
            entry["hard_C"] = hard
            entry["margin_K"] = hard - c["max_C"]
            entry["ok_hard"] = c["max_C"] <= hard
            cons["ok"] &= bool(entry["ok_hard"])
            worst = min(worst, entry["margin_K"])
        if c["type"] in tgt:
            entry["ok_target"] = c["max_C"] <= tgt[c["type"]]
        if c["type"] in strc:
            entry["ok_stretch"] = c["max_C"] <= strc[c["type"]]
        cons["per_component"].append(entry)
    cons["worst_margin_K"] = worst if worst != float("inf") else None
    if inputs.dp_hard_Pa is not None:
        cons["dp"] = {
            "dP_Pa": hydro.dP_total_Pa,
            "hard_Pa": inputs.dp_hard_Pa,
            "ok_hard": hydro.dP_total_Pa <= inputs.dp_hard_Pa,
            "ok_target": hydro.dP_total_Pa <= inputs.dp_target_Pa if inputs.dp_target_Pa else None,
            "ok_stretch": hydro.dP_total_Pa <= inputs.dp_stretch_Pa if inputs.dp_stretch_Pa else None,
        }
        cons["ok"] &= bool(cons["dp"]["ok_hard"])
    if inputs.max_outlet_rise_K is not None:
        cons["rise"] = {"rise_K": th.rise_K, "max_K": inputs.max_outlet_rise_K,
                        "ok": th.rise_K <= inputs.max_outlet_rise_K}
        cons["ok"] &= bool(cons["rise"]["ok"])

    fields = _fields(layout, inputs, th, hydro) if want_fields else None
    return Evaluation(
        design_id=design.design_id, flow_Lpm=flow, inlet_C=tin,
        hydraulics=hydro, thermal=th, layout=layout, constraints=cons,
        fields=fields, runtime_s=time.perf_counter() - t0,
    )


def _fields(layout, inputs, th: ThermalResult, hydro: HydraulicResult) -> dict:
    """Dashboard contract (plate frame; rows=increasing y, cols=increasing x)."""
    axis = layout.design.flow_axis
    g = th.grid
    if axis == "x":
        x_edges, y_edges = g["u_edges"], g["v_edges"]
        T_s, T_die, T_f, vel = th.T_s, th.T_die, th.T_f, th.velocity_u
    else:
        x_edges, y_edges = g["v_edges"], g["u_edges"]
        T_s, T_die, T_f, vel = th.T_s.T, th.T_die.T, th.T_f.T, th.velocity_u.T
    xc = np.round(0.5 * (x_edges[:-1] + x_edges[1:]), 4).tolist()
    yc = np.round(0.5 * (y_edges[:-1] + y_edges[1:]), 4).tolist()

    def arr(a, nd):
        return [
            [None if np.isnan(v) else round(float(v), nd) for v in row]
            for row in np.asarray(a)
        ]

    flux = inputs.power_map.flux_on_grid(np.asarray(x_edges), np.asarray(y_edges)) / 1e4

    def rect(r):
        return {"x0": r.x0, "y0": r.y0, "x1": r.x1, "y1": r.y1}

    return {
        "frame": "plate (mm, origin lower-left, z0 at plate bottom)",
        "units": {"x": "mm", "y": "mm", "temperature": "degC",
                  "velocity": "m/s", "heat_flux": "W/cm2"},
        "grid": {"dx_mm": g["du_mm"], "nx": len(xc), "ny": len(yc),
                 "x_centers_mm": xc, "y_centers_mm": yc},
        "chip_temperature_C": arr(T_die, 2),
        "plate_temperature_C": arr(T_s, 2),
        "fluid_temperature_C": arr(T_f, 2),
        "velocity_u_m_s": arr(vel, 4),
        "heat_flux_W_cm2": arr(flux, 4),
        "flow_axis": axis,
        "outlines": {
            "plate": {"x0": 0.0, "y0": 0.0, "x1": inputs.plate_lx_mm, "y1": inputs.plate_ly_mm},
            "fin_region": {"x0": inputs.fin_region_x0_mm, "y0": inputs.fin_region_y0_mm,
                           "x1": inputs.fin_region_x0_mm + inputs.fin_region_lx_mm,
                           "y1": inputs.fin_region_y0_mm + inputs.fin_region_ly_mm},
            "heat_sources": [
                {"name": s.name, "type": s.type, "x0": s.x0_mm, "y0": s.y0_mm,
                 "x1": s.x0_mm + s.width_mm, "y1": s.y0_mm + s.height_mm}
                for s in inputs.sources
            ],
            "inlet_openings": [rect(r) for r in layout.openings["inlet"]],
            "outlet_openings": [rect(r) for r in layout.openings["outlet"]],
        },
        "connectivity_ok": check_connectivity(layout),
    }
