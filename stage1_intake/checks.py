"""Validation check interface; domain checks are introduced in milestone 4."""

from dataclasses import dataclass


@dataclass
class CheckResult:
    id: str
    level: str
    message: str
    acknowledged: bool = False


def run_checks(values: dict) -> list[CheckResult]:
    return []
