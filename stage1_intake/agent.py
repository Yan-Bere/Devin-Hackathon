"""Terminal requirements-intake agent."""

import argparse
import json
from pathlib import Path
import re

import llm
import schema
import state as intake_state


BASE_DIR = Path(__file__).resolve().parent
PRESET_PATH = BASE_DIR / "presets" / "itherm2027.json"
SESSIONS_DIR = BASE_DIR / "sessions"
OPENING_LINE = (
    "Hi! I'll collect everything needed to simulate your cold plate. Start by describing your package, "
    "or load the ITherm 2027 preset and I'll walk you through confirming it."
)

SYSTEM_PROMPT = """You are the requirements-intake assistant for a liquid cold plate design study (ITherm 2027 package: 2 GPUs + 8 HBM stacks). Your only job is to collect and confirm the inputs listed in the STATE DIGEST. You do not design, simulate, or optimize anything.

Python owns the state. The STATE DIGEST at the end of this prompt is the single source of truth for what is missing, what is proposed, and which checks fail. Never decide on your own that something is complete or saved.

How to work:
1. Cover one schema group at a time, following next_group in the digest. Ask at most 3 related questions per turn.
2. When the group has proposed values (status default_proposed), list them compactly with their units (use value_display) and ask "Use these?". Label every field with is_assumption=true as "(ASSUMPTION)". If the user agrees, call confirm_defaults with exactly the proposed field ids you listed for that group. A "yes" confirms only the group you just presented, never fields from other groups.
3. For fields with status missing, ask for them directly. For choice fields, list the choices.
4. Extract every value the user states, even several in one message, and call set_field once per field. Pass the number and the unit exactly as the user typed them (for example value "4", unit "psi"). Never convert units yourself. user_quote must be the exact phrase from the user's latest message that the value came from.
5. If a tool returns ok=false, tell the user plainly what was wrong and ask again. Never say a value was saved unless the tool returned ok=true.
6. If the user is unsure, explain the field in one sentence using its help text, then offer the proposed value.
7. Never invent a value. Never confirm anything the user did not agree to in their latest message. If the user changes an earlier answer, call set_field for it, whatever group it is in.
8. For each failing check in the digest, explain it in plain language. Errors must be fixed. Warnings need the user's explicit acknowledgement; then call acknowledge_warning with their words.
9. If a required field has type file, call request_file so the upload widget appears.
10. When digest.complete is true, show digest.summary to the user exactly as given and ask "Is this correct?". Only if the user's next message clearly says yes, call finalize. If they want changes, make them with set_field and continue.
11. Keep replies short and plain. Talk about fields by their labels, not their ids. Messages starting with "[system]" come from the app, not the user: never quote them as user words."""


def _object_schema(properties, required):
    return {
        "type": "object",
        "properties": properties,
        "required": required,
    }


