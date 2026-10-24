"""Export the optimized straight-fin plate as CAD and mesh files."""

from math import floor
from pathlib import Path

try:
    import cadquery as cq
except Exception:
    cq = None


def _fin_centers(space_x_mm, thickness_mm, gap_mm):
    count = floor(space_x_mm / (thickness_mm + gap_mm))
    pitch = thickness_mm + gap_mm
    used_width = (count - 1) * pitch + thickness_mm
    first = -used_width / 2 + thickness_mm / 2
    return [first + index * pitch for index in range(count)]


def export_geometry(values, output_dir, thickness_mm, gap_mm):
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    stl_path = output_dir / "optimized_cold_plate.stl"
    step_path = output_dir / "optimized_cold_plate.step"
    base_x, base_y, base_z = values["base_plate_size"]
    space_x, space_y, fin_height = values["fin_design_space"]
    centers = _fin_centers(space_x, thickness_mm, gap_mm)

    if cq is not None:
        base = cq.Workplane("XY").box(
            base_x, base_y, base_z, centered=(True, True, False)
        )
        fins = (
            cq.Workplane("XY")
            .workplane(offset=base_z)
            .pushPoints([(x, 0.0) for x in centers])
            .rect(thickness_mm, space_y)
            .extrude(fin_height)
        )
        plate = base.union(fins)
        cq.exporters.export(plate, str(step_path))
        cq.exporters.export(plate, str(stl_path))
        return {
            "stl_path": str(stl_path),
            "step_path": str(step_path),
            "backend": "cadquery",
            "fin_count": len(centers),
        }

    import trimesh

    meshes = []
    base = trimesh.creation.box(extents=[base_x, base_y, base_z])
    base.apply_translation([0, 0, base_z / 2])
    meshes.append(base)
    for x in centers:
        fin = trimesh.creation.box(
            extents=[thickness_mm, space_y, fin_height]
        )
        fin.apply_translation([x, 0, base_z + fin_height / 2])
        meshes.append(fin)
    mesh = trimesh.util.concatenate(meshes)
    mesh.export(stl_path)
    return {
        "stl_path": str(stl_path),
        "step_path": None,
        "backend": "trimesh",
        "fin_count": len(centers),
    }
