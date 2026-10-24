"""CAD export: layout -> solid -> STEP/STL/GLB artifacts."""

from __future__ import annotations

import json
import os
import struct
from dataclasses import dataclass
from typing import Optional

import cadquery as cq

from coldplate.geometry import Layout

GLB_CONVENTION = (
    "glTF 2.0 standard: metres, +Y up; gltf = (x, z, -y)/1000 from the "
    "plate frame in mm"
)


@dataclass
class CadArtifacts:
    step_path: str
    stl_path: str
    glb_path: str
    bbox_mm: tuple
    volume_mm3: float
    model_volume_mm3: float
    fin_count: int
    is_valid: bool
    glb_convention: str


def build_solid(layout: Layout) -> cq.Workplane:
    """Base box + one Sketch of all fin rects, single extrude+union (probe S2)."""
    i = layout.inputs
    base = cq.Workplane("XY").box(
        i.plate_lx_mm, i.plate_ly_mm, i.base_thickness_mm, centered=(True, True, False)
    ).translate((i.plate_lx_mm / 2, i.plate_ly_mm / 2, 0))
    rects = [((r.x0 + r.x1) / 2, (r.y0 + r.y1) / 2, r.x1 - r.x0, r.y1 - r.y0) for r in layout.fins]
    if rects:
        sk = cq.Sketch().push([(cx, cy) for cx, cy, w, h in rects])
        for _cx, _cy, w, h in rects:
            sk = sk.rect(w, h)
        fins = (
            cq.Workplane("XY", origin=(0, 0, i.base_thickness_mm))
            .placeSketch(sk)
            .extrude(layout.design.fin_height_mm)
        )
        return base.union(fins)
    return base


def _glb_transform_probe(glb_path: str) -> str:
    """Read the GLB JSON chunk and report position bounds (detects scaling/axis)."""
    with open(glb_path, "rb") as f:
        data = f.read()
    if data[:4] != b"glTF":
        return "not a binary glTF"
    (jlen,) = struct.unpack_from("<I", data, 12)
    doc = json.loads(data[20 : 20 + jlen])
    mins, maxs = [], []
    for acc in doc.get("accessors", []):
        if acc.get("type") == "VEC3" and "min" in acc and "max" in acc:
            mins.append(acc["min"])
            maxs.append(acc["max"])
    if not mins:
        return "no position accessors"
    lo = [min(m[k] for m in mins) for k in range(3)]
    hi = [max(m[k] for m in maxs) for k in range(3)]
    return f"position bounds min={lo} max={hi}"


def export_design(
    layout: Layout,
    out_dir: str,
    *,
    name: Optional[str] = None,
    stl_tol: float = 0.05,
) -> CadArtifacts:
    os.makedirs(out_dir, exist_ok=True)
    name = name or layout.design.design_id
    solid = build_solid(layout)
    shp = solid.val()

    step_path = os.path.join(out_dir, f"{name}.step")
    stl_path = os.path.join(out_dir, f"{name}.stl")
    glb_path = os.path.join(out_dir, f"{name}.glb")
    shp.exportStep(step_path)
    shp.exportStl(stl_path, tolerance=stl_tol)

    # glTF standard: metres, +Y up -> transform a copy (scale mm->m, rotate
    # -90 deg about X so CAD +Z becomes glTF +Y and CAD +Y becomes glTF -Z)
    shp_gltf = shp.rotate((0, 0, 0), (1, 0, 0), -90).scale(0.001)
    assy = cq.Assembly()
    copper = cq.Color(0.72, 0.45, 0.20)
    assy.add(shp_gltf, name="coldplate", color=copper)
    if hasattr(assy, "export"):
        assy.export(glb_path)
    else:  # pragma: no cover - older cadquery
        assy.save(glb_path)
    convention = GLB_CONVENTION + " | probe: " + _glb_transform_probe(glb_path)

    bb = shp.BoundingBox()
    bbox = (bb.xlen, bb.ylen, bb.zlen)
    return CadArtifacts(
        step_path=step_path,
        stl_path=stl_path,
        glb_path=glb_path,
        bbox_mm=(round(bbox[0], 4), round(bbox[1], 4), round(bbox[2], 4)),
        volume_mm3=shp.Volume(),
        model_volume_mm3=layout.solid_volume_mm3(),
        fin_count=len(layout.fins),
        is_valid=bool(shp.isValid() and len(shp.Solids()) == 1),
        glb_convention=convention,
    )
