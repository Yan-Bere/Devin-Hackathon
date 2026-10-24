import argparse
from datetime import datetime
import json
import math
import os
import random
import re
import socket
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path


FIELDS = ("Ux", "Uy", "Uz", "h", "p_rgh")
RESIDUAL_PROFILES = {
    "Ux": (0.12, 0.045, 1e-6, 0.10),
    "Uy": (0.075, 0.032, 4e-6, 0.12),
    "Uz": (0.19, 0.039, 8e-6, 0.28),
    "h": (0.5, 0.028, 1e-5, 0.10),
    "p_rgh": (1.0, 0.018, 1e-4, 0.12),
}


def sample_params(rng: random.Random) -> dict:
    fin_count = rng.randint(8, 40)
    max_thickness = min(2.0, 39.5 / fin_count)
    return {
        "fin_count": fin_count,
        "fin_height_mm": round(rng.uniform(5.0, 30.0), 2),
        "fin_thickness_mm": round(rng.uniform(0.5, max_thickness), 3),
        "base_thickness_mm": round(rng.uniform(1.0, 5.0), 2),
        "inlet_velocity_m_s": round(rng.uniform(1.0, 5.0), 2),
    }


def _targets(params: dict, rng: random.Random) -> tuple[float, float, float]:
    count = params["fin_count"]
    height = params["fin_height_mm"]
    thickness = params["fin_thickness_mm"]
    velocity = params["inlet_velocity_m_s"]
    gap = max(0.05, (40.0 - count * thickness) / max(count - 1, 1))
    pressure = 20.0 + 0.42 * velocity**2 * (5.0 + 12.0 * height / (gap + 2.0))
    area_m2 = (1600.0 + 2.0 * count * 40.0 * height) * 1e-6
    h_conv = 25.0 + 18.0 * velocity
    max_temperature = 320.0 + 18.0 / (h_conv * area_m2)
    pressure *= rng.uniform(0.97, 1.03)
    max_temperature *= rng.uniform(0.985, 1.015)
    mean_temperature = max_temperature - rng.uniform(2.0, 7.0)
    return pressure, max_temperature, mean_temperature


def _normal(a, b, c):
    u = (b[0] - a[0], b[1] - a[1], b[2] - a[2])
    v = (c[0] - a[0], c[1] - a[1], c[2] - a[2])
    normal = (
        u[1] * v[2] - u[2] * v[1],
        u[2] * v[0] - u[0] * v[2],
        u[0] * v[1] - u[1] * v[0],
    )
    length = math.sqrt(sum(value * value for value in normal)) or 1.0
    return tuple(value / length for value in normal)


def _box_triangles(x0, y0, z0, x1, y1, z1):
    faces = [
        ((x0, y0, z0), (x0, y1, z0), (x1, y1, z0), (x1, y0, z0)),
        ((x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1)),
        ((x0, y0, z0), (x1, y0, z0), (x1, y0, z1), (x0, y0, z1)),
        ((x0, y1, z0), (x0, y1, z1), (x1, y1, z1), (x1, y1, z0)),
        ((x0, y0, z0), (x0, y0, z1), (x0, y1, z1), (x0, y1, z0)),
        ((x1, y0, z0), (x1, y1, z0), (x1, y1, z1), (x1, y0, z1)),
    ]
    for a, b, c, d in faces:
        yield a, b, c
        yield a, c, d