_FIELD_IDS = list(schema.FIELD_BY_ID)
_FIELD_ID_PROPERTY = {"type": "string", "enum": _FIELD_IDS}
TOOLS = [
    {
        "name": "set_field",
        "description": "Record one value the user stated. Pass the user's number and unit exactly as typed; Python converts units and validates.",
        "parameters": _object_schema(
            {
                "field_id": dict(_FIELD_ID_PROPERTY),
                "value": {
                    "type": "string",
                    "description": "JSON-encoded value, or plain text like '4 psi'. Examples: '27.6', '\"penalty\"', '[1, 1.5, 2]', '{\"name\": \"copper\", \"k\": 391}', heat_sources: JSON list of {name,type,x0,y0,w,h,power_W}",
                },
                "unit": {
                    "type": "string",
                    "description": "unit as the user typed it, e.g. 'psi', 'gpm', 'F', 'cm2K/W'; omit if none",
                },
                "status": {
                    "type": "string",
                    "enum": ["user_provided", "assumption_confirmed"],
                    "description": "assumption_confirmed only when the user accepts a proposed ASSUMPTION value as-is.",
                },
                "user_quote": {
                    "type": "string",
                    "description": "exact phrase from the user's latest message",
                },
            },
            ["field_id", "value", "user_quote"],
        ),
    },
    {
        "name": "confirm_defaults",
        "description": "The user accepted the proposed values you just listed for the current group.",
        "parameters": _object_schema(
            {
                "field_ids": {
                    "type": "array",
                    "items": dict(_FIELD_ID_PROPERTY),
                },
                "user_quote": {"type": "string"},
            },
            ["field_ids", "user_quote"],
        ),
    },
    {
        "name": "mark_not_applicable",
        "description": "The user said an OPTIONAL field does not apply.",
        "parameters": _object_schema(
            {
                "field_id": dict(_FIELD_ID_PROPERTY),
                "reason": {"type": "string"},
                "user_quote": {"type": "string"},
            },
            ["field_id", "reason", "user_quote"],
        ),
    },
    {
        "name": "acknowledge_warning",
        "description": "The user explicitly acknowledged a warning-level check.",
        "parameters": _object_schema(
            {
                "check_id": {"type": "string"},
                "user_quote": {"type": "string"},
            },
            ["check_id", "user_quote"],
        ),
    },
    {
        "name": "request_file",
        "description": "Show the file upload widget for a file field.",
        "parameters": _object_schema(
            {"field_id": dict(_FIELD_ID_PROPERTY)},
            ["field_id"],
        ),
    },
    {
        "name": "finalize",
        "description": "Call ONLY after you showed the final summary and the user clearly said it is correct.",
        "parameters": _object_schema(
            {"user_quote": {"type": "string"}},
            ["user_quote"],
        ),
    },
]


