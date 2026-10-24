"""Power-map models: heat-flux distributions over the plate footprint.

``flux_on_grid(x_edges_mm, y_edges_mm)`` returns the cell-average flux in
W/m^2 on an arbitrary rectilinear grid in the PLATE frame, computed by exact
area-overlap integration — so integrated power is conserved on any grid.

``component_powers(x_edges_mm, y_edges_mm)`` attributes that grid's power to
each named heat source by footprint overlap.
"""

from __future__ import annotations

import io
import math
from abc import ABC, abstractmethod
from typing import NamedTuple, Optional, Sequence

import numpy as np

from coldplate.units import convert


class Footprint(NamedTuple):
    """A rectangular heat-source footprint in the PLATE frame (mm)."""

    name: str
    type: str
    x0: float
    y0: float
    x1: float
    y1: float
    power_W: float

    @property
    def area_mm2(self) -> float:
        return (self.x1 - self.x0) * (self.y1 - self.y0)


def _overlap(edges: np.ndarray, lo: float, hi: float) -> np.ndarray:
    """Overlap length of each interval [edges[i], edges[i+1]] with [lo, hi]."""
    return np.clip(np.minimum(edges[1:], hi) - np.maximum(edges[:-1], lo), 0.0, None)


class PowerMap(ABC):
    kind: str = "abstract"
    description: str = ""

    @abstractmethod
    def flux_on_grid(
        self, x_edges_mm: Sequence[float], y_edges_mm: Sequence[float]
    ) -> np.ndarray:
        """Cell-average flux [ny, nx] in W/m^2 on the given plate-frame grid."""

    @property
    @abstractmethod
    def sources(self) -> tuple[Footprint, ...]:
        """Heat-source footprints (plate frame)."""

    def component_powers(
        self, x_edges_mm: Sequence[float], y_edges_mm: Sequence[float]
    ) -> dict[str, float]:
        """Map power integrated over each component footprint on this grid (W).

        Cells straddling a footprint boundary are attributed by area fraction,
        so the result converges to the stated powers on fine grids.
        """
        xe = np.asarray(x_edges_mm, dtype=float)
        ye = np.asarray(y_edges_mm, dtype=float)
        flux = self.flux_on_grid(xe, ye)  # W/m^2, [ny, nx]
        out: dict[str, float] = {}
        for s in self.sources:
            ov = np.outer(_overlap(ye, s.y0, s.y1), _overlap(xe, s.x0, s.x1))
            out[s.name] = float((flux * ov * 1e-6).sum())
        return out

    def total_power(self, x_edges_mm: Sequence[float], y_edges_mm: Sequence[float]) -> float:
        xe = np.asarray(x_edges_mm, dtype=float)
        ye = np.asarray(y_edges_mm, dtype=float)
        flux = self.flux_on_grid(xe, ye)
        cell_area = np.outer(np.diff(ye), np.diff(xe)) * 1e-6
        return float((flux * cell_area).sum())


class UniformPowerMap(PowerMap):
    """Uniform flux over each source footprint (P / footprint area)."""

    kind = "uniform"

    def __init__(self, sources: Sequence[Footprint], description: str = "") -> None:
        self._sources = tuple(sources)
        self.description = description or "uniform flux per component"

    @property
    def sources(self) -> tuple[Footprint, ...]:
        return self._sources

    def flux_on_grid(self, x_edges_mm, y_edges_mm) -> np.ndarray:
        xe = np.asarray(x_edges_mm, dtype=float)
        ye = np.asarray(y_edges_mm, dtype=float)
        acell = np.outer(np.diff(ye), np.diff(xe))  # mm^2
        flux = np.zeros((ye.size - 1, xe.size - 1))  # W/mm^2 first
        for s in self._sources:
            if s.area_mm2 <= 0 or s.power_W is None:
                continue
            ov = np.outer(_overlap(ye, s.y0, s.y1), _overlap(xe, s.x0, s.x1))
            flux += (s.power_W / s.area_mm2) * ov / acell
        return flux * 1e6  # W/mm^2 -> W/m^2


