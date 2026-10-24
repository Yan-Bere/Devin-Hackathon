import json
from pathlib import Path
import sys

import pytest

STAGE1_DIR = Path(__file__).resolve().parents[2] / "stage1_intake"
sys.path.insert(0, str(STAGE1_DIR))

import state


PRESET = (
    Path(__file__).resolve().parents[2]
    / "stage1_intake"
    / "presets"
    / "itherm2027.json"
)


@pytest.fixture
def finalized_requirements(tmp_path):
    session = state.Session(base_dir=tmp_path)
    assert session.load_preset(PRESET).ok
    assert session.set_field("dp_over_limit_rule", "penalty").ok
    assert session.set_field(
        "sweep_mode", "flow_sweep_at_nominal_temp"
    ).ok
    proposed = [
        field_id
        for field_id, field_state in session.fields.items()
        if field_state.status == "default_proposed"
    ]
    assert session.confirm_defaults(proposed, "Confirmed defaults.").ok
    for check in session.checks():
        if check.level == "warning" and not check.acknowledged:
            assert session.acknowledge_warning(
                check.id, f"I acknowledge {check.id}."
            ).ok
    assert session.finalize("Test fixture finalized.").ok
    requirements_path = session.dir / "requirements_final.json"
    document = json.loads(requirements_path.read_text(encoding="utf-8"))
    assert document["finalized"] is True
    return requirements_path
