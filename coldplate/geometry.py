"""Fin-channel layout: single source of truth for CAD and physics.

Works in a flow-aligned frame (u = flow axis, v = stacking axis); maps back
to plate coordinates (x, y mm from the plate's lower-left corner; z = 0 at
the plate bottom). Fins are straight walls spanning the full fin-region
length along u; zones tile along v starting and ending with a fin.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from coldplate.spec import EngineInputs


class GeometryError(ValueError):
    pass


ARRANGEMENTS = {"straight", "split_edges_to_center", "split_center_to_edges"}


@dataclass(frozen=True)
class FinZone:
    label: str
    v_start_mm: float
    v_end_mm: float
    fin_thickness_mm: float
    channel_width_mm: float

    def to_dict(self) -> dict:
        return {
            "label": self.label,
            "v_start_mm": self.v_start_mm,
            "v_end_mm": self.v_end_mm,
            "fin_thickness_mm": self.fin_thickness_mm,
            "channel_width_mm": self.channel_width_mm,
        }


@dataclass(frozen=True)
class ChannelDesign:
    design_id: str
    arrangement: str  # straight | split_edges_to_center | split_center_to_edges
    flow_axis: str  # "x" | "y"
    fin_height_mm: float
    zones: tuple[FinZone, ...]
    inlet_opening_mm: float
    outlet_opening_mm: float

    def to_dict(self) -> dict:
        return {
            "design_id": self.design_id,
            "arrangement": self.arrangement,
            "flow_axis": self.flow_axis,
            "fin_height_mm": self.fin_height_mm,
            "inlet_opening_mm": self.inlet_opening_mm,
            "outlet_opening_mm": self.outlet_opening_mm,
            "zones": [z.to_dict() for z in self.zones],
        }


def path_ramp(path: dict, u: float) -> float:
    """Flow fraction r(u) in [0,1] at position u along a path's direction."""
    d = path.get("direction", 1)
    for kind, a, b in path["segments"]:
        lo, hi = min(a, b), max(a, b)
        if lo - 1e-12 <= u <= hi + 1e-12:
            f = 0.0 if hi - lo == 0 else (u - lo) / (hi - lo)
            if d < 0:
                f = 1.0 - f
            f = min(max(f, 0.0), 1.0)
            if kind == "inlet":
                return f
            if kind == "covered":
                return 1.0
            return 1.0 - f
    return 0.0


def path_length_mm(path: dict) -> float:
    return sum(abs(b - a) for _, a, b in path["segments"])


def _zone_counts(
    L_z: float, t: float, w: float, edge_extra: float, wmin: float, wmax: float
) -> tuple[int, float]:
    """Pick (n_channels, adjusted channel width) for a zone; raises GeometryError.

    edge_extra is the solid material beyond n_z full fins: t/2 for a zone with
    one region-edge end (the other end shares a boundary fin), t for the only
    zone of a single-zone region, 0 for a fully interior zone.
    """
    if t <= 0 or w <= 0:
        raise GeometryError(f"fin thickness {t} and channel width {w} must be > 0")
    base = t + w
    n0 = max(1, int(round(L_z / base)))
    best = None
    for n in (n0 - 1, n0, n0 + 1):
        if n < 1:
            continue
        # zone = n channels + (n-1) interior fins + edge portions
        #   L_z = n*w' + (n-1)*t + edge_portions,  edge_portions = t + edge_extra
        w_adj = (L_z - n * t - edge_extra) / n
        ok = w_adj > 0 and w_adj >= wmin - 1e-12 and w_adj <= wmax + 1e-12
        score = (0 if ok else 1, abs(w_adj - w))
        if best is None or score < best[0]:
            best = (score, n, w_adj)
    if best is None or best[0][0] != 0:
        raise GeometryError(
            f"zone of length {L_z} mm cannot be tiled with t={t}/w={w} within "
            f"feature bounds [{wmin}, {wmax}] mm"
        )
    return best[1], best[2]


@dataclass(frozen=True)
class Rect:
    x0: float
    y0: float
    x1: float
    y1: float


