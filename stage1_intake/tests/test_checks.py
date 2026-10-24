from copy import deepcopy

import checks
import schema


def _values():
    return {field.id: deepcopy(field.default) for field in schema.FIELDS}


def _result(values, check_id):
    return next(result for result in checks.run_checks(values) if result.id == check_id)


def test_preset_defaults_have_expected_check_levels_and_messages():
    values = _values()
    results = {result.id: result for result in checks.run_checks(values)}

    for check_id in ("C1", "C2", "C3", "C4", "C8"):
        assert results[check_id].level == "ok"
    assert results["C5"].level == "warning"
    assert "1 L/min → 21.5 K" in results["C5"].message
    assert "1.5 L/min → 14.3 K" in results["C5"].message
    assert "2 L/min" not in results["C5"].message
    assert results["C6"].level == "info"
    assert results["C7"].level == "warning"
    assert "8.5 K of headroom" in results["C7"].message
    assert "likely infeasible" in results["C7"].message


def test_pressure_rule_resolves_c6():
    values = _values()
    values["dp_over_limit_rule"] = "penalty"

    assert _result(values, "C6").level == "ok"


def test_heat_source_total_mismatch_is_c1_error():
    values = _values()
    values["heat_sources"][0]["power_W"] = 500

    result = _result(values, "C1")
    assert result.level == "error"
    assert "1438.4" in result.message


def test_heat_source_boundary_and_overlap_are_c2_errors():
    values = _values()
    values["heat_sources"][2]["x0"] = 45

    result = _result(values, "C2")
    assert result.level == "error"
    assert "H1 extends outside" in result.message
    assert "H1 overlaps H4" in result.message


def test_fin_design_space_must_fit_base_plate():
    values = _values()
    values["fin_design_space"] = [80, 52.15, 2]

    assert _result(values, "C3").level == "error"


def test_feature_limits_and_xy_resolution_are_c4_errors():
    values = _values()
    values["min_feature"] = 0.6
    result = _result(values, "C4")
    assert result.level == "error"
    assert "smaller than" in result.message

    values = _values()
    values["min_feature"] = 0.02
    result = _result(values, "C4")
    assert result.level == "error"
    assert "finer than" in result.message

    values = _values()
    values["min_feature"] = 0.03333
    assert _result(values, "C4").level == "ok"


def test_c7_inlet_sweep_uses_worst_inlet_unless_flow_sweep_mode():
    values = _values()
    values["inlet_temp_sweep"] = [45]
    result = _result(values, "C7")
    assert result.level == "warning"
    assert "66.5" in result.message

    values["sweep_mode"] = "flow_sweep_at_nominal_temp"
    result = _result(values, "C7")
    assert result.level == "warning"
    assert "13.5 K of headroom" in result.message

    values["flow_sweep"] = [2.0, 3.0]
    result = _result(values, "C7")
    assert result.level == "ok"
    assert "24.3 K of headroom" in result.message


def test_c5_respects_maximum_coolant_rise():
    values = _values()
    values["max_coolant_rise"] = 25

    assert _result(values, "C5").level == "ok"


def test_c8_reports_small_hbm_area_and_gpu_heat_flux():
    values = _values()
    values["heat_sources"][3]["w"] = 1200
    result = _result(values, "C8")
    assert result.level == "warning"
    assert "H2" in result.message

    values = _values()
    values["heat_sources"][0]["w"] = 1
    values["heat_sources"][0]["h"] = 1
    assert _result(values, "C8").level == "warning"


def test_missing_heat_sources_skips_geometry_power_and_flux_checks():
    values = _values()
    values["heat_sources"] = None
    results = {result.id: result for result in checks.run_checks(values)}
    assert not {"C1", "C2", "C8"} & results.keys()

    results = checks.run_checks({})
    assert [(result.id, result.level) for result in results] == [("C6", "info")]
