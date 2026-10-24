from app.foam_parser import parse_residuals
from mock.generate_runs import write_case


PARAMS = {
    "fin_count": 20,
    "fin_height_mm": 20.0,
    "fin_thickness_mm": 1.0,
    "base_thickness_mm": 3.0,
    "inlet_velocity_m_s": 3.0,
}


def test_mock_completed_residuals_are_distinct_and_can_be_nonconverged(tmp_path):
    converged_dir = tmp_path / "run_0001"
    write_case(converged_dir, PARAMS, seed=4)
    converged = parse_residuals(
        (converged_dir / "log.chtMultiRegionFoam").read_text()
    )
    finals = [values[-1] for values in converged["fields"].values()]
    assert len(set(finals)) == len(finals)
    assert all(value < 1e-3 for value in finals)

    nonconverged_dir = tmp_path / "run_0002"
    write_case(nonconverged_dir, PARAMS, seed=4, nonconverged=True)
    nonconverged = parse_residuals(
        (nonconverged_dir / "log.chtMultiRegionFoam").read_text()
    )
    assert 1.5e-3 < nonconverged["fields"]["p_rgh"][-1] < 2.5e-3
    assert all(
        values[-1] < 1e-3
        for name, values in nonconverged["fields"].items()
        if name != "p_rgh"
    )


def test_failed_mock_residuals_rise_before_fatal_error(tmp_path):
    case = tmp_path / "run_0003"
    write_case(case, PARAMS, seed=9, failed=True, iterations=100)
    log = (case / "log.chtMultiRegionFoam").read_text()
    residuals = parse_residuals(log)

    assert "FOAM FATAL ERROR" in log
    assert residuals["fields"]["Ux"][-1] > residuals["fields"]["Ux"][-20] * 10
