"""Stage-3 dashboard handoff: start_modelling + ready message + button state."""

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

import app as intake_app
import agent as intake_agent
import llm
import state as intake_state


@pytest.fixture
def session(tmp_path):
    return intake_state.Session(base_dir=tmp_path)


@pytest.fixture
def agent(session):
    return intake_agent.Agent(session, llm.get_provider("mock"))


def _finalize(agent, payload=None):
    agent.session.finalized = True
    doc = payload or {"finalized": True, "fields": {"flow_nominal": {"value": 2.0}}}
    (agent.session.dir / "requirements_final.json").write_text(json.dumps(doc))
    return doc


def test_start_modelling_not_finalized(agent):
    assert intake_app.start_modelling(agent) == "Finalize requirements first."


def test_start_modelling_posts_payload(agent):
    doc = _finalize(agent, {"finalized": True, "fields": {"x": {"value": 1}}})
    opener = MagicMock()
    msg = intake_app.start_modelling(agent, opener=opener)
    assert "Modelling started" in msg
    req = opener.call_args[0][0]
    assert req.full_url == f"{intake_app.DASHBOARD_URL}/api/modelling/start"
    assert json.loads(req.data) == {"requirements_final": doc}
    assert req.get_header("Content-type") == "application/json"
    assert opener.call_args.kwargs["timeout"] == 5


def test_start_modelling_unreachable(agent):
    _finalize(agent)
    def boom(req, timeout=None):
        raise ConnectionError("refused")
    msg = intake_app.start_modelling(agent, opener=boom)
    assert "Dashboard not reachable" in msg
    assert "run_demo_stack.py" in msg


def test_ready_message_appended_once(agent):
    agent.start_preset()
    chat = [{"role": "assistant", "content": "first"}]
    # simulate finalization then two handler yields
    agent.session.finalized = True
    c1 = intake_app._append_ready_message(agent, list(chat))
    assert c1[-1]["content"] == intake_app.READY_MSG
    c2 = intake_app._append_ready_message(agent, list(c1))
    assert sum(m["content"] == intake_app.READY_MSG for m in c2) == 1


def test_outputs_tuple_has_dashboard_update():
    out = intake_app._outputs(None, [], False, "mock")
    assert len(out) == 12  # outputs list + dashboard button
