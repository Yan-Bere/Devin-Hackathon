import json
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from app.foam_parser import parse_case, parse_residuals


def _cfg():
    return SimpleNamespace(
        function_objects={
            "inlet_pressure": "inletPressure",
            "outlet_pressure": "outletPressure",
            "solid_temperature": "solidTemperature",
            "solid_temperature_avg": "solidTemperatureAvg",
        }
    )


def _base_case(path: Path):
    path.mkdir(parents=True, exist_ok=True)
    (path / "params.json").write_text(json.dumps({"fin_count": 12}))
    (path / "system").mkdir()
    (path / "system" / "controlDict").write_text(
        "application chtMultiRegionFoam;\nendTime 500;\n"
    )
    (path / "constant" / "triSurface").mkdir(parents=True)
    (path / "constant" / "triSurface" / "heatsink.stl").write_text("solid test\nendsolid\n")
    return path


def _write_function(path, function, filename, header, rows, time="0", region=None):
    root = path / "postProcessing"
    if region:
        root /= region
    output = root / function / time / filename
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(header + "\n" + "\n".join(rows) + "\n")


def test_parser_uses_header_names_and_latest_time_directory(tmp_path):
    case = _base_case(tmp_path / "run_0003")
    _write_function(
        case,
        "inletPressure",
        "surfaceFieldValue.dat",
        "# Time  areaAverage(p)",
        ["0 3"],
    )
    _write_function(
        case,
        "inletPressure",
        "surfaceFieldValue.dat",
        "# Time  areaSum(p)  areaAverage(p)",
        ["250 200 22"],
        time="250",
    )
    _write_function(
        case,
        "outletPressure",
        "surfaceFieldValue.dat",
        "# Time  areaAverage(p)",
        ["250 2"],
        time="250",
        region="fluid",
    )
    _write_function(
        case,
        "solidTemperature",
        "fieldMinMax.dat",
        "# Time  field  min  location(min)  processor  max  location(max)  processor",
        ["250 T 300 (0.001 0.002 0.0005) 0 351.7 (0.02 0.02 0.0001) 0"],
        time="250",
    )
    _write_function(
        case,
        "solidTemperatureAvg",
        "volFieldValue.dat",
        "# Time  volAverage(T)",
        ["250 330.4"],
        time="250",
    )
    (case / "log.chtMultiRegionFoam").write_text("Time = 250\nEnd\n")

    run = parse_case(case, _cfg())
    assert run.metrics == {
        "pressure_drop_pa": 20.0,
        "max_temperature_k": 351.7,
        "mean_temperature_k": 330.4,
    }
    assert run.status == "completed"
    assert run.has_geometry is True


def test_parser_status_detection_for_pending_running_completed_and_failed(tmp_path):
    pending = _base_case(tmp_path / "run_0001")
    assert parse_case(pending, _cfg()).status == "pending"

    log = pending / "log.chtMultiRegionFoam"
    log.write_text("Time = 10\nDILUPBiCGStab: Solving for Ux, Initial residual = 0.1\n")
    assert parse_case(pending, _cfg()).status == "running"

    log.write_text("Time = 10\nEnd\n")
    assert parse_case(pending, _cfg()).status == "completed"

    log.write_text("Time = 10\n--> FOAM FATAL ERROR:\nMaximum iterations exceeded\n")
    failed = parse_case(pending, _cfg())
    assert failed.status == "failed"
    assert failed.error == "Maximum iterations exceeded"


def test_parser_reads_openfoam_banner_start_as_local_time_converted_to_utc(tmp_path):
    case = _base_case(tmp_path / "run_0002")
    (case / "log.chtMultiRegionFoam").write_text(
        "Build  : v2312\n"
        "Date   : Oct 24 2026\n"
        "Time   : 17:40:32\n"
        "Time = 500\n"
        "End\n"
    )

    run = parse_case(case, _cfg())
    expected = datetime.strptime(
        "Oct 24 2026 17:40:32", "%b %d %Y %H:%M:%S"
    ).astimezone(timezone.utc)
    assert datetime.fromisoformat(run.started_at) == expected


def test_parser_residuals_take_first_initial_residual_per_field_per_iteration():
    log = """Time = 10
DILUPBiCGStab:  Solving for Ux, Initial residual = 0.0123, Final residual = 0.000456, No Iterations 2
GAMG:  Solving for p_rgh, Initial residual = 0.5, Final residual = 0.01, No Iterations 5
DILUPBiCGStab:  Solving for Ux, Initial residual = 0.9, Final residual = 0.1, No Iterations 1
Time = 20
DILUPBiCGStab:  Solving for Ux, Initial residual = 0.0008, Final residual = 0.00001, No Iterations 2
"""
    residuals = parse_residuals(log)
    assert residuals["iterations"] == [10, 20]
    assert residuals["fields"]["Ux"] == [0.0123, 0.0008]
    assert residuals["fields"]["p_rgh"] == [0.5, None]