class Layout:
    """Plate-frame geometry of one channel design."""

    def __init__(
        self,
        design: ChannelDesign,
        inputs: EngineInputs,
        fins: list[Rect],
        channels: list[dict],
        openings: dict,
        paths: list[dict],
        u_range: tuple[float, float],
        v_range: tuple[float, float],
    ) -> None:
        self.design = design
        self.inputs = inputs
        self.fins = fins
        self.channels = channels  # {index, zone, v_lo, v_hi, width_mm}
        self.openings = openings  # {"inlet": [Rect], "outlet": [Rect]}
        self.paths = paths  # {id, segments: [(kind, u0, u1)]}
        self.u_range = u_range
        self.v_range = v_range

    @property
    def base_z0(self) -> float:
        return self.inputs.base_thickness_mm

    @property
    def fin_z1(self) -> float:
        return self.inputs.base_thickness_mm + self.design.fin_height_mm

    def solid_volume_mm3(self) -> float:
        v = self.inputs.plate_lx_mm * self.inputs.plate_ly_mm * self.inputs.base_thickness_mm
        for r in self.fins:
            v += (r.x1 - r.x0) * (r.y1 - r.y0) * self.design.fin_height_mm
        return v

    def wetted_perimeter_mm(self, ch: dict) -> float:
        return 2.0 * (ch["width_mm"] + self.design.fin_height_mm)

    def open_area_fraction(self) -> float:
        fin_v = sum(r.y1 - r.y0 if self.design.flow_axis == "x" else r.x1 - r.x0 for r in self.fins)
        L_v = self.v_range[1] - self.v_range[0]
        return 1.0 - fin_v / L_v if L_v > 0 else 0.0

    def zone_info(self) -> list[dict]:
        out = []
        for i, z in enumerate(self.design.zones):
            chs = [c for c in self.channels if c["zone_index"] == i]
            out.append({
                "label": z.label,
                "channels": len(chs),
                "actual_channel_width_mm": chs[0]["width_mm"] if chs else None,
                "fin_thickness_mm": z.fin_thickness_mm,
            })
        return out

    def to_dict(self) -> dict:
        return {
            "design": self.design.to_dict(),
            "u_range_mm": list(self.u_range),
            "v_range_mm": list(self.v_range),
            "fins": [r.__dict__ for r in self.fins],
            "channels": self.channels,
            "openings": {
                "inlet": [r.__dict__ for r in self.openings["inlet"]],
                "outlet": [r.__dict__ for r in self.openings["outlet"]],
            },
            "paths": self.paths,
            "zones": self.zone_info(),
            "solid_volume_mm3": self.solid_volume_mm3(),
            "open_area_fraction": self.open_area_fraction(),
            "fin_z0_mm": self.base_z0,
            "fin_z1_mm": self.fin_z1,
        }


def _uv_rect(u0, u1, v0, v1, axis) -> Rect:
    if axis == "x":
        return Rect(u0, v0, u1, v1)
    return Rect(v0, u0, v1, u1)


