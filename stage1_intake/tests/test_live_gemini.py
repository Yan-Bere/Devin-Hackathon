import json
import os
from pathlib import Path

import pytest

import agent
import llm
import state


pytestmark = pytest.mark.skipif(
    os.getenv("RUN_LIVE") != "1" or not os.getenv("GEMINI_API_KEY"),
    reason="set RUN_LIVE=1 and GEMINI_API_KEY to run the live Gemini test",
)


PRESET = Path(agent.__file__).resolve().parent / "presets" / "itherm2027.json"


def test_gemini_intake_conversation(tmp_path):
    session = state.Session(base_dir=tmp_path)
    intake_agent = agent.Agent(session, llm.GeminiProvider())

    def exchange(message):
        print(f"USER: {message}", flush=True)
        reply = intake_agent.handle(message)
        print(f"BOT: {reply}", flush=True)
        return reply

    try:
        reply = intake_agent.start_preset(PRESET)
        print(f"BOT: {reply}", flush=True)
        exchange("Yes those limits are right, but over 4 psi is a penalty, not disqualification.")
        exchange("Use 2 L/min nominal, 30 C inlet, sweep flow only at 30 C.")
        exchange("Actually make the TIM 0.08 cm2K/W.")

        for _ in range(20):
            if session.finalized:
                break
            message = "yes" if intake_agent.awaiting_final_confirmation else "Yes, use those."
            exchange(message)
    finally:
        notes_path = session.dir / "notes.txt"
        notes = notes_path.read_text(encoding="utf-8") if notes_path.exists() else ""
        notes_kind = "FINAL" if session.finalized else "PARTIAL"
        print(f"{notes_kind} NOTES.TXT:\n{notes}", flush=True)

    assert session.finalized, "Gemini did not finalize the intake within 20 turns"
    assert session.fields["tim_resistance"].value == pytest.approx(0.08)
    assert session.fields["tim_resistance"].status == "user_provided"
    assert session.fields["dp_over_limit_rule"].value == "penalty"
    assert session.fields["flow_nominal"].value == pytest.approx(2.0)
    assert session.fields["inlet_temp_nominal"].value == pytest.approx(30.0)
    assert session.fields["sweep_mode"].value == "flow_sweep_at_nominal_temp"

    assert "Yes those limits are right, but over 4 psi is a penalty, not disqualification." in notes
    assert "Use 2 L/min nominal, 30 C inlet, sweep flow only at 30 C." in notes
    assert "Actually make the TIM 0.08 cm2K/W." in notes
    final_document = json.loads(
        (session.dir / "requirements_final.json").read_text(encoding="utf-8")
    )
    assert final_document["finalized"] is True