class Agent:
    def __init__(self, session: intake_state.Session, provider: llm.LLMProvider | None = None, max_tool_rounds: int = 8):
        self.session = session
        self.provider = provider or llm.get_provider()
        self.max_tool_rounds = max_tool_rounds
        self.history = []
        self.presented_group = None
        self.awaiting_final_confirmation = False
        self.requested_file = None
        self.latest_real_user_message = ""
        self.turn_mutated = False
        self._awaiting_confirmation_at_turn_start = False
        self._summary_shown_last_turn = False

    def _reset_conversation(self):
        self.history = []
        self.presented_group = None
        self.awaiting_final_confirmation = False
        self.requested_file = None
        self.latest_real_user_message = ""
        self.turn_mutated = False
        self._awaiting_confirmation_at_turn_start = False
        self._summary_shown_last_turn = False

    def start_preset(self, path=PRESET_PATH):
        self._reset_conversation()
        result = self.session.load_preset(path)
        if not result.ok:
            self.session.log_bot(result.message)
            return result.message
        synthetic = "[system] The user loaded the ITherm 2027 preset. Present the first open group."
        self.session.log_system(synthetic)
        return self._run_turn(synthetic, synthetic=True)

    def start_blank(self):
        self._reset_conversation()
        self.session.start_blank()
        synthetic = "[system] The user started a blank session. Ask about the first open group."
        self.session.log_system(synthetic)
        return self._run_turn(synthetic, synthetic=True)

    def handle(self, user_text: str):
        self.latest_real_user_message = user_text
        self.session.log_user(user_text)
        return self._run_turn(user_text, synthetic=False)

    def _value_display(self, item):
        field_state = self.session.fields[item.id]
        if field_state.status in {"missing", "not_applicable"}:
            return "MISSING"
        return self.session._display_value(item, field_state)

    def digest(self):
        result = self.session.digest()
        group_number = result["next_group"]
        base_fields = {item["id"]: item for item in result["next_group_fields"]}
        if group_number is not None:
            for item in schema.FIELDS:
                if item.group != group_number:
                    continue
                field_state = self.session.fields[item.id]
                required = self.session.is_required(item.id)
                if not required and field_state.status in {
                    "user_provided", "assumption_confirmed", "not_applicable"
                }:
                    continue
                entry = base_fields.get(item.id)
                if entry is None:
                    entry = {
                        "id": item.id,
                        "label": item.label,
                        "unit": item.unit,
                        "status": field_state.status,
                        "value": field_state.value if field_state.status == "default_proposed" else None,
                        "is_assumption": item.is_assumption,
                        "choices": item.choices,
                        "help": item.help,
                        "required": required,
                    }
                entry["type"] = item.type
                entry["value_display"] = self._value_display(item)
                entry["choices"] = list(item.choices) if item.choices is not None else None
                entry["required"] = required
                base_fields[item.id] = entry
            result["next_group_fields"] = [
                base_fields[item.id]
                for item in schema.FIELDS
                if item.group == group_number and item.id in base_fields
            ]
        else:
            result["next_group_fields"] = []

        if self.presented_group is None:
            presented_fields = []
        else:
            presented_fields = [
                {"id": item.id, "status": self.session.fields[item.id].status}
                for item in schema.FIELDS
                if item.group == self.presented_group
                and self.session.fields[item.id].status
                not in {"user_provided", "assumption_confirmed", "not_applicable"}
            ]
        result.update(
            {
                "presented_group": self.presented_group,
                "presented_fields": presented_fields,
                "awaiting_final_confirmation": self.awaiting_final_confirmation,
                "finalized": self.session.finalized,
                "summary": self.session.summary_text() if self.session.is_complete() else None,
            }
        )
        return result

    def _system_with_digest(self, digest):
        return (
            SYSTEM_PROMPT
            + "\n\nSTATE DIGEST (authoritative, computed by Python):\n"
            + json.dumps(digest, indent=1, ensure_ascii=False)
        )

    def _history_window(self, limit: int = 40) -> list[dict]:
        window = self.history[-limit:]
        while window and window[0].get("role") != "user":
            window = window[1:]
        if window:
            return window
        last_user = next(
            (
                index
                for index in range(len(self.history) - 1, -1, -1)
                if self.history[index].get("role") == "user"
            ),
            None,
        )
        return self.history[last_user:] if last_user is not None else []

    def _run_turn(self, user_text, synthetic):
        history_start = len(self.history)
        self.turn_mutated = False
        self._awaiting_confirmation_at_turn_start = (
            self.awaiting_final_confirmation
            and self._summary_shown_last_turn
            and not synthetic
        )
        self.history.append({"role": "user", "text": user_text})
        reply = ""
        completed = False
        provider_error = False
        for _ in range(self.max_tool_rounds):
            digest = self.digest()
            try:
                turn = self.provider.generate(
                    self._system_with_digest(digest),
                    self._history_window(),
                    TOOLS,
                    digest,
                )
            except Exception as exc:
                del self.history[history_start:]
                reply = (
                    "The language model is temporarily unavailable "
                    f"({type(exc).__name__}). Your inputs so far are saved — "
                    "please send your last message again."
                )
                completed = True
                provider_error = True
                break
            self.history.append(
                {
                    "role": "assistant",
                    "text": turn.text,
                    "tool_calls": turn.tool_calls,
                    "raw": turn.raw,
                    "model": getattr(self.provider, "model", None),
                }
            )
            if not turn.tool_calls:
                reply = turn.text
                completed = True
                break
            results = []
            for call in turn.tool_calls:
                result = self._execute_tool(call.name, call.args)
                results.append({"id": call.id, "name": call.name, "result": result})
            self.history.append({"role": "tool", "results": results})
        if not completed:
            reply = "Sorry, I got stuck — could you rephrase?"
        self.presented_group = self.session.next_group()
        is_complete = self.session.is_complete()
        summary = self.session.summary_text() if is_complete else None
        if is_complete and not self.session.finalized and summary not in reply:
            reply = f"{reply}\n\n{summary}\n\nIs this correct?"
        unacknowledged_checks = [
            result
            for result in self.session.checks()
            if result.level in {"warning", "error"} and not result.acknowledged
        ]
        if (
            not self.session.missing_required()
            and not self.session.finalized
            and unacknowledged_checks
        ):
            for result in unacknowledged_checks:
                if result.id not in reply:
                    reply += f"\n\n⚠️ {result.id} ({result.level}): {result.message}"
            acknowledgement_prompt = (
                "Warnings need your explicit acknowledgement (or change the inputs); "
                "errors must be fixed."
            )
            if acknowledgement_prompt not in reply:
                reply += f"\n\n{acknowledgement_prompt}"
        self._summary_shown_last_turn = (
            bool(summary)
            and summary in reply
            and re.search(r"\bIs this correct\?", reply, re.IGNORECASE) is not None
            and not self.session.finalized
            and not provider_error
        )
        self.awaiting_final_confirmation = (
            is_complete and not self.session.finalized and bool(reply.strip())
        )
        self.session.log_bot(reply)
        return reply

    @staticmethod
    def _normalized_quote(text):
        return re.sub(r"\s+", " ", str(text).casefold()).strip()

    def _guarded_quote(self, quote):
        quote = str(quote or "")
        if self._normalized_quote(quote) not in self._normalized_quote(self.latest_real_user_message):
            return self.latest_real_user_message
        return quote

    @staticmethod
    def _is_clear_confirmation(text):
        normalized = re.sub(r"\s+", " ", str(text).casefold()).strip()
        if re.search(r"\d", normalized):
            return False
        edit_markers = (
            "no",
            "not",
            "but",
            "except",
            "change",
            "actually",
            "instead",
            "however",
            "wait",
            "make",
            "set",
            "update",
            "should",
            "don't",
            "isn't",
            "wrong",
        )
        if any(
            re.search(rf"(?<!\w){re.escape(marker)}(?!\w)", normalized)
            for marker in edit_markers
        ):
            return False
        affirmatives = (
            "yes",
            "yep",
            "yeah",
            "yup",
            "y",
            "correct",
            "ok",
            "okay",
            "sure",
            "confirm",
            "confirmed",
            "looks good",
            "sounds good",
            "all good",
            "lgtm",
            "that's correct",
            "that is correct",
            "go ahead",
            "finalize",
        )
        pattern = r"^(?:" + "|".join(re.escape(value) for value in affirmatives) + r")\b"
        return re.match(pattern, normalized) is not None

    @staticmethod
    def _op_result(result):
        return {"ok": result.ok, "message": result.message, **result.data}

    def _execute_tool(self, name, args):
        try:
            if name == "set_field":
                raw_value = args.get("value")
                if not isinstance(raw_value, str):
                    return {"ok": False, "message": "value must be a string"}
                try:
                    value = json.loads(raw_value)
                except (json.JSONDecodeError, TypeError):
                    value = raw_value
                result = self.session.set_field(
                    args.get("field_id"),
                    value,
                    unit=args.get("unit"),
                    status=args.get("status", "user_provided"),
                    user_quote=self._guarded_quote(args.get("user_quote", "")),
                )
                if result.ok:
                    self.turn_mutated = True
                    self.awaiting_final_confirmation = False
                return self._op_result(result)
            if name == "confirm_defaults":
                field_ids = args.get("field_ids", [])
                invalid = [
                    field_id
                    for field_id in field_ids
                    if not isinstance(field_id, str)
                    or field_id not in schema.FIELD_BY_ID
                    or schema.FIELD_BY_ID[field_id].group != self.presented_group
                ]
                if invalid:
                    target_id = next(
                        (field_id for field_id in invalid if field_id in schema.FIELD_BY_ID),
                        None,
                    )
                    target_group = (
                        schema.FIELD_BY_ID[target_id].group if target_id is not None else "?"
                    )
                    current_name = schema.GROUPS.get(self.presented_group, "unknown")
                    return {
                        "ok": False,
                        "message": (
                            "You can only confirm fields of the group you just presented "
                            f"(group {self.presented_group}: {current_name}). "
                            f"Present group {target_group} first."
                        ),
                    }
                result = self.session.confirm_defaults(
                    field_ids,
                    user_quote=self._guarded_quote(args.get("user_quote", "")),
                )
                if result.ok and field_ids:
                    self.turn_mutated = True
                    self.awaiting_final_confirmation = False
                return self._op_result(result)
            if name == "mark_not_applicable":
                result = self.session.mark_not_applicable(
                    args.get("field_id"),
                    args.get("reason", ""),
                    user_quote=self._guarded_quote(args.get("user_quote", "")),
                )
                if result.ok:
                    self.turn_mutated = True
                    self.awaiting_final_confirmation = False
                return self._op_result(result)
            if name == "acknowledge_warning":
                result = self.session.acknowledge_warning(
                    args.get("check_id", ""),
                    user_quote=self._guarded_quote(args.get("user_quote", "")),
                )
                if result.ok:
                    self.turn_mutated = True
                    self.awaiting_final_confirmation = False
                return self._op_result(result)
            if name == "request_file":
                field_id = args.get("field_id")
                if field_id not in schema.FIELD_BY_ID or schema.FIELD_BY_ID[field_id].type != "file":
                    return {"ok": False, "message": f"{field_id!r} is not a file field"}
                self.requested_file = field_id
                return {"ok": True, "message": f"Upload requested for {field_id}", "field_id": field_id}
            if name == "finalize":
                missing = self.session.missing_required()
                blocking = self.session.blocking_issues()
                if missing:
                    return {
                        "ok": False,
                        "message": "Cannot finalize; missing required fields: " + ", ".join(missing),
                    }
                if blocking:
                    return {
                        "ok": False,
                        "message": "Cannot finalize; blocking issues: " + "; ".join(blocking),
                    }
                if not self._awaiting_confirmation_at_turn_start:
                    return {
                        "ok": False,
                        "message": "show the summary and ask 'Is this correct?' first.",
                    }
                if not self._is_clear_confirmation(self.latest_real_user_message):
                    return {
                        "ok": False,
                        "message": "Finalize only after the user clearly confirms the summary.",
                    }
                if self.turn_mutated:
                    return {
                        "ok": False,
                        "message": "Show the updated summary and ask 'Is this correct?' in a later turn before finalizing.",
                    }
                if not self.session.is_complete():
                    return {"ok": False, "message": "Cannot finalize until all required fields and checks are complete."}
                result = self.session.finalize(
                    user_quote=self._guarded_quote(args.get("user_quote", ""))
                )
                if result.ok:
                    self.turn_mutated = True
                    self.awaiting_final_confirmation = False
                return self._op_result(result)
            return {"ok": False, "message": f"Unknown tool {name!r}"}
        except Exception as exc:
            return {"ok": False, "message": str(exc)}


