import json
import re
from pathlib import Path

import pytest

import agent
import llm
import state


PRESET = Path(agent.__file__).resolve().parent / "presets" / "itherm2027.json"


def _tool(name, args):
    return llm.ToolCall(id=f"{name}-call", name=name, args=args)


def _confirm_current_group(system, history, digest):
    message = history[-1]["text"]
    field_ids = [
        item["id"]
        for item in digest["presented_fields"]
        if item["status"] == "default_proposed"
    ]
    return llm.LLMTurn(
        text="",
        tool_calls=[
            _tool("confirm_defaults", {"field_ids": field_ids, "user_quote": message})
        ],
    )


def _next_opening(system, history, digest):
    return llm.LLMTurn(text=llm.render_group(digest), tool_calls=[])


def _complete_session(tmp_path):
    session = state.Session(base_dir=tmp_path)
    assert session.load_preset(PRESET).ok
    assert session.set_field("dp_over_limit_rule", "penalty").ok
    assert session.set_field("sweep_mode", "full_grid").ok
    proposed = [
        field_id
        for field_id, field_state in session.fields.items()
        if field_state.status == "default_proposed"
    ]
    assert session.confirm_defaults(proposed, user_quote="Yes, use these.").ok
    assert session.is_complete()
    return session


def test_scripted_happy_path_records_inputs_confirms_groups_and_finalizes(tmp_path):
    def record_first_group(system, history, digest):
        message = history[-1]["text"]
        fields = [
            item["id"]
            for item in digest["presented_fields"]
            if item["status"] == "default_proposed"
        ]
        return llm.LLMTurn(
            text="",
            tool_calls=[
                _tool(
                    "confirm_defaults",
                    {"field_ids": fields, "user_quote": message},
                ),
                _tool(
                    "set_field",
                    {
                        "field_id": "dp_over_limit_rule",
                        "value": '"penalty"',
                        "user_quote": "over 4 psi is a penalty",
                    },
                ),
            ],
        )

    def record_operating_points(system, history, digest):
        return llm.LLMTurn(
            text="",
            tool_calls=[
                _tool(
                    "set_field",
                    {
                        "field_id": "flow_nominal",
                        "value": "2",
                        "unit": "L/min",
                        "status": "assumption_confirmed",
                        "user_quote": "2 L/min",
                    },
                ),
                _tool(
                    "set_field",
                    {
                        "field_id": "inlet_temp_nominal",
                        "value": "30",
                        "unit": "C",
                        "status": "assumption_confirmed",
                        "user_quote": "30 C",
                    },
                ),
                _tool(
                    "set_field",
                    {
                        "field_id": "sweep_mode",
                        "value": '"flow_sweep_at_nominal_temp"',
                        "user_quote": "sweep flow only at 30 C",
                    },
                ),
            ],
        )

    def change_tim(system, history, digest):
        return llm.LLMTurn(
            text="",
            tool_calls=[
                _tool(
                    "set_field",
                    {
                        "field_id": "tim_resistance",
                        "value": "0.08",
                        "unit": "cm2K/W",
                        "user_quote": "0.08 cm2K/W",
                    },
                )
            ],
        )

    def show_summary(system, history, digest):
        assert digest["complete"]
        return llm.LLMTurn(
            text=f'{digest["summary"]}\n\nIs this correct?',
            tool_calls=[],
        )

    def finalize(system, history, digest):
        return llm.LLMTurn(
            text="",
            tool_calls=[
                _tool("finalize", {"user_quote": history[-1]["text"]})
            ],
        )

    turns = [
        llm.LLMTurn(text="Group 1: Limits and scoring", tool_calls=[]),
        record_first_group,
        _next_opening,
        record_operating_points,
        _next_opening,
        change_tim,
        _next_opening,
    ]
    for _ in range(4):
        turns.extend([_confirm_current_group, _next_opening])
    turns.extend([_confirm_current_group, show_summary, finalize, _next_opening])
    provider = llm.ScriptedProvider(turns)
    session = state.Session(base_dir=tmp_path)
    intake_agent = agent.Agent(session, provider)

    intake_agent.start_preset()
    intake_agent.handle(
        "Yes those limits are right, but over 4 psi is a penalty, not disqualification."
    )
    intake_agent.handle(
        "Use 2 L/min nominal, 30 C inlet, sweep flow only at 30 C."
    )
    intake_agent.handle("Actually make the TIM 0.08 cm2K/W.")
    for _ in range(5):
        summary_reply = intake_agent.handle("Yes, use those.")

    assert intake_agent.digest()["complete"] is True
    assert intake_agent.awaiting_final_confirmation is True
    assert "Is this correct?" in summary_reply
    assert session.fields["dp_over_limit_rule"].value == "penalty"
    assert session.fields["dp_over_limit_rule"].source_quote == "over 4 psi is a penalty"
    assert session.fields["dp_over_limit_rule"].status == "user_provided"
    assert session.fields["dp_hard_limit"].status == "user_provided"
    assert session.fields["dp_hard_limit"].source_quote == (
        "Yes those limits are right, but over 4 psi is a penalty, not disqualification."
    )
    assert session.fields["dp_penalty_per_psi"].status == "user_provided"
    assert session.fields["flow_nominal"].value == 2
    assert session.fields["inlet_temp_nominal"].value == 30
    assert session.fields["sweep_mode"].value == "flow_sweep_at_nominal_temp"
    assert session.fields["tim_resistance"].value == 0.08
    assert session.fields["tim_resistance"].source_quote == "0.08 cm2K/W"

    intake_agent.handle("yes")

    assert session.finalized is True
    assert (session.dir / "requirements_final.json").exists()
    final_document = json.loads((session.dir / "requirements_final.json").read_text())
    assert final_document["fields"]["tim_resistance"]["status"] == "user_provided"
    assert final_document["fields"]["tim_resistance"]["source_quote"] == "0.08 cm2K/W"
    notes = (session.dir / "notes.txt").read_text()
    assert "Yes those limits are right, but over 4 psi is a penalty, not disqualification." in notes
    assert "Use 2 L/min nominal, 30 C inlet, sweep flow only at 30 C." in notes
    assert "Actually make the TIM 0.08 cm2K/W." in notes
    assert re.search(r"\[\d{2}:\d{2}:\d{2}\]", notes)


