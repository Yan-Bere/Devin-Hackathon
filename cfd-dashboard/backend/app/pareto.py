from collections.abc import Iterable, Mapping
from typing import Any


def pareto_ids(runs: Iterable[Any]) -> set[str]:
    candidates = []
    for run in runs:
        value = run if isinstance(run, Mapping) else run.__dict__
        metrics = value.get("metrics", {})
        pressure = metrics.get("pressure_drop_pa")
        temperature = metrics.get("max_temperature_k")
        details = value.get("details") or {}
        if (
            value.get("status") == "completed"
            and pressure is not None
            and temperature is not None
            and details.get("feasible", True) is not False
        ):
            candidates.append((str(value["id"]), float(pressure), float(temperature)))

    result = set()
    for run_id, pressure, temperature in candidates:
        dominated = any(
            other_pressure <= pressure
            and other_temperature <= temperature
            and (other_pressure < pressure or other_temperature < temperature)
            for other_id, other_pressure, other_temperature in candidates
            if other_id != run_id
        )
        if not dominated:
            result.add(run_id)
    return result
