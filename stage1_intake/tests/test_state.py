import json
from pathlib import Path

import pytest

import schema
from state import Session


PRESET = Path(schema.__file__).parent / "presets" / "itherm2027.json"


def new_session(tmp_path):
    return Session(base_dir=tmp_path)


def test_set_field_converts_and_logs_original_units(tmp_path):
    session = new_session(tmp_path)
    result = session.set_field("dp_hard_limit", "4 psi", user_quote="four psi")
    assert result.ok
    assert session.fields["dp_hard_limit"].value == pytest.approx(27.579, abs=1e-3)
    assert session.fields["dp_hard_limit"].status == "user_provided"
    assert session.fields["dp_hard_limit"].source_quote == "four psi"
    notes = (session.dir / "notes.txt").read_text()
    assert "(from 4 psi)" in notes
    assert 'quote="four psi"' in notes

    assert session.set_field("flow_nominal", 0.528, "gpm").ok
    assert session.fields["flow_nominal"].value == pytest.approx(1.99869, abs=1e-4)
    assert session.set_field("inlet_temp_nominal", 86, "°F").ok
    assert session.fields["inlet_temp_nominal"].value == pytest.approx(30)
    assert session.set_field("max_coolant_rise", 9, "°F").ok
    assert session.fields["max_coolant_rise"].value == pytest.approx(5)


def test_invalid_values_do_not_change_field_state(tmp_path):
    session = new_session(tmp_path)
    before = session.fields["hbm_tmax_limit"]
    result = session.set_field("hbm_tmax_limit", 250, "°C")
    assert not result.ok
    assert session.fields["hbm_tmax_limit"] == before
    assert not session.set_field("dp_over_limit_rule", "maybe").ok
    assert not session.set_field("dp_hard_limit", 4, "°C").ok


def test_blank_and_preset_proposals(tmp_path):
    session = new_session(tmp_path)
    always_required = [
        item.id
        for item in schema.FIELDS
        if item.required is True
    ]
    assert session.missing_required() == always_required
    for field_id in ("dp_penalty_per_psi", "power_map_file", "power_map_pitch"):
        assert field_id not in session.missing_required()

    result = session.load_preset(PRESET)
    assert result.ok
    assert session.fields["dp_hard_limit"].status == "default_proposed"
    assert session.fields["dp_over_limit_rule"].status == "missing"
    assert session.fields["sweep_mode"].status == "missing"
    assert session.missing_required()


def test_conditional_required_fields(tmp_path):
    session = new_session(tmp_path)
    assert session.set_field("dp_over_limit_rule", "penalty").ok
    assert session.is_required("dp_penalty_per_psi")
    assert session.set_field("dp_over_limit_rule", "disqualify").ok
    assert not session.is_required("dp_penalty_per_psi")
    assert session.set_field("power_map_mode", "grid_file").ok
    assert session.is_required("power_map_file")
    assert session.is_required("power_map_pitch")


def test_schema_validates_lists_objects_and_optional_multiselects():
    assert schema.validate(schema.FIELD_BY_ID["base_plate_size"], "78, 78, 2", "mm") == [78, 78, 2]
    assert schema.validate(
        schema.FIELD_BY_ID["base_material"],
        {"name": "copper", "k": {"value": 391, "unit": "W/m·K"}},
        None,
    ) == {"name": "copper", "k": 391}
    assert schema.validate(schema.FIELD_BY_ID["required_outputs"], [], None) == []
    with pytest.raises(ValueError, match="between 0 °C and 200 °C"):
        schema.validate(schema.FIELD_BY_ID["hbm_tmax_limit"], "250 °C", None)


def test_confirmation_rules_are_explicit_and_atomic(tmp_path):
    session = new_session(tmp_path)
    session.load_preset(PRESET)
    assert session.confirm_defaults(["tim_resistance", "dp_hard_limit"], "confirmed").ok
    assert session.fields["tim_resistance"].status == "assumption_confirmed"
    assert session.fields["dp_hard_limit"].status == "user_provided"
    before = session.fields["dp_hard_limit"].status
    result = session.confirm_defaults(["dp_hard_limit", "dp_over_limit_rule"], "confirmed")
    assert not result.ok
    assert session.fields["dp_hard_limit"].status == before


def test_mark_not_applicable_and_fluid_side_effect(tmp_path):
    session = new_session(tmp_path)
    assert not session.mark_not_applicable("dp_hard_limit", "not used").ok
    assert session.mark_not_applicable("gpu_t_target", "not needed").ok
    assert session.fields["gpu_t_target"].status == "not_applicable"
    assert session.set_field("fluid", "PG25").ok
    assert session.fields["fluid_properties"].status == "missing"
    assert session.fields["fluid_properties"].value is None


def test_heat_source_side_effect_and_requirements_rewrite(tmp_path):
    session = new_session(tmp_path)
    assert session.set_field("heat_sources", schema.FIELD_BY_ID["heat_sources"].default).ok
    assert session.fields["total_power"].status == "default_proposed"
    assert session.fields["total_power"].value == pytest.approx(1492.8)
    document = json.loads((session.dir / "requirements.json").read_text())
    assert document["fields"]["heat_sources"]["status"] == "user_provided"
    assert document["fields"]["total_power"]["value"] == pytest.approx(1492.8)
    assert set(document) == {
        "session_id", "finalized", "schema_version", "created_at", "updated_at", "fields", "checks", "files"
    }


def test_finalize_incomplete_and_full_happy_path(tmp_path):
    session = new_session(tmp_path)
    assert not session.finalize().ok
    assert not (session.dir / "requirements_final.json").exists()

    session.load_preset(PRESET)
    assert session.set_field("dp_over_limit_rule", "penalty", user_quote="penalty").ok
    assert session.set_field("sweep_mode", "full_grid", user_quote="full grid").ok
    defaults = [
        field_id
        for field_id, state in session.fields.items()
        if state.status == "default_proposed"
    ]
    assert session.confirm_defaults(defaults, "I confirm the proposed values").ok
    assert session.is_complete()
    assert session.finalize("finalize").ok
    final_document = json.loads((session.dir / "requirements_final.json").read_text())
    assert final_document["finalized"] is True
    assert set(final_document["fields"]["dp_hard_limit"]) == {
        "value", "unit", "status", "source_quote", "updated_at", "required", "is_assumption", "group"
    }


def test_digest_returns_next_group_and_defaults(tmp_path):
    session = new_session(tmp_path)
    session.load_preset(PRESET)
    digest = session.digest()
    assert digest["next_group"] == 1
    assert digest["next_group_name"] == schema.GROUPS[1]
    assert any(item["id"] == "dp_hard_limit" and item["value"] == 27.6 for item in digest["next_group_fields"])