def test_confirm_defaults_rejects_fields_outside_presented_group(tmp_path):
    provider = llm.ScriptedProvider(
        [
            llm.LLMTurn(text="Group 1", tool_calls=[]),
            llm.LLMTurn(
                text="",
                tool_calls=[
                    _tool(
                        "confirm_defaults",
                        {
                            "field_ids": ["tim_resistance"],
                            "user_quote": "Yes, confirm the TIM.",
                        },
                    )
                ],
            ),
            llm.LLMTurn(text="Please confirm only this group.", tool_calls=[]),
        ]
    )
    session = state.Session(base_dir=tmp_path)
    intake_agent = agent.Agent(session, provider)
    intake_agent.start_preset()

    intake_agent.handle("Yes, confirm the TIM.")

    tool_result = intake_agent.history[-2]["results"][0]["result"]
    assert tool_result["ok"] is False
    assert "group 1: Limits and scoring" in tool_result["message"]
    assert "Present group 3 first." in tool_result["message"]
    assert session.fields["tim_resistance"].status == "default_proposed"


def test_finalize_requires_a_separate_summary_confirmation_and_no_mutation(tmp_path):
    incomplete_provider = llm.ScriptedProvider(
        [
            llm.LLMTurn(text="Group 1", tool_calls=[]),
            llm.LLMTurn(
                text="",
                tool_calls=[_tool("finalize", {"user_quote": "finish"})],
            ),
            llm.LLMTurn(text="I still need more information.", tool_calls=[]),
        ]
    )
    incomplete = state.Session(base_dir=tmp_path / "incomplete")
    incomplete_agent = agent.Agent(incomplete, incomplete_provider)
    incomplete_agent.start_preset()
    incomplete_agent.handle("finish")
    incomplete_result = incomplete_agent.history[-2]["results"][0]["result"]
    assert incomplete_result["ok"] is False
    assert "missing required fields" in incomplete_result["message"].lower()
    assert incomplete.finalized is False

    not_shown = _complete_session(tmp_path / "not_shown")
    not_shown_provider = llm.ScriptedProvider(
        [
            llm.LLMTurn(
                text="",
                tool_calls=[_tool("finalize", {"user_quote": "yes"})],
            ),
            llm.LLMTurn(text="Please review the summary first.", tool_calls=[]),
        ]
    )
    not_shown_agent = agent.Agent(not_shown, not_shown_provider)
    not_shown_agent.handle("yes")
    not_shown_result = not_shown_agent.history[-2]["results"][0]["result"]
    assert not_shown_result["ok"] is False
    assert "show the summary" in not_shown_result["message"].lower()
    assert not_shown.finalized is False

    complete = _complete_session(tmp_path / "complete")
    mutation_provider = llm.ScriptedProvider(
        [
            llm.LLMTurn(
                text=f"{complete.summary_text()}\n\nIs this correct?",
                tool_calls=[],
            ),
            llm.LLMTurn(
                text="",
                tool_calls=[
                    _tool(
                        "set_field",
                        {
                            "field_id": "dp_hard_limit",
                            "value": "28",
                            "unit": "kPa",
                            "user_quote": "yes",
                        },
                    ),
                    _tool("finalize", {"user_quote": "finalize"}),
                ],
            ),
            llm.LLMTurn(text="Please confirm the updated summary in a later turn.", tool_calls=[]),
        ]
    )
    complete_agent = agent.Agent(complete, mutation_provider)
    complete_agent.handle("Please show the final summary.")
    complete_agent.handle("yes")
    mutation_results = complete_agent.history[-2]["results"]
    assert mutation_results[0]["result"]["ok"] is True
    assert mutation_results[1]["result"]["ok"] is False
    assert "later turn" in mutation_results[1]["result"]["message"]
    assert complete.is_complete()
    assert complete.finalized is False


