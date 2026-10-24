import gradio as gr

import agent
import app
import checks
import llm
import schema
import state


def _initial_chat():
    return [{"role": "assistant", "content": agent.OPENING_LINE}]


def _last_result(generator):
    results = list(generator)
    assert len(results) == 2
    return results[-1]


def test_build_app_constructs_gradio_six_messages_ui():
    demo = app.build_app("mock")

    assert isinstance(demo, gr.Blocks)
    assert demo.title == "Cold Plate Requirements Intake — ITherm 2027"
    assert any(
        getattr(component, "value", None)
        == (
            "## Cold Plate Requirements Intake — ITherm 2027\n\n"
            "Collects and validates the simulation inputs and writes "
            "`requirements_final.json` for the optimizer stage."
        )
        for component in demo.blocks.values()
    )


def test_preset_checklist_has_group_progress_and_table_display(tmp_path):
    result = _last_result(app.on_preset(None, _initial_chat(), "mock", tmp_path))
    intake_agent, _, progress, checklist, downloads, footer, *_ = result
    done, total = intake_agent.session.progress()

    for group_number, group_name in schema.GROUPS.items():
        assert f"Group {group_number} — {group_name}" in checklist
    assert "🟡" in checklist
    assert "✅ C1:" in checklist
    assert "⚠️ C5:" in checklist
    assert "ℹ️ C6:" in checklist
    check_lines = [
        line
        for line in checklist.splitlines()
        if line.startswith(("✅ ", "ℹ️ ", "⚠️ ", "❌ "))
    ]
    assert [line.split(":", 1)[0].split()[-1] for line in check_lines] == [
        f"C{check_id}" for check_id in range(1, 9)
    ]
    assert "10 rows, 1492.8 W" in checklist
    assert "Group 1 — Limits and scoring (0/" in checklist
    assert "← current" in checklist
    assert f"**{done}/{total} required fields complete**" in progress
    assert downloads == [
        str(intake_agent.session.dir / name)
        for name in ("notes.txt", "requirements.json")
    ]
    assert footer == "LLM: mock"
    assert intake_agent.session.acknowledge_warning("C5", "I acknowledge C5.").ok
    c5_line = next(
        line for line in app.render_checklist(intake_agent.session).splitlines()
        if line.startswith("⚠️ C5:")
    )
    assert c5_line.endswith(" — acknowledged")


def test_checklist_renders_error_icon_and_missing_data_message(tmp_path, monkeypatch):
    session = state.Session(base_dir=tmp_path)
    results = [
        checks.CheckResult(id="C8", level="error", message="must be fixed"),
        checks.CheckResult(
            id="C5",
            level="warning",
            message="must be acknowledged",
            acknowledged=True,
        ),
    ]
    monkeypatch.setattr(session, "checks", lambda: results)

    checklist = app.render_checklist(session)
    assert "⚠️ C5: must be acknowledged — acknowledged" in checklist
    assert "❌ C8: must be fixed" in checklist
    assert checklist.index("⚠️ C5:") < checklist.index("❌ C8:")

    monkeypatch.setattr(session, "checks", lambda: [])
    assert "Checks: not enough data yet" in app.render_checklist(session)


def test_preset_then_send_confirms_group_and_updates_chat(tmp_path):
    preset_result = _last_result(app.on_preset(None, _initial_chat(), "mock", tmp_path))
    intake_agent, chat, *_ = preset_result

    results = list(app.on_send("yes", intake_agent, chat, "mock", tmp_path))
    waiting_chat = results[0][1]
    result = results[-1]
    updated_agent, updated_chat, _, checklist, *_ = result

    assert waiting_chat[-2] == {"role": "user", "content": "yes"}
    assert waiting_chat[-1] == {"role": "assistant", "content": "…thinking"}
    assert all(not update["interactive"] for update in results[0][6:])
    assert all(update["interactive"] for update in result[6:])
    assert updated_agent.session.fields["dp_hard_limit"].status == "user_provided"
    assert "✅ Pressure-drop hard limit:" in checklist
    assert {"role": "user", "content": "yes"} in updated_chat
    assert updated_chat[-1]["role"] == "assistant"
    assert updated_chat[-1]["content"].strip()
    assert "…thinking" not in updated_chat[-1]["content"]


def test_mock_handlers_finalize_and_expose_final_download(tmp_path):
    result = _last_result(app.on_preset(None, _initial_chat(), "mock", tmp_path))
    intake_agent, chat, *_ = result
    progress = ""

    for _ in range(30):
        if intake_agent.session.finalized:
            break
        digest = intake_agent.digest()
        if digest["awaiting_final_confirmation"]:
            message = "yes"
        elif not digest["presented_fields"] and any(
            check["id"] == "C5"
            and check["level"] == "warning"
            and not check["acknowledged"]
            for check in digest["failing_checks"]
        ):
            message = "yes, acknowledged"
        else:
            missing_enum = next(
                (
                    item
                    for item in digest["next_group_fields"]
                    if item["type"] == "enum" and item["status"] == "missing"
                ),
                None,
            )
            message = (
                missing_enum["choices"][0].replace("_", " ")
                if missing_enum
                else "yes"
            )
        result = _last_result(app.on_send(message, intake_agent, chat, "mock", tmp_path))
        intake_agent, chat, progress, _, downloads, *_ = result

    assert intake_agent.session.finalized is True
    assert str(intake_agent.session.dir / "requirements_final.json") in downloads
    assert "Finalized ✅" in progress


def test_send_starts_blank_session_when_agent_state_is_empty(tmp_path):
    result = _last_result(
        app.on_send(
            "I have a liquid-cooled package.",
            None,
            _initial_chat(),
            "mock",
            tmp_path,
        )
    )
    intake_agent, chat, *_ = result

    assert isinstance(intake_agent, agent.Agent)
    assert any("START blank" in entry for entry in intake_agent.session.log)
    assert {"role": "user", "content": "I have a liquid-cooled package."} in chat


def test_provider_error_is_shown_as_assistant_message(tmp_path):
    def raise_provider_error(system, history, digest):
        raise RuntimeError("provider down")

    intake_agent = agent.Agent(
        state.Session(base_dir=tmp_path),
        llm.ScriptedProvider([raise_provider_error]),
    )

    result = _last_result(
        app.on_send(
            "Start with my package.",
            intake_agent,
            _initial_chat(),
            "mock",
            tmp_path,
        )
    )
    chat = result[1]

    assert chat[-1]["role"] == "assistant"
    assert "temporarily unavailable (RuntimeError)" in chat[-1]["content"]
