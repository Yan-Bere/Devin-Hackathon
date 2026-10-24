"""Prompt templates for the requirements parser (prompts/requirements_parser/<v>/)."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

PROMPTS_ROOT = Path(__file__).resolve().parent.parent / "prompts" / "requirements_parser"


@dataclass(frozen=True)
class PromptTemplate:
    version: str
    task_template: str
    repair_template: str
    sha256: str  # sha256 of task+repair bytes; part of the parse cache key

    def render_task(self, document: str) -> str:
        doc = document.replace("\r\n", "\n").replace("\r", "\n")
        return self.task_template.replace("{document}", doc)

    def render_repair(self, errors: list[str]) -> str:
        lines = [f"- {e}" for e in errors[:30]]
        if len(errors) > 30:
            lines[-1] = f"- ... and {len(errors) - 29} more problems"
        return self.repair_template.replace("{errors}", "\n".join(lines))


def load_prompt(version: str = "v1") -> PromptTemplate:
    d = PROMPTS_ROOT / version
    task = (d / "task.md").read_text(encoding="utf-8")
    repair = (d / "repair.md").read_text(encoding="utf-8")
    h = hashlib.sha256()
    h.update(task.encode("utf-8"))
    h.update(b"\x00")
    h.update(repair.encode("utf-8"))
    return PromptTemplate(version=version, task_template=task, repair_template=repair, sha256=h.hexdigest())
