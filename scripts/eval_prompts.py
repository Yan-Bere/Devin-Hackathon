"""Prompt-evaluation harness runner.

For each fixture document: parse_requirements, then score_extraction against
its rubric. Writes prompts/requirements_parser/eval/<version>-<UTC>.json and
prints a markdown table.

  --provider devin    live Devin sessions (consumes quota)
  --provider recorded replays tests/fixtures/devin_recordings/<stem>.<ver>.json
  --record            after a live parse, save the structured_output as a
                      recording fixture (never secrets)
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from coldplate import units  # noqa: E402
from coldplate.devin_client import DevinClient, DevinSettings  # noqa: E402
from coldplate.eval.harness import score_extraction  # noqa: E402
from coldplate.eval.rubric import RUBRICS  # noqa: E402
from coldplate.parser import parse_requirements  # noqa: E402

FIXTURES_DIR = REPO_ROOT / "tests" / "fixtures"
RECORDINGS_DIR = FIXTURES_DIR / "devin_recordings"
EVAL_DIR = REPO_ROOT / "prompts" / "requirements_parser" / "eval"
REFERENCE_FILES = {"power_map_W_per_mm2.csv": FIXTURES_DIR / "reference_files" / "power_map_W_per_mm2.csv"}


def _ref_files() -> dict[str, bytes]:
    return {name: p.read_bytes() for name, p in REFERENCE_FILES.items() if p.exists()}


def _pipeline_expectations(stem: str, result) -> list[str]:
    """Fixture-level assertions beyond the extraction rubric."""
    out = []
    spec = result.spec
    if stem == "E_missing_flow":
        ok = (
            result.status == "needs_input"
            and "coolant.flow_rate" in result.missing_essential
            and spec is not None
            and spec.coolant.flow_rate_Lpm.value != 2.0
        )
        out.append(f"E needs_input, flow missing & never 2.0: {'PASS' if ok else 'FAIL'}")
    elif stem == "B_flow_3lpm":
        ok = spec is not None and spec.coolant.flow_rate_Lpm.value == 3.0
        out.append(f"B spec flow 3.0: {'PASS' if ok else 'FAIL'}")
    elif stem == "C_gpu1_power_plus20":
        ok = spec is not None and abs((spec.total_power_W or 0) - 1603.68) < 0.01
        out.append(f"C total_power 1603.68: {'PASS' if ok else 'FAIL'}")
    elif stem == "D_plate_90x84":
        ok = spec is not None and (
            spec.plate.length_x_mm.value == 90.0
            and spec.plate.width_y_mm.value == 84.0
            and spec.plate.thickness_mm.value == 2.5
        )
        out.append(f"D plate 90x84x2.5: {'PASS' if ok else 'FAIL'}")
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--prompt-version", default="v1")
    ap.add_argument("--fixtures", default=None, help="comma list, e.g. A,B,E (default all)")
    ap.add_argument("--provider", choices=["devin", "recorded"], default="recorded")
    ap.add_argument("--no-cache", action="store_true")
    ap.add_argument("--record", action="store_true", help="record live structured_output to fixtures")
    args = ap.parse_args()

    all_stems = sorted(p.stem for p in FIXTURES_DIR.glob("*.md"))
    if args.fixtures:
        wanted = {s.strip().upper() for s in args.fixtures.split(",")}
        stems = [s for s in all_stems if s.split("_")[0].upper() in wanted]
    else:
        stems = all_stems

    client = None
    if args.provider == "devin":
        client = DevinClient(DevinSettings.from_env())

    ref = _ref_files()
    rows = []
    report = {"prompt_version": args.prompt_version, "at_utc": datetime.now(timezone.utc).isoformat(), "provider": args.provider, "fixtures": []}

    for stem in stems:
        doc_path = FIXTURES_DIR / f"{stem}.md"
        document = doc_path.read_text(encoding="utf-8")
        recording = None
        if args.provider == "recorded":
            rec_path = RECORDINGS_DIR / f"{stem}.{args.prompt_version}.json"
            if rec_path.exists():
                recording = json.loads(rec_path.read_text(encoding="utf-8"))
            else:
                print(f"{stem}: no recording at {rec_path}; skipped")
                continue

        t0 = time.perf_counter()
        result = parse_requirements(
            document,
            reference_files=ref,
            provider=args.provider,
            prompt_version=args.prompt_version,
            use_cache=not args.no_cache,
            client=client,
            recording=recording,
        )
        latency = time.perf_counter() - t0

        if args.record and args.provider == "devin" and result.extraction:
            RECORDINGS_DIR.mkdir(parents=True, exist_ok=True)
            sess = result.sessions[0].model_dump() if result.sessions else {}
            rec_path = RECORDINGS_DIR / f"{stem}.{args.prompt_version}.json"
            rec_path.write_text(
                json.dumps(
                    {
                        "fixture": stem,
                        "prompt_version": args.prompt_version,
                        "recorded_at_utc": datetime.now(timezone.utc).isoformat(),
                        "structured_output": result.extraction,
                        "session": sess,
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )

        rubric = RUBRICS.get(f"{stem}.md")
        score = score_extraction(result.extraction, document, rubric, units.convert) if rubric else None
        counts = score.counts if score else {}
        expectations = _pipeline_expectations(stem, result)

        entry = {
            "fixture": stem,
            "status": result.status,
            "provider_label": result.provider_label,
            "cached": result.cached,
            "devin_calls": result.devin_calls,
            "schema_failure": bool(result.initial_validation_errors),
            "repaired": result.repaired,
            "acus": sum(s.acus_consumed or 0 for s in result.sessions) or None,
            "sessions": [s.model_dump() for s in result.sessions],
            "latency_s": round(latency, 2),
            "findings": [f.__dict__ for f in score.findings] if score else [],
            "counts": counts,
            "expectations": expectations,
            "error": result.error,
            "initial_validation_errors": result.initial_validation_errors,
            "final_validation_errors": result.final_validation_errors,
            "missing_essential": result.missing_essential,
            "unsupported_assumptions": result.unsupported_assumptions,
            "evidence_misses": result.evidence_misses,
            "warnings": result.warnings,
        }
        report["fixtures"].append(entry)
        rows.append(entry)
        print(
            f"{stem:22} {result.status:12} calls={result.devin_calls} "
            f"repaired={result.repaired} findings={sum(counts.values()) if counts else 0}"
        )
        for e in expectations:
            print(f"   {e}")

    EVAL_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_path = EVAL_DIR / f"{args.prompt_version}-{stamp}.json"
    out_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    # markdown table
    print("\n| fixture | status | ext_err | prov_err | unsup_assum | evid_miss | value_not_in_quote | schema_fail | repaired | calls | ACU |")
    print("|---|---|---|---|---|---|---|---|---|---|---|")
    for r in rows:
        c = r["counts"]
        value_misses = sum(1 for m in r["evidence_misses"] if "does not appear in the evidence quote" in m)
        print(
            f"| {r['fixture']} | {r['status']} | {c.get('extraction_error',0)} | "
            f"{c.get('provenance_error',0)} | {c.get('unsupported_assumption',0)} | "
            f"{c.get('evidence_miss',0)} | {value_misses} | {r['schema_failure']} | {r['repaired']} | "
            f"{r['devin_calls']} | {r['acus']} |"
        )
    print(f"\nreport: {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
