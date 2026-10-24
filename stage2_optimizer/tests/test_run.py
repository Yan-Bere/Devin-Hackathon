from pathlib import Path

from stage2_optimizer.run import run


def test_run_returns_optimizer_results_and_writes_geometry(finalized_requirements):
    result = run(finalized_requirements)

    assert set(result) >= {
        "baseline",
        "optimized",
        "sweep",
        "evaluations",
        "feasible",
        "failing_constraints",
        "files",
        "run_elapsed_seconds",
    }
    stl_path = result["files"]["stl_path"]
    assert stl_path is not None
    assert stl_path.startswith(str(finalized_requirements.parent))
    assert Path(stl_path).is_file()
    assert result["files"]["backend"] == "cadquery"
    assert Path(result["files"]["step_path"]).is_file()
