"""Stage 2 entry point."""

import json
from pathlib import Path
from time import perf_counter

from .geometry import export_geometry
from .optimize import optimize


def run(requirements_path) -> dict:
    start = perf_counter()
    requirements_path = Path(requirements_path)
    document = json.loads(requirements_path.read_text(encoding="utf-8"))
    if not document.get("finalized"):
        raise ValueError("requirements_final.json must be finalized")
    fields = document.get("fields")
    if not isinstance(fields, dict):
        raise ValueError("requirements_final.json has no fields object")
    values = {
        field_id: entry["value"]
        for field_id, entry in fields.items()
    }
    result = optimize(values)
    files = export_geometry(
        values,
        requirements_path.parent,
        result["optimized"]["fin_thickness_mm"],
        result["optimized"]["gap_mm"],
    )
    result["files"] = files
    result["run_elapsed_seconds"] = perf_counter() - start
    return result