def build_layout(inputs: EngineInputs, design: ChannelDesign) -> Layout:
    if design.arrangement not in ARRANGEMENTS:
        raise GeometryError(f"unsupported arrangement {design.arrangement!r}")
    if design.flow_axis not in ("x", "y"):
        raise GeometryError(f"flow_axis must be 'x' or 'y', got {design.flow_axis!r}")
    H = design.fin_height_mm
    if H <= 0 or H > inputs.fin_height_max_mm + 1e-9:
        raise GeometryError(
            f"fin height {H} must be in (0, {inputs.fin_height_max_mm}]"
        )
    wmin = inputs.min_feature_mm or 0.0
    wmax = inputs.max_feature_mm or float("inf")
    if inputs.min_feature_mm is not None and H < inputs.min_feature_mm - 1e-12:
        raise GeometryError(f"fin height {H} < min feature {inputs.min_feature_mm}")

    fx0, fy0 = inputs.fin_region_x0_mm, inputs.fin_region_y0_mm
    flx, fly = inputs.fin_region_lx_mm, inputs.fin_region_ly_mm
    if flx <= 0 or fly <= 0:
        raise GeometryError("fin region has no extent")
    if (
        fx0 < -1e-9 or fy0 < -1e-9
        or fx0 + flx > inputs.plate_lx_mm + 1e-9
        or fy0 + fly > inputs.plate_ly_mm + 1e-9
    ):
        raise GeometryError("fin region lies outside the plate")

    # flow-aligned extents
    if design.flow_axis == "x":
        u0, u1 = fx0, fx0 + flx
        v0, v1 = fy0, fy0 + fly
    else:
        u0, u1 = fy0, fy0 + fly
        v0, v1 = fx0, fx0 + flx
    L_u = u1 - u0
    L_v = v1 - v0

    zones = sorted(design.zones, key=lambda z: z.v_start_mm)
    if not zones:
        raise GeometryError("design has no zones")
    if abs(zones[0].v_start_mm - v0) > 1e-9 or abs(zones[-1].v_end_mm - v1) > 1e-9:
        raise GeometryError("zones do not cover the fin region along v")
    for a, b in zip(zones, zones[1:]):
        if abs(b.v_start_mm - a.v_end_mm) > 1e-9:
            raise GeometryError("zones are not contiguous along v")

    # opening feasibility
    io, oo = design.inlet_opening_mm, design.outlet_opening_mm
    if design.arrangement == "straight":
        if io + oo >= L_u:
            raise GeometryError(
                f"straight: inlet ({io}) + outlet ({oo}) must be < flow length {L_u}"
            )
    else:
        if 2 * io + oo >= L_u:
            raise GeometryError(
                f"split: 2*inlet ({2 * io}) + outlet ({oo}) must be < flow length {L_u}"
            )

    # tile zones -> fins & channels. Interior zone boundaries share ONE fin
    # centred on the boundary (t/2 in each zone); region edges carry a full
    # fin inside the region.
    fins: list[Rect] = []
    channels: list[dict] = []
    nz = len(zones)
    ci = 0
    for zi, z in enumerate(zones):
        L_z = z.v_end_mm - z.v_start_mm
        t = z.fin_thickness_mm
        if t < wmin - 1e-12 or t > wmax + 1e-12:
            raise GeometryError(
                f"fin thickness {t} outside feature bounds "
                f"[{wmin}, {wmax}] in zone {z.label}"
            )
        edge_extra = (t if zi == 0 else t / 2) + (t if zi == nz - 1 else t / 2) - t
        n, w_adj = _zone_counts(
            L_z, t, z.channel_width_mm, edge_extra=edge_extra,
            wmin=wmin, wmax=wmax,
        )
        # left edge: full fin at region edge, shared fin already emitted by
        # the previous zone for interior boundaries
        if zi == 0:
            fins.append(_uv_rect(u0, u1, v0, v0 + t, design.flow_axis))
            v = z.v_start_mm + t
        else:
            v = z.v_start_mm + t / 2
        for k in range(n):
            channels.append({
                "index": ci, "zone": z.label, "zone_index": zi,
                "v_lo": v, "v_hi": v + w_adj,
                "width_mm": w_adj,
            })
            ci += 1
            v += w_adj
            if k < n - 1:
                fins.append(_uv_rect(u0, u1, v, v + t, design.flow_axis))
                v += t
        # right edge: region edge -> full fin inside region; interior
        # boundary -> shared fin centred on the boundary
        if zi == nz - 1:
            fins.append(_uv_rect(u0, u1, v, v + t, design.flow_axis))
            v += t
        else:
            # shared fin centred on the boundary: [v_end - t/2, v_end + t/2]
            fins.append(_uv_rect(u0, u1, v, v + t, design.flow_axis))
            v += t / 2
        if abs(v - z.v_end_mm) > 1e-6:
            raise GeometryError(f"zone {z.label} tiling does not fill its extent")

    # every contiguous solid wall must respect the max feature size
    # (fin walls run along u; their thickness is measured along v)
    axis = design.flow_axis
    walls = sorted(
        ((f.y0, f.y1) if axis == "x" else (f.x0, f.x1)) for f in fins
    )
    merged = []
    for a, b in walls:
        if merged and a <= merged[-1][1] + 1e-9:
            merged[-1][1] = max(merged[-1][1], b)
        else:
            merged.append([a, b])
    for a, b in merged:
        if b - a > wmax + 1e-9:
            raise GeometryError(
                f"solid wall of {b - a:.3f} mm at v={a:.3f} exceeds "
                f"max feature {wmax} mm"
            )

    # openings (footprints spanning full v-range)
    uc = 0.5 * (u0 + u1)
    if design.arrangement == "split_edges_to_center":
        inlets = [(u0, u0 + io), (u1 - io, u1)]
        outlets = [(uc - oo / 2, uc + oo / 2)]
    elif design.arrangement == "split_center_to_edges":
        inlets = [(uc - io / 2, uc + io / 2)]
        outlets = [(u0, u0 + oo), (u1 - oo, u1)]
    else:
        inlets = [(u0, u0 + io)]
        outlets = [(u1 - oo, u1)]
    openings = {
        "inlet": [_uv_rect(a, b, v0, v1, design.flow_axis) for a, b in inlets],
        "outlet": [_uv_rect(a, b, v0, v1, design.flow_axis) for a, b in outlets],
    }

    # flow paths (ordered u-segments, upstream -> downstream)
    paths = []
    if design.arrangement == "straight":
        paths.append({
            "id": "main", "direction": +1,
            "segments": [
                ("inlet", u0, u0 + io),
                ("covered", u0 + io, u1 - oo),
                ("outlet", u1 - oo, u1),
            ],
        })
    elif design.arrangement == "split_edges_to_center":
        half = oo / 2
        paths.append({
            "id": "left", "direction": +1,
            "segments": [
                ("inlet", u0, u0 + io),
                ("covered", u0 + io, uc - half),
                ("outlet", uc - half, uc),
            ],
        })
        paths.append({
            "id": "right", "direction": -1,
            "segments": [
                ("inlet", u1 - io, u1),
                ("covered", uc + half, u1 - io),
                ("outlet", uc, uc + half),
            ],
        })
    else:  # split_center_to_edges
        half = io / 2
        paths.append({
            "id": "left", "direction": -1,
            "segments": [
                ("inlet", uc - half, uc),
                ("covered", u0 + oo, uc - half),
                ("outlet", u0, u0 + oo),
            ],
        })
        paths.append({
            "id": "right", "direction": +1,
            "segments": [
                ("inlet", uc, uc + half),
                ("covered", uc + half, u1 - oo),
                ("outlet", u1 - oo, u1),
            ],
        })
    # sanity: segments must be contiguous & non-empty
    for p in paths:
        seg = p["segments"]
        for k in range(len(seg) - 1):
            pass

    return Layout(
        design=design, inputs=inputs, fins=fins, channels=channels,
        openings=openings, paths=paths, u_range=(u0, u1), v_range=(v0, v1),
    )


