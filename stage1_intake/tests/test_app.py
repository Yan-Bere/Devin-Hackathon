import gradio as gr
import pandas as pd

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
    assert demo.title == "Cold Plate Copilot"
    assert any(
        getattr(component, "value", None) == app.ui_style.header_html()
        for component in demo.blocks.values()
    )
    assert "From competition specs to an optimized" in app.ui_style.header_html()
    assert any(
        isinstance(component, gr.ScatterPlot)
        for component in demo.blocks.values()
    )
    assert any(
        isinstance(component, gr.Model3D)
        for component in demo.blocks.values()
    )
    assert any(
        getattr(component, "value", None) == "Optimize"
        and not component.interactive
        for component in demo.blocks.values()
    )


def test_preset_checklist_has_group_progress_and_table_display(tmp_path):
    result = _last_result(app.on_preset(None, _initial_chat(), "mock", tmp_path))
    intake_agent, _, progress, checklist, downloads, footer, *_ = result
    done, total = intake_agent.session.progress()

    for group_number, group_name in schema.GROUPS.items():
        assert f"Group {group_number} — {group_name}" in checklist
    assert "cp-status cp-proposed" in checklist
    assert 'data-check="C1"' in checklist
    assert "cp-check-ok" in checklist
    assert 'cp-check cp-check-warning" data-check="C5"' in checklist
    assert 'cp-check cp-check-info" data-check="C6"' in checklist
    import re
    assert re.findall(r'data-check="(C\d)"', checklist) == [
        f"C{check_id}" for check_id in range(1, 9)
    ]
    assert "10 rows, 1492.8 W" in checklist
    assert "Group 1 — Limits and scoring" in checklist
    assert "cp-group cp-current" in checklist
    assert f"{done} / {total} confirmed" in checklist
    assert "cp-step cp-active" in progress and "Specs" in progress
    assert downloads == [
        str(intake_agent.session.dir / name)
        for name in ("notes.txt", "requirements.json")
    ]
    assert footer == "LLM: mock"
    assert intake_agent.session.acknowledge_warning("C5", "I acknowledge C5.").ok
    rendered = app.render_checklist(intake_agent.session)
    c5_row = rendered[rendered.index('data-check="C5"'):]
    c5_row = c5_row[: c5_row.index("</div></div>")]
    assert "— acknowledged" in c5_row


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
    assert "must be acknowledged<span class=\"cp-ack\">— acknowledged</span>" in checklist
    assert 'cp-check-error" data-check="C8"' in checklist and "must be fixed" in checklist
    assert checklist.index('data-check="C5"') < checklist.index('data-check="C8"')

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
    assert all(not update["interactive"] for update in results[0][6:11])
    assert all(update["interactive"] for update in result[6:10])
    assert result[10]["interactive"] is False
    assert updated_agent.session.fields["dp_hard_limit"].status == "user_provided"
    assert "Pressure-drop hard limit" in checklist and "✓ confirmed" in checklist
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
    assert result[10]["interactive"] is True


def test_optimize_handler_yields_progress_and_results(tmp_path, monkeypatch):
    class FinalizedSession:
        finalized = True
        dir = tmp_path

    class AgentState:
        session = FinalizedSession()

    nominal = {
        "delta_p_kPa": 2.0,
        "delta_p_psi": 0.29,
        "pumping_power_W": 0.1,
    }
    baseline = {
        "fin_thickness_mm": 0.3,
        "gap_mm": 0.3,
        "fin_count": 86,
        "T_gpu_max_C": 70.0,
        "T_hbm_max_C": 50.0,
        "delta_p_nominal_kPa": 2.0,
        "fom": 0.0,
        "feasible": False,
        "constraints": [],
        "failing_constraints": [],
        "nominal": nominal,
    }
    optimized = {
        **baseline,
        "fin_thickness_mm": 0.2,
        "gap_mm": 0.2,
        "fom": 0.05,
        "T_gpu_max_C": 68.0,
        "T_hbm_max_C": 48.0,
        "failing_constraints": [
            {
                "name": "Coolant outlet rise",
                "actual": 21.5,
                "limit": 12.0,
                "unit": "K",
            }
        ],
    }
    sweep = [
        {
            "flow_L_min": 1.0,
            "inlet_temp_C": 30.0,
            "delta_p_kPa": 1.0,
            "delta_p_psi": 0.15,
            "max_gpu_C": 80.0,
            "max_hbm_C": 55.0,
            "coolant_outlet_rise_K": 21.5,
        }
    ]
    fake_result = {
        "baseline": baseline,
        "optimized": optimized,
        "feasible": False,
        "failing_constraints": optimized["failing_constraints"],
        "sweep": sweep,
        "evaluations": [
            {
                "T_hbm_max_C": 48.0,
                "delta_p_nominal_kPa": 2.0,
                "feasible": False,
            }
        ],
        "files": {
            "stl_path": str(tmp_path / "optimized.stl"),
            "step_path": str(tmp_path / "optimized.step"),
        },
        "run_elapsed_seconds": 2.5,
    }

    results = list(app.on_optimize(AgentState(), runner=lambda path: fake_result))

    assert len(results) == 2
    assert results[0][0] == "Optimizing… (reduced-order model)"
    assert "No feasible design found" in results[1][1]
    assert "Coolant outlet rise" in results[1][1]
    assert isinstance(results[1][2], pd.DataFrame)
    assert isinstance(results[1][3], pd.DataFrame)
    assert {"baseline", "optimum"} <= set(results[1][3]["kind"])
    assert results[1][4] == fake_result["files"]["stl_path"]
    assert results[1][5] == [
        fake_result["files"]["step_path"],
        fake_result["files"]["stl_path"],
    ]
    assert results[1][6]["interactive"] is True


def test_optimize_handler_catches_errors(tmp_path):
    class FinalizedSession:
        finalized = True
        dir = tmp_path

    class AgentState:
        session = FinalizedSession()

    results = list(
        app.on_optimize(
            AgentState(),
            runner=lambda path: (_ for _ in ()).throw(RuntimeError("optimizer broke")),
        )
    )

    assert "Optimization failed: RuntimeError: optimizer broke" in results[-1][0]


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
