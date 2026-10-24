"""Scoring of a Devin extraction against a fixture rubric (see ``rubric.py`` for semantics).

``score_extraction`` is pure: it takes the extraction as a plain dict, the document text,
the rubric and a unit converter ``convert(value, unit, kind) -> float`` (raising on an
unknown unit), and returns every finding. Run orchestration (live/recorded parses,
Devin call accounting, reports) lives in ``scripts/eval_prompts.py``.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Callable

from coldplate.evidence import evidence_found
from coldplate.eval.rubric import Check, Rubric

Converter = Callable[[float, "str | None", str], float]

CATEGORIES = ("extraction_error", "provenance_error", "unsupported_assumption", "evidence_miss")
ESSENTIAL_PREFIXES = ("plate.", "fin_region.", "heat_sources", "coolant.flow_rate", "coolant.inlet_temperature")
_MISSING = object()
_TOKEN = re.compile(r"^(?P<name>[A-Za-z_]+)(?:\[(?P<key>[A-Za-z_]+)=(?P<val>[^\]]+)\])?$")


@dataclass(frozen=True)
class Finding:
    category: str
    path: str
    detail: str


@dataclass
class ScoreReport:
    fixture: str
    n_checks: int
    findings: list[Finding] = field(default_factory=list)

    @property
    def counts(self) -> dict[str, int]:
        c = Counter(f.category for f in self.findings)
        return {k: c.get(k, 0) for k in CATEGORIES}

    def add(self, category: str, path: str, detail: str) -> None:
        self.findings.append(Finding(category, path, detail))


def resolve(data: Any, path: str) -> Any:
    """Follow a dotted path; ``name[key=value]`` picks the first list element whose key contains value."""
    node = data
    for token in path.split("."):
        m = _TOKEN.match(token)
        if m is None or not isinstance(node, dict) or m["name"] not in node:
            return _MISSING
        node = node[m["name"]]
        if m["key"]:
            if not isinstance(node, list):
                return _MISSING
            want = m["val"].strip().lower()
            node = next((el for el in node if want in str(el.get(m["key"], "")).strip().lower()), _MISSING)
            if node is _MISSING:
                return _MISSING
    return node


def _close(a: float, b: float, rel_tol: float) -> bool:
    return math.isclose(a, b, rel_tol=rel_tol, abs_tol=1e-6 if b == 0 else 0.0)


def _text(node: Any) -> str | None:
    if isinstance(node, dict):
        node = node.get("value")
    return None if node is None else str(node)


def _check_source(report: ScoreReport, path: str, node: Any, allowed: tuple[str, ...]) -> None:
    if not isinstance(node, dict) or "source" not in node:
        return
    src = node["source"]
    if src == "assumed":
        report.add("unsupported_assumption", path, "value marked 'assumed' although the rubric expects it from the document")
    elif src not in allowed:
        report.add("provenance_error", path, f"source={src!r}, expected one of {list(allowed)}")


def _convert(report: ScoreReport, path: str, value: Any, unit: Any, kind: str, convert: Converter) -> float | None:
    try:
        return float(convert(float(value), unit, kind))
    except Exception as exc:  # noqa: BLE001 - any conversion failure is an extraction error
        report.add("extraction_error", path, f"unit not convertible ({unit!r} as {kind}): {exc}")
        return None


def _score_check(report: ScoreReport, check: Check, extraction: dict, convert: Converter) -> None:
    node = resolve(extraction, check.path)
    if node is _MISSING:
        report.add("extraction_error", check.path, "path not present in extraction")
        return

    if check.match == "list":
        values = node.get("values") if isinstance(node, dict) else None
        if not values:
            report.add("extraction_error", check.path, "list missing or empty")
        else:
            got = [_convert(report, check.path, v, node.get("unit"), check.kind or "", convert) for v in values]
            if all(g is not None for g in got):
                exp = sorted(check.value)  # type: ignore[arg-type]
                if len(got) != len(exp) or not all(_close(g, e, check.rel_tol) for g, e in zip(sorted(got), exp)):
                    report.add("extraction_error", check.path, f"got {sorted(got)}, expected {exp}")
        _check_source(report, check.path, node, check.sources)
        return

    if check.match == "contains_all":
        items = [str(x).lower() for x in node] if isinstance(node, list) else []
        for want in check.value:  # type: ignore[union-attr]
            if not any(str(want).lower() in item for item in items):
                report.add("extraction_error", check.path, f"{want!r} not listed (got {node!r})")
        return

    if check.match == "covers_type":
        items = [str(x).strip().lower() for x in node] if isinstance(node, list) else []
        for want in check.value:  # type: ignore[union-attr]
            w = str(want).strip().lower()
            names = [
                str(h.get("name", "")).strip().lower()
                for h in extraction.get("heat_sources") or []
                if str(h.get("type", "")).strip().lower() == w
            ]
            by_type = any(w in item for item in items)
            by_names = bool(names) and all(n in items for n in names)
            if not (by_type or by_names):
                report.add("extraction_error", check.path, f"{want!r} not covered by type or by all its source names (got {node!r})")
        return

    if check.kind is not None:  # numeric quantity
        value = node.get("value") if isinstance(node, dict) else None
        if value is None:
            report.add("extraction_error", check.path, f"value missing (expected {check.value})")
        else:
            got = _convert(report, check.path, value, node.get("unit"), check.kind, convert)
            if got is not None and not _close(got, float(check.value), check.rel_tol):  # type: ignore[arg-type]
                report.add("extraction_error", check.path, f"got {got:g}, expected {check.value:g}")
        _check_source(report, check.path, node, check.sources)
        return

    text = _text(node)
    if check.match == "one_of":
        ok = text is not None and text.strip().lower() in {str(v).lower() for v in check.value}  # type: ignore[union-attr]
    elif check.match == "contains":
        ok = text is not None and str(check.value).lower() in text.lower()
    else:
        ok = text is not None and text.strip().lower() == str(check.value).lower()
    if not ok:
        report.add("extraction_error", check.path, f"got {text!r}, expected {check.value!r} ({check.match})")
    _check_source(report, check.path, node, check.sources)


def _score_heat_sources(report: ScoreReport, rubric: Rubric, extraction: dict, convert: Converter) -> None:
    got = {str(h.get("name", "")).strip().lower(): h for h in extraction.get("heat_sources") or []}
    expected_names = {h.name.lower() for h in rubric.heat_sources}
    for exp in rubric.heat_sources:
        path = f"heat_sources[{exp.name}]"
        h = got.get(exp.name.lower())
        if h is None:
            report.add("extraction_error", path, "heat source missing")
            continue
        if str(h.get("type", "")).lower() != exp.type.lower():
            report.add("extraction_error", f"{path}.type", f"got {h.get('type')!r}, expected {exp.type!r}")
        for attr, kind, unit_key in (
            ("x0", "length", "length_unit"),
            ("y0", "length", "length_unit"),
            ("width", "length", "length_unit"),
            ("height", "length", "length_unit"),
            ("power", "power", "power_unit"),
        ):
            want = getattr(exp, attr)
            if h.get(attr) is None:
                report.add("extraction_error", f"{path}.{attr}", f"value missing (expected {want})")
                continue
            v = _convert(report, f"{path}.{attr}", h[attr], h.get(unit_key), kind, convert)
            if v is not None and not _close(v, want, rubric.heat_source_tol):
                report.add("extraction_error", f"{path}.{attr}", f"got {v:g}, expected {want:g}")
        _check_source(report, path, h, ("input",))
    for name, h in got.items():
        if name not in expected_names:
            report.add("extraction_error", f"heat_sources[{h.get('name')}]", "unexpected heat source")


def _walk_evidence(report: ScoreReport, node: Any, document: str, path: str) -> None:
    if isinstance(node, dict):
        if node.get("source") in ("input", "input_flagged_assumption") and "evidence" in node:
            if not evidence_found(node.get("evidence"), document):
                report.add("evidence_miss", path or "<root>", f"quote not found in document: {node.get('evidence')!r}")
        for key, child in node.items():
            _walk_evidence(report, child, document, f"{path}.{key}" if path else key)
    elif isinstance(node, list):
        for i, child in enumerate(node):
            tag = (child.get("name") or child.get("component_type")) if isinstance(child, dict) else None
            _walk_evidence(report, child, document, f"{path}[{tag or i}]")


def score_extraction(extraction: dict | None, document: str, rubric: Rubric, convert: Converter) -> ScoreReport:
    report = ScoreReport(fixture=rubric.fixture, n_checks=len(rubric.checks) + 6 * len(rubric.heat_sources))
    if extraction is None:
        report.add("extraction_error", "<root>", "no valid extraction (parse failed)")
        return report

    for check in rubric.checks:
        _score_check(report, check, extraction, convert)
    _score_heat_sources(report, rubric, extraction, convert)

    for path in rubric.expect_missing:
        report.n_checks += 1
        node = resolve(extraction, path)
        if node is _MISSING:
            report.add("extraction_error", path, "path not present in extraction")
            continue
        src, value = node.get("source"), node.get("value")
        if src == "assumed":
            report.add("unsupported_assumption", path, f"absent from the document but reported as assumed value {value!r}")
        elif value is not None or src != "missing":
            report.add("extraction_error", path, f"absent from the document but reported value={value!r}, source={src!r}")

    missing_entries = [m for m in extraction.get("missing_fields") or [] if m.get("essential")]
    for needle in rubric.required_missing_entries:
        report.n_checks += 1
        if not any(needle.lower() in str(m.get("field", "")).lower() for m in missing_entries):
            report.add("extraction_error", "missing_fields", f"no essential missing_fields entry mentioning {needle!r}")
    if not rubric.allow_essential_missing:
        for m in missing_entries:
            if str(m.get("field", "")).lower().startswith(ESSENTIAL_PREFIXES):
                report.add("extraction_error", "missing_fields", f"essential input flagged missing although the document gives it: {m.get('field')!r}")

    for check in rubric.forbidden:
        report.n_checks += 1
        node = resolve(extraction, check.path)
        if isinstance(node, dict) and node.get("value") is not None and check.kind:
            try:
                got = float(convert(float(node["value"]), node.get("unit"), check.kind))
            except Exception:  # noqa: BLE001
                continue
            if _close(got, float(check.value), check.rel_tol):  # type: ignore[arg-type]
                report.add("extraction_error", check.path, f"forbidden value {check.value:g} reported (source={node.get('source')!r})")

    _walk_evidence(report, extraction, document, "")
    return report