def write_geometry(path: Path, params: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    count = params["fin_count"]
    thickness = params["fin_thickness_mm"]
    height = params["fin_height_mm"]
    base_thickness = params["base_thickness_mm"]
    gap = max(0.0, (40.0 - count * thickness) / max(count - 1, 1))
    z_fin = 1.0 + base_thickness
    boxes = [
        (10.0, 10.0, 0.0, 30.0, 30.0, 1.0),
        (0.0, 0.0, 1.0, 40.0, 40.0, z_fin),
    ]
    for fin in range(count):
        x0 = fin * (thickness + gap)
        boxes.append((x0, 0.0, z_fin, x0 + thickness, 40.0, z_fin + height))
    with path.open("w") as stl:
        stl.write("solid heatsink\n")
        for box in boxes:
            for triangle in _box_triangles(*box):
                normal = _normal(*triangle)
                stl.write(
                    "  facet normal "
                    + " ".join(f"{value:.7g}" for value in normal)
                    + "\n    outer loop\n"
                )
                for vertex in triangle:
                    stl.write(
                        "      vertex " + " ".join(f"{value:.7g}" for value in vertex) + "\n"
                    )
                stl.write("    endloop\n  endfacet\n")
        stl.write("endsolid heatsink\n")


def _ensure_static_case(case_dir: Path, params: dict) -> None:
    case_dir.mkdir(parents=True, exist_ok=True)
    (case_dir / "params.json").write_text(json.dumps(params, indent=2) + "\n")
    system_dir = case_dir / "system"
    system_dir.mkdir(parents=True, exist_ok=True)
    (system_dir / "controlDict").write_text(
        "FoamFile\n{\n    version 2.0;\n    format ascii;\n"
        "    class dictionary;\n    object controlDict;\n}\n"
        "application chtMultiRegionFoam;\nstartFrom startTime;\n"
        "startTime 0;\nstopAt endTime;\nendTime 500;\ndeltaT 1;\n"
    )
    cells = int(60000 + params["fin_count"] * params["fin_height_mm"] * 160)
    (case_dir / "log.checkMesh").write_text(
        "Checking geometry...\n"
        f"    cells:            {cells}\n"
        "Mesh OK.\n"
    )
    write_geometry(case_dir / "constant" / "triSurface" / "heatsink.stl", params)
    for function, filename, header in (
        ("inletPressure", "surfaceFieldValue.dat", "# Time  areaAverage(p)\n"),
        ("outletPressure", "surfaceFieldValue.dat", "# Time  areaAverage(p)\n"),
        (
            "solidTemperature",
            "fieldMinMax.dat",
            "# Time  field  min  location(min)  processor  max  location(max)  processor\n",
        ),
        ("solidTemperatureAvg", "volFieldValue.dat", "# Time  volAverage(T)\n"),
    ):
        output = case_dir / "postProcessing" / function / "0" / filename
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(header)


def _log_header(case_dir: Path, started_at: datetime) -> str:
    return (
        "/*---------------------------------------------------------------------------*\\\n"
        "| =========                 |                                                 |\n"
        "| OpenFOAM: The Open Source CFD Toolbox                                      |\n"
        "\\*---------------------------------------------------------------------------*/\n"
        "Build  :  v2312\n"
        "Exec   :  chtMultiRegionFoam -parallel\n"
        f"Date   : {started_at.strftime('%b %d %Y')}\n"
        f"Time   : {started_at.strftime('%H:%M:%S')}\n"
        f"Host   : {socket.gethostname()}\n"
        f"PID    : {os.getpid()}\n"
        f"Case   : {case_dir.resolve()}\n"
        "nProcs : 4\n"
        "Create time\n"
        "Create mesh for time = 0\n"
    )


def _append_iteration(
    case_dir: Path,
    iteration: int,
    target_values,
    rng,
    *,
    failed: bool = False,
    failure_start: int | None = None,
    fail_at: int | None = None,
    nonconverged: bool = False,
) -> None:
    log_path = case_dir / "log.chtMultiRegionFoam"
    with log_path.open("a") as log:
        log.write(f"\nTime = {iteration}\n\n")
        for field in FIELDS:
            start, decay, floor, noise = RESIDUAL_PROFILES[field]
            if field == "p_rgh" and nonconverged:
                floor = 0.002
            initial = (floor + start * math.exp(-decay * iteration)) * rng.uniform(
                1.0 - noise, 1.0 + noise
            )
            if failed and failure_start is not None and fail_at is not None:
                if iteration >= failure_start:
                    fraction = min(
                        1.0,
                        (iteration - failure_start) / max(1, fail_at - failure_start),
                    )
                    initial *= 10 ** (4 * fraction)
            final = initial * rng.uniform(0.015, 0.08)
            solver = "GAMG" if field == "p_rgh" else "DILUPBiCGStab"
            count = 5 if field == "p_rgh" else 2
            log.write(
                f"{solver}:  Solving for {field}, Initial residual = {initial:.6g}, "
                f"Final residual = {final:.6g}, No Iterations {count}\n"
            )
        log.flush()
    if iteration % 10 != 0:
        return
    pressure, max_temperature, mean_temperature = target_values
    fraction = math.exp(-0.012 * iteration)
    pressure_value = pressure * (1.0 + 0.18 * fraction) * rng.uniform(0.997, 1.003)
    temperature_value = max_temperature + 12.0 * fraction + rng.uniform(-0.2, 0.2)
    mean_value = mean_temperature + 10.0 * fraction + rng.uniform(-0.2, 0.2)
    (case_dir / "postProcessing" / "inletPressure" / "0" / "surfaceFieldValue.dat").open(
        "a"
    ).write(f"{iteration} {pressure_value:.6f}\n")
    (case_dir / "postProcessing" / "outletPressure" / "0" / "surfaceFieldValue.dat").open(
        "a"
    ).write(f"{iteration} 0.000000\n")
    (case_dir / "postProcessing" / "solidTemperature" / "0" / "fieldMinMax.dat").open(
        "a"
    ).write(
        f"{iteration} T 300.00 (0.001 0.002 0.0005) 0 "
        f"{temperature_value:.6f} (0.02 0.02 0.0001) 0\n"
    )
    (case_dir / "postProcessing" / "solidTemperatureAvg" / "0" / "volFieldValue.dat").open(
        "a"
    ).write(f"{iteration} {mean_value:.6f}\n")


def _append_fatal(log_path: Path) -> None:
    with log_path.open("a") as log:
        log.write(
            "\n--> FOAM FATAL ERROR:\n"
            "Maximum number of iterations exceeded\n"
            "    From function solve()\n"
            "    in file fvSolution\n"
        )


def write_case(
    case_dir: Path,
    params: dict,
    seed: int = 0,
    *,
    failed: bool = False,
    nonconverged: bool = False,
    iterations: int = 500,
    run_seconds: float = 0.0,
) -> None:
    rng = random.Random(seed)
    targets = _targets(params, rng)
    _ensure_static_case(case_dir, params)
    log_path = case_dir / "log.chtMultiRegionFoam"
    started_at = datetime.now().astimezone()
    log_path.write_text(_log_header(case_dir, started_at))
    if run_seconds:
        # Spread updates across the requested wall time rather than tying them to solver time.
        interval = run_seconds / max(1, iterations)
    else:
        interval = 0.0
    fail_at = max(10, int(iterations * rng.uniform(0.45, 0.8))) if failed else iterations + 1
    failure_start = max(1, fail_at - rng.randint(20, 40)) if failed else None
    for iteration in range(1, iterations + 1):
        if failed and iteration >= fail_at:
            _append_fatal(log_path)
            return
        _append_iteration(
            case_dir,
            iteration,
            targets,
            rng,
            failed=failed,
            failure_start=failure_start,
            fail_at=fail_at,
            nonconverged=nonconverged,
        )
        if interval:
            time.sleep(interval)
    with log_path.open("a") as log:
        log.write("\nEnd\n")


def write_complete_case(
    case_dir: Path,
    index: int = 1,
    params: dict | None = None,
    seed: int = 0,
) -> Path:
    rng = random.Random(seed + index)
    params = params or sample_params(rng)
    write_case(case_dir, params, seed + index, iterations=500)
    return Path(case_dir)


def _next_index(runs_dir: Path) -> int:
    indices = []
    for path in runs_dir.glob("run_*"):
        match = re.search(r"(\d+)$", path.name)
        if match and path.is_dir():
            indices.append(int(match.group(1)))
    return max(indices, default=0) + 1


def run_generator(
    runs_dir: Path,
    budget: int = 40,
    concurrency: int = 2,
    run_seconds: float = 25.0,
    seed: int = 0,
) -> None:
    runs_dir = Path(runs_dir)
    runs_dir.mkdir(parents=True, exist_ok=True)
    first_index = _next_index(runs_dir)
    jobs = []
    with ThreadPoolExecutor(max_workers=max(1, concurrency)) as executor:
        for offset in range(max(0, budget)):
            index = first_index + offset
            rng = random.Random(seed + index)
            params = sample_params(rng)
            should_fail = index % 10 == seed % 10
            jobs.append(
                executor.submit(
                    write_case,
                    runs_dir / f"run_{index:04d}",
                    params,
                    seed + index,
                    failed=should_fail,
                    nonconverged=index % 7 == seed % 7,
                    iterations=500,
                    run_seconds=run_seconds * rng.uniform(0.6, 1.4),
                )
            )
        for job in as_completed(jobs):
            job.result()


def main():
    parser = argparse.ArgumentParser(description="Generate synthetic OpenFOAM case runs")
    parser.add_argument("--runs-dir", type=Path, required=True)
    parser.add_argument("--budget", type=int, default=40)
    parser.add_argument("--concurrency", type=int, default=2)
    parser.add_argument("--run-seconds", type=float, default=25.0)
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()
    run_generator(
        runs_dir=args.runs_dir,
        budget=args.budget,
        concurrency=args.concurrency,
        run_seconds=args.run_seconds,
        seed=args.seed,
    )


if __name__ == "__main__":
    main()
