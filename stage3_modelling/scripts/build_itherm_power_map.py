"""Build the ITherm power-map reference files from the competition package figure.

Source: the package/power-map figure in "METTL Slides Week Oct 19.pptx" (the
ITherm 2027 competition drawing of 2 GPUs + 8 HBM stacks). Every cell of that
drawing is a 2 mm x 2 mm square labelled with its power in watts. The labels
were read from the image and cross-checked by classifying each cell's fill
colour; the transcription reproduces the stated component powers exactly
(each GPU 554.4 W, each HBM stack 48.0 W, total 1492.8 W).

Note: this figure contradicts two ASSUMPTION lines in coldplate_devin_inputs.md
(GPU background is 0 W, not 2.0 relative; peak cell flux is 200 W/cm^2, not
~134 W/cm^2; HBM rows are graded 30-50 W/cm^2, not uniform).

Outputs (coordinates are the die-region frame of the requirements document:
origin at the lower-left corner of the 52.15 x 50.30 mm die region):
  tests/fixtures/itherm_figure_power_map.json   native 2 mm cells per component
  tests/fixtures/reference_files/power_map_W_per_mm2.csv
      0.5 mm grid in W/mm^2, no header; row 0 is y = 0.25 mm (bottom),
      column 0 is x = 0.25 mm (left) -- the convention stated in the
      requirements document. Values are exact area averages of the 2 mm cells.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures"

CELL_MM = 2.0
DIE_REGION_MM = (52.15, 50.30)
GRID_PITCH_MM = 0.5

# GPU1 as drawn, rows listed top -> bottom, columns left -> right (W per cell).
_GPU1_TOP_TO_BOTTOM = [
    [0, 0, 8, 8, 8, 8, 8, 8, 8, 8, 0, 0, 0],
    [0, 0, 2.4, 2.4, 2.4, 2.4, 2.4, 2.4, 2.4, 2.4, 0, 0, 0],
    [0] * 13,
    [0, 0, 0, 0, 0, 0, 4, 4, 6, 6, 4, 4, 6],
    [0, 0, 0, 0, 0, 0, 6, 6, 8, 8, 6, 6, 8],
    [0, 0, 0, 0, 0, 0, 4, 4, 7, 7, 7, 7, 8],
    [0, 0, 0, 0, 0, 0, 6, 6, 6, 6, 8, 8, 6],
    [0, 0, 0, 0, 0, 0, 4, 4, 8, 8, 6, 6, 8],
    [0, 0, 0, 0, 0, 0, 6, 6, 6, 6, 8, 8, 6],
    [0, 0, 0, 0, 0, 0, 4, 4, 7, 7, 7, 7, 8],
    [0, 0, 0, 0, 0, 0, 6, 6, 8, 8, 6, 6, 8],
    [0, 0, 0, 0, 0, 0, 4, 4, 6, 6, 4, 4, 6],
    [0] * 13,
    [0, 0, 2.4, 2.4, 2.4, 2.4, 2.4, 2.4, 2.4, 2.4, 0, 0, 0],
    [0, 0, 8, 8, 8, 8, 8, 8, 8, 8, 0, 0, 0],
]
# Top-row HBM stacks (H1-H4) as drawn, top -> bottom; the 2.0 W rows face the GPUs.
_HBM_TOP_ROW_TOP_TO_BOTTOM = [[1.2] * 6, [1.2] * 6, [1.6] * 6, [2.0] * 6, [2.0] * 6]

# Component footprints from the requirements table: (type, x0, y0, width, height, power W).
COMPONENTS = {
    "GPU1": ("GPU", 0.00, 10.15, 26.0, 30.0, 554.4),
    "GPU2": ("GPU", 26.15, 10.15, 26.0, 30.0, 554.4),
    "H1": ("HBM", 0.00, 40.30, 12.0, 10.0, 48.0),
    "H2": ("HBM", 14.00, 40.30, 12.0, 10.0, 48.0),
    "H3": ("HBM", 26.15, 40.30, 12.0, 10.0, 48.0),
    "H4": ("HBM", 40.15, 40.30, 12.0, 10.0, 48.0),
    "H5": ("HBM", 0.00, 0.00, 12.0, 10.0, 48.0),
    "H6": ("HBM", 14.00, 0.00, 12.0, 10.0, 48.0),
    "H7": ("HBM", 26.15, 0.00, 12.0, 10.0, 48.0),
    "H8": ("HBM", 40.15, 0.00, 12.0, 10.0, 48.0),
}


def component_cells_bottom_to_top() -> dict[str, np.ndarray]:
    """Per-component cell powers (W), row 0 = bottom (lowest y), column 0 = left."""
    gpu1 = np.array(_GPU1_TOP_TO_BOTTOM, dtype=float)[::-1]
    gpu2 = gpu1[:, ::-1]  # GPU2 is drawn as the mirror image of GPU1
    hbm_top = np.array(_HBM_TOP_ROW_TOP_TO_BOTTOM, dtype=float)[::-1]
    hbm_bottom = hbm_top[::-1]  # bottom-row stacks are mirrored: 2.0 W rows face up, toward the GPUs
    cells = {"GPU1": gpu1, "GPU2": gpu2}
    for name in ("H1", "H2", "H3", "H4"):
        cells[name] = hbm_top.copy()
    for name in ("H5", "H6", "H7", "H8"):
        cells[name] = hbm_bottom.copy()
    for name, arr in cells.items():
        _, _, _, w, h, power = COMPONENTS[name]
        assert arr.shape == (round(h / CELL_MM), round(w / CELL_MM)), name
        assert abs(arr.sum() - power) < 1e-9, (name, arr.sum(), power)
    return cells


def rasterize(cells: dict[str, np.ndarray]) -> np.ndarray:
    """Exact area-weighted average flux (W/mm^2) on the 0.5 mm die-region grid."""
    nx = int(np.ceil(DIE_REGION_MM[0] / GRID_PITCH_MM))
    ny = int(np.ceil(DIE_REGION_MM[1] / GRID_PITCH_MM))
    xe = np.arange(nx + 1) * GRID_PITCH_MM
    ye = np.arange(ny + 1) * GRID_PITCH_MM
    power = np.zeros((ny, nx))
    for name, arr in cells.items():
        _, x0, y0, _, _, _ = COMPONENTS[name]
        for r in range(arr.shape[0]):
            for c in range(arr.shape[1]):
                if arr[r, c] == 0.0:
                    continue
                cx0, cy0 = x0 + c * CELL_MM, y0 + r * CELL_MM
                ox = np.clip(np.minimum(xe[1:], cx0 + CELL_MM) - np.maximum(xe[:-1], cx0), 0.0, None)
                oy = np.clip(np.minimum(ye[1:], cy0 + CELL_MM) - np.maximum(ye[:-1], cy0), 0.0, None)
                power += np.outer(oy, ox) * (arr[r, c] / CELL_MM**2)
    return power / GRID_PITCH_MM**2


def main() -> None:
    cells = component_cells_bottom_to_top()
    flux = rasterize(cells)
    total = flux.sum() * GRID_PITCH_MM**2
    assert abs(total - 1492.8) < 1e-6, total

    doc = {
        "description": "ITherm 2027 package power map transcribed from the competition figure "
        "(METTL Slides Week Oct 19.pptx). Values are watts per 2 mm x 2 mm cell.",
        "frame": "die region (52.15 x 50.30 mm), origin at its lower-left corner, x right, y up",
        "cell_size_mm": CELL_MM,
        "row_order": "row 0 = bottom (lowest y) of each component footprint",
        "verified_sums_W": {name: float(arr.sum()) for name, arr in cells.items()},
        "total_W": float(sum(arr.sum() for arr in cells.values())),
        "peak_flux_W_per_cm2": float(max(arr.max() for arr in cells.values()) / (CELL_MM**2 / 100.0)),
        "components": {
            name: {
                "type": COMPONENTS[name][0],
                "x0_mm": COMPONENTS[name][1],
                "y0_mm": COMPONENTS[name][2],
                "width_mm": COMPONENTS[name][3],
                "height_mm": COMPONENTS[name][4],
                "power_W": COMPONENTS[name][5],
                "cells_W": arr.tolist(),
            }
            for name, arr in cells.items()
        },
    }
    (FIXTURES / "itherm_figure_power_map.json").write_text(json.dumps(doc, indent=1) + "\n", encoding="utf-8")

    out_dir = FIXTURES / "reference_files"
    out_dir.mkdir(parents=True, exist_ok=True)
    with (out_dir / "power_map_W_per_mm2.csv").open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        for row in flux:  # row 0 = bottom (y = 0.25 mm)
            writer.writerow([f"{v:.6g}" for v in row])
    print(f"grid {flux.shape[1]} x {flux.shape[0]} cells, total {total:.4f} W, peak {flux.max() * 100:.1f} W/cm^2")


if __name__ == "__main__":
    main()