def _print_final_paths(session):
    print(f"notes.txt: {session.dir / 'notes.txt'}")
    print(f"requirements.json: {session.dir / 'requirements.json'}")
    print(f"requirements_final.json: {session.dir / 'requirements_final.json'}")


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--provider", choices=("mock", "gemini"))
    parser.add_argument("--preset", action="store_true")
    args = parser.parse_args(argv)
    print(OPENING_LINE)
    session = intake_state.Session(base_dir=SESSIONS_DIR)
    provider = llm.get_provider(args.provider)
    agent = Agent(session, provider)
    if args.preset:
        print(agent.start_preset())
        if session.finalized:
            _print_final_paths(session)
            return
    while True:
        try:
            line = input("> ")
        except EOFError:
            break
        command = line.strip()
        if command == "/quit":
            break
        if command == "/preset":
            reply = agent.start_preset()
        elif command == "/blank":
            reply = agent.start_blank()
        elif command == "/state":
            done, total = session.progress()
            missing = session.missing_required()
            print(f"Progress: {done} / {total} required fields")
            print("Missing required fields: " + (", ".join(missing) if missing else "none"))
            continue
        else:
            reply = agent.handle(line)
        print(reply)
        if session.finalized:
            _print_final_paths(session)
            break


if __name__ == "__main__":
    main()