def test_quote_guard_replaces_unmatched_quote_with_latest_user_message(tmp_path):
    provider = llm.ScriptedProvider(
        [
            llm.LLMTurn(text="Group 1", tool_calls=[]),
            llm.LLMTurn(
                text="",
                tool_calls=[
                    _tool(
                        "set_field",
                        {
                            "field_id": "dp_hard_limit",
                            "value": "4 psi",
                            "user_quote": "unrelated invented words",
                        },
                    )
                ],
            ),
            llm.LLMTurn(text="Recorded.", tool_calls=[]),
        ]
    )
    session = state.Session(base_dir=tmp_path)
    intake_agent = agent.Agent(session, provider)
    intake_agent.start_preset()
    message = "The pressure limit is four psi, not the old value."
    intake_agent.handle(message)

    assert session.fields["dp_hard_limit"].source_quote == message


def test_system_digest_is_rebuilt_after_tool_round_and_system_logs_are_not_user(tmp_path):
    provider = llm.ScriptedProvider(
        [
            llm.LLMTurn(text="Group 1", tool_calls=[]),
            llm.LLMTurn(
                text="",
                tool_calls=[
                    _tool(
                        "set_field",
                        {
                            "field_id": "dp_hard_limit",
                            "value": "4 psi",
                            "user_quote": "4 psi",
                        },
                    )
                ],
            ),
            llm.LLMTurn(text="Recorded.", tool_calls=[]),
        ]
    )
    session = state.Session(base_dir=tmp_path)
    intake_agent = agent.Agent(session, provider)
    intake_agent.start_preset()
    intake_agent.handle("Set the pressure limit to 4 psi.")

    assert len(provider.calls) == 3
    first_digest = provider.calls[1][2]
    system, _, digest = provider.calls[2]
    assert "STATE DIGEST (authoritative, computed by Python):" in system
    assert any(item["id"] == "dp_hard_limit" for item in first_digest["presented_fields"])
    assert not any(item["id"] == "dp_hard_limit" for item in digest["presented_fields"])
    encoded_digest = system.split(
        "STATE DIGEST (authoritative, computed by Python):\n", 1
    )[1]
    assert json.loads(encoded_digest) == digest

    notes = (session.dir / "notes.txt").read_text()
    assert "SYSTEM: \"[system] The user loaded the ITherm 2027 preset." in notes
    assert 'USER: "[system]' not in notes


