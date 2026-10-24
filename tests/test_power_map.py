"""PowerMap tests against the real fixture CSV (die-region frame)."""

import numpy as np
import pytest

from coldplate.power_map import Footprint, GridPowerMap, UniformPowerMap
from pathlib import Path

FIXTURES = Path(__file__).parent / "fixtures"
CSV = (FIXTURES / "reference_files" / "power_map_W_per_mm2.csv").read_bytes()

# die region 52.15 x 50.30 centered on the 78 x 78 plate
DIE_OX, DIE_OY = 12.925, 13.85

# heat-source footprints in the PLATE frame (die origin + document coords)
SOURCES = tuple(
    Footprint(n, t, x0 + DIE_OX, y0 + DIE_OY, x0 + DIE_OX + w, y0 + DIE_OY + h, p)
    for n, t, x0, y0, w, h, p in [
        ("GPU1", "GPU", 0.00, 10.15, 26.0, 30.0, 554.4),
        ("GPU2", "GPU", 26.15, 10.15, 26.0, 30.0, 554.4),
        ("H1", "HBM", 0.00, 40.30, 12.0, 10.0, 48.0),
        ("H2", "HBM", 14.00, 40.30, 12.0, 10.0, 48.0),
        ("H3", "HBM", 26.15, 40.30, 12.0, 10.0, 48.0),
        ("H4", "HBM", 40.15, 40.30, 12.0, 10.0, 48.0),
        ("H5", "HBM", 0.00, 0.00, 12.0, 10.0, 48.0),
        ("H6", "HBM", 14.00, 0.00, 12.0, 10.0, 48.0),
        ("H7", "HBM", 26.15, 0.00, 12.0, 10.0, 48.0),
        ("H8", "HBM", 40.15, 0.00, 12.0, 10.0, 48.0),
    ]
)


def make_grid(row0="bottom"):
    return GridPowerMap.from_csv(
        CSV,
        pitch_mm=0.5,
        origin_plate_mm=(DIE_OX, DIE_OY),
        row0=row0,
        units="W/mm^2",
        sources=SOURCES,
        file_name="power_map_W_per_mm2.csv",
    )


def plate_grid(dx):
    xe = np.arange(0.0, 78.0 + 1e-9, dx)
    ye = np.arange(0.0, 78.0 + 1e-9, dx)
    return xe, ye


@pytest.mark.parametrize("dx", [0.5, 0.37, 1.0, 0.25])
def test_total_power_conserved(dx):
    g = make_grid()
    xe, ye = plate_grid(dx)
    total = g.total_power(xe, ye)
    assert total == pytest.approx(1492.8, abs=1e-6)


def test_component_powers_fine_grid():
    g = make_grid()
    xe, ye = plate_grid(0.1)
    powers = g.component_powers(xe, ye)
    # the figure's flux bleeds ~1% outside the stated footprints (20 W total),
    # so footprint-integrated powers land ~1% under the tabled values
    assert powers["GPU1"] == pytest.approx(554.4, rel=0.02)
    assert powers["H1"] == pytest.approx(48.0, rel=0.02)
    assert powers["GPU2"] == pytest.approx(554.4, rel=0.02)


def test_native_component_powers_exact():
    g = make_grid()
    native, outside = g.attributed_powers()
    # area-normalised attribution gives ~stated powers; ~0 outside
    assert outside == pytest.approx(0.0, abs=1e-6)
    assert native["GPU1"] == pytest.approx(554.4, rel=0.005)
    # boundary-cell attribution is approximate: within the 5% warn tolerance
    assert native["H1"] == pytest.approx(48.0, rel=0.05)


def test_peak_flux_200_W_cm2():
    g = make_grid()
    assert g.values_W_mm2.max() == pytest.approx(2.0)  # 200 W/cm^2


def test_row0_flip_mirrors_map():
    bottom = make_grid("bottom")
    top = make_grid("top")
    assert np.array_equal(np.flipud(bottom.values_W_mm2), top.values_W_mm2)


def test_flux_inside_gpu_footprint():
    g = make_grid()
    xe, ye = plate_grid(0.1)
    flux = g.flux_on_grid(xe, ye)
    # a cell well inside GPU1 (plate coords ~ (25, 35)) must be nonzero
    xc = 0.5 * (xe[:-1] + xe[1:])
    yc = 0.5 * (ye[:-1] + ye[1:])
    j = int(np.argmin(abs(xc - 25.0)))
    i = int(np.argmin(abs(yc - 35.0)))
    assert flux[i, j] > 0
    # a cell far outside the die region is zero
    i2 = int(np.argmin(abs(yc - 5.0)))
    assert flux[i2, j] == 0.0


def test_uniform_map_conserves_power():
    um = UniformPowerMap(SOURCES)
    xe, ye = plate_grid(0.37)
    assert um.total_power(xe, ye) == pytest.approx(1492.8, rel=1e-9)
    powers = um.component_powers(xe, ye)
    assert powers["GPU1"] == pytest.approx(554.4, rel=0.005)
    # uniform flux inside GPU1 footprint = 554.4 W / 780 mm^2
    flux = um.flux_on_grid(xe, ye)
    xc = 0.5 * (xe[:-1] + xe[1:])
    yc = 0.5 * (ye[:-1] + ye[1:])
    j = int(np.argmin(abs(xc - 20.0)))
    i = int(np.argmin(abs(yc - 30.0)))
    assert flux[i, j] == pytest.approx(554.4 / 780.0 * 1e6, rel=0.01)


def test_rescale_components():
    g = make_grid()
    stated = {s.name: s.power_W for s in SOURCES}
    stated["GPU1"] = 665.28
    warnings = g.rescale_components(stated)
    assert any("GPU1" in w and "rescaled" in w for w in warnings)
    # after rescale the map sums to the stated total (outside power is ~0)
    assert float(g.values_W_mm2.sum() * 0.25) == pytest.approx(1603.68, rel=0.005)


def test_no_rescale_when_totals_match():
    g = make_grid()
    stated = {s.name: s.power_W for s in SOURCES}
    before = g.values_W_mm2.copy()
    warnings = g.rescale_components(stated)
    assert not any("rescaled" in w for w in warnings)
    assert np.array_equal(g.values_W_mm2, before)