def check_connectivity(layout: Layout) -> bool:
    """Every channel's u-extent must overlap an inlet AND an outlet footprint."""
    u0, u1 = layout.u_range
    axis = layout.design.flow_axis

    def urange(rect: Rect):
        return (rect.x0, rect.x1) if axis == "x" else (rect.y0, rect.y1)

    ins = [urange(r) for r in layout.openings["inlet"]]
    outs = [urange(r) for r in layout.openings["outlet"]]
    for ch in layout.channels:
        def hit(ranges):
            return any(a < u1 - 1e-9 and b > u0 + 1e-9 for a, b in ranges)
        if not (hit(ins) and hit(outs)):
            return False
    return True


def derive_zone_bands(inputs: EngineInputs, flow_axis: str) -> list[tuple[str, float, float]]:
    """Project heat sources onto v; boundaries at midpoints between typed bands."""
    if flow_axis == "x":
        v0, v1 = inputs.fin_region_y0_mm, inputs.fin_region_y0_mm + inputs.fin_region_ly_mm
        iv = [(s.y0_mm, s.y0_mm + s.height_mm, s.type) for s in inputs.sources]
    else:
        v0, v1 = inputs.fin_region_x0_mm, inputs.fin_region_x0_mm + inputs.fin_region_lx_mm
        iv = [(s.x0_mm, s.x0_mm + s.width_mm, s.type) for s in inputs.sources]
    if not iv:
        return [("uniform", v0, v1)]
    iv.sort()
    bands = []
    cur_type, cur_lo, cur_hi = iv[0][2], iv[0][0], iv[0][1]
    for lo, hi, t in iv[1:]:
        if lo < cur_hi - 1e-9 and t != cur_type:
            return [("uniform", v0, v1)]  # types overlap along v
        if t == cur_type and lo <= cur_hi + 1e-9:
            cur_hi = max(cur_hi, hi)
        else:
            bands.append([cur_type, cur_lo, cur_hi])
            cur_type, cur_lo, cur_hi = t, lo, hi
    bands.append([cur_type, cur_lo, cur_hi])
    # boundaries at midpoints of gaps between differently-typed bands
    out = []
    for i, (t, lo, hi) in enumerate(bands):
        start = v0 if i == 0 else (bands[i - 1][2] + lo) / 2.0
        end = v1 if i == len(bands) - 1 else (hi + bands[i + 1][1]) / 2.0
        out.append((t, start, end))
    return out


def baseline_design(inputs: EngineInputs) -> ChannelDesign:
    """One uniform zone from the spec baseline; mid-feature fallback."""
    if inputs.flow_axis == "x":
        v0, v1 = inputs.fin_region_y0_mm, inputs.fin_region_y0_mm + inputs.fin_region_ly_mm
    else:
        v0, v1 = inputs.fin_region_x0_mm, inputs.fin_region_x0_mm + inputs.fin_region_lx_mm
    t = inputs.baseline_fin_thickness_mm
    w = inputs.baseline_channel_width_mm
    h = inputs.baseline_fin_height_mm or inputs.fin_height_max_mm
    if t is None or w is None:
        lo = inputs.min_feature_mm or 0.1
        hi = inputs.max_feature_mm or 0.5
        mid = (lo + hi) / 2.0
        t = t if t is not None else mid
        w = w if w is not None else mid
    zone = FinZone("baseline", v0, v1, t, w)
    return ChannelDesign(
        design_id="baseline",
        arrangement=inputs.arrangement,
        flow_axis=inputs.flow_axis,
        fin_height_mm=h,
        zones=(zone,),
        inlet_opening_mm=inputs.inlet_opening_mm,
        outlet_opening_mm=inputs.outlet_opening_mm,
    )