def test_mock_provider_end_to_end_completes_preset_intake(tmp_path):
    session = state.Session(base_dir=tmp_path)
    intake_agent = agent.Agent(session, llm.MockProvider())
    intake_agent.start_preset()

    for _ in range(30):
        if session.finalized:
            break
        digest = intake_agent.digest()
        if digest["awaiting_final_confirmation"]:
            message = "yes"
        else:
            missing_enum = next(
                (
                    item
                    for item in digest["next_group_fields"]
                    if item["type"] == "enum" and item["status"] == "missing"
                ),
                None,
            )
            if missing_enum:
                message = missing_enum["choices"][0].replace("_", " ")
            else:
                message = "yes"
        intake_agent.handle(message)

    assert session.finalized is True
    assert intake_agent.digest()["complete"] is True
    assert (session.dir / "requirements_final.json").exists()


def test_digest_includes_optional_open_fields_and_summary_text(tmp_path):
    session = state.Session(base_dir=tmp_path)
    intake_agent = agent.Agent(session, llm.MockProvider())
    intake_agent.start_preset()

    digest = intake_agent.digest()
    assert digest["presented_group"] == 1
    assert any(
        item["id"] == "dp_penalty_per_psi" and item["required"] is False
        for item in digest["next_group_fields"]
    )

    summary = session.summary_text()
    assert "Group 1 — Limits and scoring" in summary
    assert "Pressure-drop hard limit:" in summary
    assert "Heat sources: 10 rows, 1492.8 W" in summary
    assert "Checks: none failing" in summary


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("Yes, that's all correct", True),
        ("yes looks good", True),
        ("Confirmed.", True),
        ("ok go ahead", True),
        ("yes but change the TIM", False),
        ("no", False),
        ("yes, make flow 3 L/min", False),
        ("not quite", False),
        ("actually wait", False),
    ],
)
def test_clear_confirmation_requires_unqualified_affirmative(message, expected):
    assert agent.Agent._is_clear_confirmation(message) is expected


def test_provider_error_rolls_back_history_and_keeps_session_mutations(tmp_path):
    def fail_after_tool(system, history, digest):
        raise RuntimeError("provider unavailable")

    provider = llm.ScriptedProvider(
        [
            llm.LLMTurn(text="Group 1", tool_calls=[]),
            llm.LLMTurn(
                text="",
                tool_calls=[
                    _tool(
                        "set_field",
                        {
                            "field_id": "dp_hard_limit",
                            "value": "4",
                            "unit": "psi",
                            "user_quote": "4 psi",
                        },
                    )
                ],
            ),
            fail_after_tool,
        ]
    )
    session = state.Session(base_dir=tmp_path)
    intake_agent = agent.Agent(session, provider)
    intake_agent.start_preset()
    original_limit = session.fields["dp_hard_limit"].value
    history_length = len(intake_agent.history)

    reply = intake_agent.handle("Set the pressure limit to 4 psi.")

    assert reply == (
        "The language model is temporarily unavailable (RuntimeError). "
        "Your inputs so far are saved — please send your last message again."
    )
    assert len(intake_agent.history) == history_length
    assert session.fields["dp_hard_limit"].value != original_limit
    assert session.fields["dp_hard_limit"].status == "user_provided"
    assert intake_agent._summary_shown_last_turn is False
    assert "Set the pressure limit to 4 psi." in (session.dir / "notes.txt").read_text()


def test_complete_session_gets_deterministic_summary_and_can_be_finalized(tmp_path):
    session = _complete_session(tmp_path)
    provider = llm.ScriptedProvider(
        [
            llm.LLMTurn(text="Everything is complete.", tool_calls=[]),
            llm.LLMTurn(
                text="",
                tool_calls=[_tool("finalize", {"user_quote": "yes"})],
            ),
        ]
    )
    intake_agent = agent.Agent(session, provider)

    reply = intake_agent.handle("Please show me the final details.")

    assert session.summary_text() in reply
    assert "Is this correct?" in reply
    assert intake_agent._summary_shown_last_turn is True

    intake_agent.handle("yes")

    assert session.finalized is True
