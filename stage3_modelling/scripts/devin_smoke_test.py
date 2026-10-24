"""Devin API v3 smoke test for the coldplate engine.

--dry-run: only calls GET /self (no session, consumes no quota).
Default:   creates ONE minimal structured-output session, waits, prints the
           result, terminates the session, and writes a JSON record to
           runs/smoke/<UTC timestamp>.json (no secrets).

Exit code 0 on success, non-zero with the mapped error message otherwise.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from coldplate.devin_client import DevinClient, DevinError, DevinSettings  # noqa: E402

PROMPT = (
    "Integration smoke test. Do not run code, open repositories, browse, or "
    "create files. Immediately call the structured output tool with ok=true "
    'and echo="coldplate-smoke-v1", then end your turn.'
)

SCHEMA = {
    "type": "object",
    "properties": {
        "ok": {"type": "boolean"},
        "echo": {"type": "string"},
    },
    "required": ["ok", "echo"],
    "additionalProperties": False,
}

TITLE = "coldplate-engine smoke test"
TAGS = ["coldplate-engine", "smoke-test"]


def _mask_org(org_id: str) -> str:
    if len(org_id) <= 7:
        return org_id
    return f"{org_id[:6]}…{org_id[-2:]}"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="only call GET /self; creates no session and consumes no quota",
    )
    args = ap.parse_args()

    try:
        settings = DevinSettings.from_env()
    except DevinError as e:
        print(f"CONFIG ERROR: {e}", file=sys.stderr)
        return 2

    client = DevinClient(settings)
    try:
        print(f"api_version: {client.api_version}")
        if client.api_version == "v1":
            print(
                "note: legacy v1 API — ACU consumption is not reported by this "
                "endpoint (acus_consumed will be null)"
            )
        if args.dry_run:
            me = client.whoami()
            print("GET /self OK" if client.api_version == "v3" else "GET /sessions?limit=1 OK")
            print(json.dumps(me, indent=2, default=str))
            if settings.org_id:
                print(f"org_id: {_mask_org(settings.org_id)}")
            return 0

        result = client.run_structured(
            PROMPT,
            SCHEMA,
            title=TITLE,
            tags=TAGS,
            terminate=True,
            timeout_s=600,
        )
    except DevinError as e:
        print(f"DEVIN ERROR: {e}", file=sys.stderr)
        return 1
    finally:
        client.close()

    record = {
        "kind": "devin-smoke-v1",
        "at_utc": datetime.now(timezone.utc).isoformat(),
        "api_version": client.api_version,
        "org_id": _mask_org(settings.org_id) if settings.org_id else None,
        "session_id": result.session_id,
        "url": result.url,
        "status": result.status,
        "status_detail": result.status_detail,
        "structured_output": result.structured_output,
        "acus_consumed": result.acus_consumed,
        "on_demand_usage": result.on_demand_usage,
        "elapsed_s": round(result.elapsed_s, 1),
        "polls": result.polls,
        "last_devin_message": result.last_devin_message,
    }
    out_dir = REPO_ROOT / "runs" / "smoke"
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_path = out_dir / f"{stamp}.json"
    out_path.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")

    for k, v in record.items():
        print(f"{k}: {v}")
    print(f"record: {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
