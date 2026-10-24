"""Session state, explicit confirmation, and persisted intake artifacts."""

from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime
import json
from pathlib import Path
import secrets

import checks as intake_checks
import schema
import units


STATUSES = ("missing", "default_proposed", "assumption_confirmed", "user_provided", "not_applicable")
DONE = {"user_provided", "assumption_confirmed"}


@dataclass
class FieldState:
    value: object = None
    unit: str | None = None
    status: str = "missing"
    source_quote: str | None = None
    updated_at: str | None = None


@dataclass
class OpResult:
    ok: bool
    message: str
    data: dict = field(default_factory=dict)


class Session:
    def __init__(self, base_dir="sessions", session_id=None, clock=datetime.now):
        self.clock = clock
        created = self.clock()
        self.session_id = session_id or f"{created:%Y-%m-%d_%H%M}_{secrets.token_hex(2)}"
        self.dir = Path(base_dir) / self.session_id
        self.dir.mkdir(parents=True, exist_ok=True)
        (self.dir / "uploads").mkdir(exist_ok=True)
        self.created_at = created.isoformat()
        self.updated_at = created.isoformat()
        self.fields = {item.id: FieldState() for item in schema.FIELDS}
        self.acknowledged = {}
        self.files = {}
        self.finalized = False
        self.log = []
        self.save()

    def _now(self):
        return self.clock()

    def _timestamp(self):
        return self._now().strftime("%H:%M:%S")

    def _iso_timestamp(self):
        return self._now().isoformat()

    def _log(self, message):
        self.log.append(f"[{self._timestamp()}] {message}")

    def _failure(self, message):
        return OpResult(False, message)

    def _reset_finalized(self):
        if self.finalized:
            self.finalized = False
            self._log("FINALIZED state cleared because intake fields changed")

    def _set_proposal(self, field_id, value):
        item = schema.FIELD_BY_ID[field_id]
        state = self.fields[field_id]
        state.value = deepcopy(value)
        state.unit = item.unit
        state.status = "default_proposed"
        state.source_quote = None
        state.updated_at = self._iso_timestamp()

    def load_preset(self, path):
        try:
            preset = json.loads(Path(path).read_text(encoding="utf-8"))
            preset_fields = preset["fields"]
            if not isinstance(preset_fields, dict):
                raise ValueError("preset fields must be an object")
            validated = {}
            for field_id, value in preset_fields.items():
                if field_id not in schema.FIELD_BY_ID:
                    raise ValueError(f"unknown preset field {field_id!r}")
                field = schema.FIELD_BY_ID[field_id]
                validated[field_id] = schema.validate(field, value, None)
        except (OSError, KeyError, TypeError, ValueError) as exc:
            return self._failure(f"Could not load preset: {exc}")
        self._reset_finalized()
        for field_id, value in validated.items():
            self._set_proposal(field_id, value)
        name = preset.get("name", Path(path).stem)
        self._log(f"PRESET loaded {name} ({len(validated)} fields proposed)")
        self.save()
        return OpResult(True, f"Loaded {name} ({len(validated)} fields proposed)", {"fields": len(validated)})

    def start_blank(self):
        self._reset_finalized()
        self.fields = {item.id: FieldState() for item in schema.FIELDS}
        self.acknowledged.clear()
        self.files.clear()
        self._log("START blank")
        self.save()
        return OpResult(True, "Started a blank intake session")

    def log_user(self, text):
        self._log(f'USER: "{text}"')
        self.save()

    def log_bot(self, text):
        self._log(f'BOT: "{str(text)[:300]}"')
        self.save()

    def log_system(self, text):
        self._log(f'SYSTEM: "{text}"')
        self.save()

    def _original_unit(self, value, unit):
        if isinstance(value, str):
            try:
                number, embedded_unit = units.parse_quantity(value)
            except ValueError:
                return value, unit
            return number, embedded_unit if embedded_unit is not None else unit
        return value, unit

    def _log_value(self, field, value, original_value, original_unit, status, quote):
        if field.type == "table":
            total = sum(row.get("power_W", 0) for row in value)
            description = f"SET {field.id} ({len(value)} rows, {units.format_value(total, 'W')})"
        elif field.type in {"object", "list", "multi", "vec2", "vec3"}:
            description = f"SET {field.id} = {json.dumps(value, ensure_ascii=False, separators=(',', ':'))}"
        elif field.type in {"float", "int"}:
            description = f"SET {field.id} = {units.format_value(value, field.unit)}"
        else:
            description = f"SET {field.id} = {value}"
        if field.unit and original_unit:
            try:
                normalized = units.normalize_unit(original_unit)
            except units.UnitError:
                normalized = original_unit
            if normalized != field.unit:
                original_display = (
                    str(int(original_value))
                    if isinstance(original_value, float) and original_value.is_integer()
                    else str(original_value)
                )
                description += f" (from {original_display} {original_unit})"
        self._log(f'{description} status={status} quote="{quote}"')

    def _auto_total_power(self):
        state = self.fields["total_power"]
        if state.status in DONE:
            return
        sources = self.fields["heat_sources"].value or []
        total = round(sum(row["power_W"] for row in sources), 2)
        self._set_proposal("total_power", total)
        self._log(f"AUTO total_power = {units.format_value(total, 'W')} (sum of heat_sources)")

    def _auto_fluid_properties(self, fluid):
        properties = self.fields["fluid_properties"]
        if fluid != "water":
            properties.value = None
            properties.unit = None
            properties.status = "missing"
            properties.source_quote = None
            properties.updated_at = self._iso_timestamp()
            self._log("AUTO fluid_properties reset to missing for non-water coolant")
        elif properties.status == "missing":
            self._set_proposal("fluid_properties", schema.FIELD_BY_ID["fluid_properties"].default)
            self._log("AUTO fluid_properties proposed with water defaults")

    def set_field(self, field_id, value, unit=None, status="user_provided", user_quote=""):
        if field_id not in schema.FIELD_BY_ID:
            return self._failure(f"Unknown field {field_id!r}")
        if status not in {"user_provided", "assumption_confirmed"}:
            return self._failure("status must be 'user_provided' or 'assumption_confirmed'")
        item = schema.FIELD_BY_ID[field_id]
        original_value, original_unit = self._original_unit(value, unit)
        try:
            canonical = schema.validate(item, value, unit)
        except (ValueError, units.UnitError) as exc:
            message = str(exc)
            self._log(f'REJECTED {field_id}: {message} quote="{user_quote}"')
            self.save()
            return self._failure(message)
        resolved_status = status
        current = self.fields[field_id]
        if status == "assumption_confirmed":
            if not item.is_assumption or current.status != "default_proposed" or canonical != current.value:
                resolved_status = "user_provided"
        self._reset_finalized()
        current.value = canonical
        current.unit = item.unit
        current.status = resolved_status
        current.source_quote = user_quote
        current.updated_at = self._iso_timestamp()
        self._log_value(item, canonical, original_value, original_unit, resolved_status, user_quote)
        if field_id == "heat_sources":
            self._auto_total_power()
        elif field_id == "fluid":
            self._auto_fluid_properties(canonical)
        self.save()
        return OpResult(True, f"Set {field_id}", {"value": canonical, "status": resolved_status})

    def confirm_defaults(self, field_ids, user_quote=""):
        ids = list(field_ids)
        invalid = [
            field_id
            for field_id in ids
            if field_id not in self.fields or self.fields[field_id].status != "default_proposed"
        ]
        if invalid:
            return self._failure(
                "Can only confirm proposed defaults; unavailable fields: " + ", ".join(invalid)
            )
        self._reset_finalized()
        for field_id in ids:
            item = schema.FIELD_BY_ID[field_id]
            state = self.fields[field_id]
            status = "assumption_confirmed" if item.is_assumption else "user_provided"
            state.status = status
            state.source_quote = user_quote
            state.updated_at = self._iso_timestamp()
            self._log(
                f'CONFIRM {field_id} = {self._compact_value(state.value)} '
                f'status={status} quote="{user_quote}"'
            )
        self.save()
        return OpResult(True, f"Confirmed {len(ids)} proposed defaults", {"fields": ids})

    @staticmethod
    def _compact_value(value):
        if isinstance(value, (dict, list)):
            return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        return str(value)

    def mark_not_applicable(self, field_id, reason, user_quote=""):
        if field_id not in self.fields:
            return self._failure(f"Unknown field {field_id!r}")
        item = schema.FIELD_BY_ID[field_id]
        if self.is_required(field_id):
            return self._failure(f"{field_id} is currently required and cannot be marked not applicable")
        self._reset_finalized()
        state = self.fields[field_id]
        state.value = None
        state.unit = item.unit
        state.status = "not_applicable"
        state.source_quote = user_quote
        state.updated_at = self._iso_timestamp()
        self._log(f'NOT_APPLICABLE {field_id}: {reason} quote="{user_quote}"')
        self.save()
        return OpResult(True, f"Marked {field_id} not applicable")

    def acknowledge_warning(self, check_id, user_quote):
        warning = next(
            (item for item in intake_checks.run_checks(self.values()) if item.id == check_id and item.level == "warning"),
            None,
        )
        if warning is None:
            return self._failure(f"{check_id} is not a current warning")
        self.acknowledged[check_id] = user_quote
        self._log(f'ACKNOWLEDGE {check_id} quote="{user_quote}"')
        self.save()
        return OpResult(True, f"Acknowledged {check_id}")

    def values(self):
        return {
            field_id: state.value if state.status not in {"missing", "not_applicable"} else None
            for field_id, state in self.fields.items()
        }

    def is_required(self, field_id):
        return schema.is_required(schema.FIELD_BY_ID[field_id], self.values())

    def missing_required(self):
        return [
            item.id
            for item in schema.FIELDS
            if self.is_required(item.id) and self.fields[item.id].status not in DONE
        ]

    def progress(self):
        required = [item for item in schema.FIELDS if self.is_required(item.id)]
        return sum(self.fields[item.id].status in DONE for item in required), len(required)

    def checks(self):
        results = intake_checks.run_checks(self.values())
        for result in results:
            result.acknowledged = result.id in self.acknowledged
        return results

    def blocking_issues(self):
        return [
            result.message
            for result in self.checks()
            if result.level == "error" or (result.level == "warning" and not result.acknowledged)
        ]

    def is_complete(self):
        return not self.missing_required() and not self.blocking_issues()

    def next_group(self):
        missing = set(self.missing_required())
        return next((item.group for item in schema.FIELDS if item.id in missing), None)

    def digest(self):
        group_number = self.next_group()
        group_fields = []
        if group_number is not None:
            for item in schema.FIELDS:
                if item.group != group_number or not self.is_required(item.id):
                    continue
                state = self.fields[item.id]
                if state.status in DONE:
                    continue
                group_fields.append(
                    {
                        "id": item.id,
                        "label": item.label,
                        "unit": item.unit,
                        "status": state.status,
                        "value": deepcopy(state.value) if state.status == "default_proposed" else None,
                        "is_assumption": item.is_assumption,
                        "choices": item.choices,
                        "help": item.help,
                        "required": True,
                    }
                )
        next_group_name = schema.GROUPS.get(group_number) if group_number is not None else None
        other_open = {}
        for item in schema.FIELDS:
            if self.is_required(item.id) and self.fields[item.id].status not in DONE and item.group != group_number:
                group_name = schema.GROUPS[item.group]
                other_open[group_name] = other_open.get(group_name, 0) + 1
        failing_checks = [
            {
                "id": result.id,
                "level": result.level,
                "message": result.message,
                "acknowledged": result.acknowledged,
            }
            for result in self.checks()
            if result.level != "ok"
        ]
        return {
            "progress": list(self.progress()),
            "next_group": group_number,
            "next_group_name": next_group_name,
            "next_group_fields": group_fields,
            "other_open_by_group": other_open,
            "failing_checks": failing_checks,
            "complete": self.is_complete(),
        }

    def finalize(self, user_quote=""):
        missing = self.missing_required()
        blocking = self.blocking_issues()
        if missing or blocking:
            parts = []
            if missing:
                parts.append("Missing required fields: " + ", ".join(missing))
            if blocking:
                parts.append("Blocking checks: " + "; ".join(blocking))
            return self._failure(". ".join(parts))
        self.finalized = True
        self._log(f'FINALIZE quote="{user_quote}"')
        self.save()
        final_path = self.dir / "requirements_final.json"
        final_path.write_text(
            json.dumps(self._requirements_document(), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return OpResult(True, "Requirements finalized", {"path": str(final_path)})

    def _requirements_document(self):
        return {
            "session_id": self.session_id,
            "finalized": self.finalized,
            "schema_version": 1,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "fields": {
                item.id: {
                    "value": deepcopy(self.fields[item.id].value),
                    "unit": self.fields[item.id].unit,
                    "status": self.fields[item.id].status,
                    "source_quote": self.fields[item.id].source_quote,
                    "updated_at": self.fields[item.id].updated_at,
                    "required": self.is_required(item.id),
                    "is_assumption": item.is_assumption,
                    "group": item.group,
                }
                for item in schema.FIELDS
            },
            "checks": [
                {
                    "id": result.id,
                    "level": result.level,
                    "message": result.message,
                    "acknowledged": result.acknowledged,
                }
                for result in self.checks()
            ],
            "files": self.files,
        }

    def _display_value(self, item, state):
        if state.status == "missing":
            return "MISSING"
        if state.status == "not_applicable":
            return "NOT APPLICABLE"
        if item.type == "table":
            total = sum(row.get("power_W", 0) for row in (state.value or []))
            return f"{len(state.value)} rows, {total:g} W"
        if item.type in {"vec2", "vec3"}:
            values = " × ".join(units.format_value(value, "") for value in state.value)
            return f"{values} {item.unit}".strip()
        if item.type == "list" and item.quantity:
            values = ", ".join(units.format_value(value, "") for value in state.value)
            return f"{values} {item.unit}".strip()
        if item.type in {"float", "int"}:
            return units.format_value(state.value, item.unit)
        if isinstance(state.value, (dict, list)):
            return json.dumps(state.value, ensure_ascii=False, separators=(",", ":"))
        return str(state.value)

    def summary_text(self):
        lines = []
        for group_number, group_name in schema.GROUPS.items():
            group_fields = [
                item for item in schema.FIELDS
                if item.group == group_number and self.fields[item.id].status != "missing"
            ]
            if not group_fields:
                continue
            lines.append(f"Group {group_number} — {group_name}")
            for item in group_fields:
                state = self.fields[item.id]
                assumption = " (ASSUMPTION)" if item.is_assumption else ""
                display = self._display_value(item, state)
                lines.append(
                    f"  {item.label}: {display}{assumption} [{state.status}]"
                )
        failing = [result for result in self.checks() if result.level != "ok"]
        if failing:
            for result in failing:
                acknowledged = " (acknowledged)" if result.acknowledged else ""
                lines.append(f"Checks: {result.id} ({result.level}): {result.message}{acknowledged}")
        else:
            lines.append("Checks: none failing")
        return "\n".join(lines)

    def _notes_text(self):
        lines = [f"=== Cold plate intake session {self.session_id} ==="]
        lines.extend(self.log)
        lines.append("--- CURRENT STATE (rewritten each update) ---")
        for group_number, group_name in schema.GROUPS.items():
            lines.append(f"[{group_name}]")
            for item in schema.FIELDS:
                if item.group == group_number:
                    state = self.fields[item.id]
                    lines.append(
                        f"  {item.id.ljust(24, '.')} {self._display_value(item, state)}   ({state.status})"
                    )
        lines.append("[Checks]")
        checks = self.checks()
        if checks:
            for result in checks:
                acknowledgement = " (acknowledged)" if result.acknowledged else ""
                lines.append(f"  {result.level.upper()} {result.id}: {result.message}{acknowledgement}")
        else:
            lines.append("  No checks")
        done, total = self.progress()
        lines.append(f"Progress: {done} / {total} required fields")
        return "\n".join(lines) + "\n"

    def save(self):
        self.updated_at = self._iso_timestamp()
        (self.dir / "notes.txt").write_text(self._notes_text(), encoding="utf-8")
        (self.dir / "requirements.json").write_text(
            json.dumps(self._requirements_document(), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
