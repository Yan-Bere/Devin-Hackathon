import os
from datetime import datetime, timezone

from app.config import AppConfig
from app.store import RunStore


def test_fingerprint_ignores_processor_tree_but_tracks_solver_log(tmp_path):
    case = tmp_path / "run_0001"
    case.mkdir()
    (case / "params.json").write_text("{}")
    (case / "system").mkdir()
    (case / "system" / "controlDict").write_text("application solver;\n")
    (case / "log.solver").write_text("initial\n")

    processor_dir = case / "processor0" / "100"
    processor_dir.mkdir(parents=True)
    for index in range(100):
        (processor_dir / f"field-{index}").write_text("large unrelated tree")
    velocity = processor_dir / "U"
    velocity.write_text("old solution field")

    store = RunStore(AppConfig(runs_dir=tmp_path))
    initial = store._fingerprint(case)
    velocity.write_text("updated solution field with more data")
    assert store._fingerprint(case) == initial

    with (case / "log.solver").open("a") as log:
        log.write("new solver output\n")
    assert store._fingerprint(case) != initial


def test_finished_case_runtime_uses_banner_start_and_log_mtime(tmp_path):
    case = tmp_path / "run_0002"
    case.mkdir()
    banner = (
        "Date   : Oct 24 2026\n"
        "Time   : 17:40:32\n"
        "Time = 500\n"
        "End\n"
    )
    log = case / "log.solver"
    log.write_text(banner)
    started = datetime.strptime(
        "Oct 24 2026 17:40:32", "%b %d %Y %H:%M:%S"
    ).astimezone(timezone.utc)
    finished_timestamp = started.timestamp() + 123.4
    os.utime(log, (finished_timestamp, finished_timestamp))

    store = RunStore(AppConfig(runs_dir=tmp_path))
    store.scan()
    run = store.get_run("run_0002")

    assert run.status == "completed"
    assert run.started_at == started.isoformat()
    assert run.finished_at == datetime.fromtimestamp(
        finished_timestamp, timezone.utc
    ).isoformat()
    assert abs(run.runtime_s - 123.4) < 0.01