class GridPowerMap(PowerMap):
    """Cell-wise heat-flux map from a CSV grid (native frame = heat-source frame).

    The CSV's cell (i, j) covers ``[x0 + j*pitch, x0 + (j+1)*pitch]`` x
    ``[y0 + i*pitch, y0 + (i+1)*pitch]`` where (x0, y0) is the map origin in
    plate-frame mm. With ``row0="top"`` file row 0 is the highest-y row.
    """

    kind = "file"

    def __init__(
        self,
        values_W_mm2: np.ndarray,
        pitch_mm: float,
        origin_plate_mm: tuple[float, float],
        sources: Sequence[Footprint],
        file_name: str = "",
        description: str = "",
    ) -> None:
        # values indexed [row][col]; row 0 = lowest y in the map frame
        self._v = np.asarray(values_W_mm2, dtype=float)
        self._pitch = float(pitch_mm)
        self._ox, self._oy = float(origin_plate_mm[0]), float(origin_plate_mm[1])
        self._sources = tuple(sources)
        self.file_name = file_name
        self.description = description or f"heat-flux grid {file_name}"
        r, c = self._v.shape
        self._x_edges = self._ox + self._pitch * np.arange(c + 1)
        self._y_edges = self._oy + self._pitch * np.arange(r + 1)

    @property
    def sources(self) -> tuple[Footprint, ...]:
        return self._sources

    @property
    def shape(self) -> tuple[int, int]:
        return self._v.shape

    @property
    def pitch_mm(self) -> float:
        return self._pitch

    @property
    def values_W_mm2(self) -> np.ndarray:
        """Native cell values (row 0 = bottom), W/mm^2."""
        return self._v

    @classmethod
    def from_csv(
        cls,
        data: bytes,
        *,
        pitch_mm: float,
        origin_plate_mm: tuple[float, float],
        row0: str = "bottom",
        units: str = "W/mm^2",
        sources: Sequence[Footprint] = (),
        file_name: str = "",
        description: str = "",
    ) -> "GridPowerMap":
        text = data.decode("utf-8-sig", errors="replace")
        rows = [
            [float(x) for x in line.split(",")]
            for line in text.strip().splitlines()
            if line.strip()
        ]
        v = np.array(rows, dtype=float)
        if v.ndim != 2 or v.size == 0:
            raise ValueError("power map CSV is empty or not 2-D")
        if str(row0).strip().lower().startswith("top"):
            v = np.flipud(v)
        # convert file units to W/mm^2: file value is flux in `units`
        v_Wm2 = convert(1.0, units, "heat_flux")  # W/m^2 per unit
        v_mm2 = v * (v_Wm2 * 1e-6)
        return cls(v_mm2, pitch_mm, origin_plate_mm, sources, file_name, description)

    def flux_on_grid(self, x_edges_mm, y_edges_mm) -> np.ndarray:
        xe = np.asarray(x_edges_mm, dtype=float)
        ye = np.asarray(y_edges_mm, dtype=float)
        # overlap of each output cell edge range with each native cell
        # cell-by-cell overlap matrices: out_x[j, c], out_y[i, r]
        ox = np.clip(
            np.minimum(xe[1:, None], self._x_edges[None, 1:])
            - np.maximum(xe[:-1, None], self._x_edges[None, :-1]),
            0.0,
            None,
        )  # [nx_out, C]
        oy = np.clip(
            np.minimum(ye[1:, None], self._y_edges[None, 1:])
            - np.maximum(ye[:-1, None], self._y_edges[None, :-1]),
            0.0,
            None,
        )  # [ny_out, R]
        weighted = oy @ self._v @ ox.T  # [ny_out, nx_out], W/mm^2 * mm^2
        acell = np.outer(np.diff(ye), np.diff(xe))
        return weighted / acell * 1e6  # -> W/m^2

    def _footprint_overlaps(self) -> tuple[np.ndarray, np.ndarray]:
        """(stack [R,C,K] of cell-footprint overlap areas, totals [R,C])."""
        if not self._sources:
            return np.zeros(self._v.shape + (0,)), np.zeros(self._v.shape)
        stack = np.stack(
            [
                np.outer(
                    _overlap(self._y_edges, s.y0, s.y1),
                    _overlap(self._x_edges, s.x0, s.x1),
                )
                for s in self._sources
            ],
            axis=2,
        )
        return stack, stack.sum(axis=2)

    def attributed_powers(self) -> tuple[dict[str, float], float]:
        """(per-component attributed power, power in cells touching no footprint).

        Each cell's power goes to the footprints it overlaps in proportion to
        overlap area — a boundary cell inside ONE footprint gives it all its
        power, so tiling artefacts do not under-count components.
        """
        stack, total = self._footprint_overlaps()
        cell_p = self._v * self._pitch**2
        out: dict[str, float] = {}
        touched = total > 0
        for k, s in enumerate(self._sources):
            share = np.zeros(self._v.shape)
            share[touched] = stack[:, :, k][touched] / total[touched]
            out[s.name] = float((cell_p * share).sum())
        outside = float(cell_p[~touched].sum())
        return out, outside

    def native_component_powers(self) -> dict[str, float]:
        """Alias for attributed_powers (footprint-only part)."""
        return self.attributed_powers()[0]

    def rescale_components(
        self,
        stated_powers: dict[str, float],
        total_tol: float = 0.01,
        comp_tol: float = 0.05,
    ) -> list[str]:
        """Policy: if |map total − Σ stated| <= total_tol, keep the map and only
        warn about per-component deviations > comp_tol. Otherwise rescale each
        component's attributed share to its stated power (shared boundary cells
        get each share scaled by its own factor) and warn per component.
        Returns warning strings.
        """
        warnings: list[str] = []
        attributed, _outside = self.attributed_powers()
        stated_total = sum(v for v in stated_powers.values() if v is not None)
        map_total = float(self._v.sum() * self._pitch**2)
        if stated_total <= 0:
            return warnings
        if abs(map_total - stated_total) / stated_total <= total_tol:
            for s in self._sources:
                want = stated_powers.get(s.name)
                got = attributed.get(s.name, 0.0)
                if want and not math.isclose(got, want, rel_tol=comp_tol):
                    warnings.append(
                        f"power map component {s.name}: attributed {got:.2f} W "
                        f"differs from stated {want:.2f} W by >5% (map kept as is)"
                    )
            return warnings
        # rescale per component on its attributed share
        stack, total = self._footprint_overlaps()
        touched = total > 0
        scale = np.zeros(self._v.shape)
        for k, s in enumerate(self._sources):
            want = stated_powers.get(s.name)
            got = attributed.get(s.name, 0.0)
            if want and got > 0:
                f = want / got
                warnings.append(
                    f"power map component {s.name}: attributed {got:.2f} W, "
                    f"stated {want:.2f} W — rescaled by {f:.4f}"
                )
            else:
                f = 1.0
            share = np.zeros(self._v.shape)
            share[touched] = stack[:, :, k][touched] / total[touched]
            scale += share * f
        # untouched cells keep their value; shared cells get the share-weighted factor
        self._v = np.where(touched, self._v * scale, self._v)
        return warnings
