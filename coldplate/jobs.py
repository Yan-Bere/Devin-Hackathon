"""In-memory job manager backed by runs/jobs/<job_id>/job.json."""

from __future__ import annotations

import json
import secrets
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from coldplate.pipeline import run_job

_TERMINAL = {"completed", "failed", "needs_input", "unsupported"}
_STAGE_WEIGHTS = {"parse": (0.0, 0.2), "evaluate": (0.2, 0.7),
                  "select": (0.7, 0.7), "sweep": (0.7, 0.85),
                  "export": (0.85, 1.0)}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_job_id() -> str:
    return datetime.now(timezone.utc).strftime("j%Y%m%dT%H%M%S-") + secrets.token_hex(2)


class Job:
    def __init__(self, job_id: str, job_dir: Path):
        self.job_id = job_id
        self.dir = job_dir
        self.status = "queued"
        self.stage = "queued"
        self.progress = 0.0
        self.message = "queued"
        self.events: list[dict] = []
        self.error: Optional[str] = None
        self.interpretation: dict = {}
        self.created_at = _now()
        self.updated_at = self.created_at

    def event(self, stage: str, message: str):
        self.events.append({"at": _now(), "stage": stage, "message": message})
        self.message = message

    def set(self, status: str, stage: str, frac: float, message: str):
        self.status = status
        self.stage = stage
        self.progress = min(max(frac, 0.0), 1.0)
        self.event(stage, message)
        self.updated_at = _now()
        self.persist()

    def persist(self):
        self.dir.mkdir(parents=True, exist_ok=True)
        (self.dir / "job.json").write_text(json.dumps(self.to_dict(), indent=2))

    def to_dict(self) -> dict:
        return {
            "job_id": self.job_id, "status": self.status, "stage": self.stage,
            "progress": round(self.progress, 4), "message": self.message,
            "events": self.events, "interpretation": self.interpretation,
            "error": self.error,
            "created_at": self.created_at, "updated_at": self.updated_at,
        }


class JobManager:
    def __init__(self, runs_dir: Path):
        self.runs_dir = Path(runs_dir)
        self.jobs: dict[str, Job] = {}
        self._lock = threading.Lock()
        self._pool = ThreadPoolExecutor(max_workers=1)
        self._recover()

    def _recover(self):
        """Mark non-terminal jobs left from a previous process as failed."""
        jobs_root = self.runs_dir / "jobs"
        if not jobs_root.is_dir():
            return
        for d in jobs_root.iterdir():
            jf = d / "job.json"
            if not jf.exists():
                continue
            try:
                data = json.loads(jf.read_text())
            except Exception:
                continue
            if data.get("status") not in _TERMINAL:
                data["status"] = "failed"
                data["error"] = "server restarted"
                data["updated_at"] = _now()
                data.setdefault("events", []).append(
                    {"at": _now(), "stage": data.get("stage", "?"),
                     "message": "server restarted; job marked failed"})
                jf.write_text(json.dumps(data, indent=2))

    def submit(self, document: str, reference_files: dict, options: dict) -> Job:
        job_id = new_job_id()
        job_dir = self.runs_dir / "jobs" / job_id
        job = Job(job_id, job_dir)
        with self._lock:
            self.jobs[job_id] = job
        job.persist()
        self._pool.submit(self._run, job, document, reference_files, options)
        return job

    def get(self, job_id: str) -> Optional[Job]:
        return self.jobs.get(job_id)

    def _run(self, job: Job, document, reference_files, options):
        def progress(stage: str, frac: float, msg: str):
            status = {"parse": "parsing", "evaluate": "evaluating",
                      "select": "selecting", "sweep": "sweeping",
                      "export": "exporting"}.get(stage, "evaluating")
            job.set(status, stage, frac, msg)
        try:
            job.set("parsing", "parse", 0.0, "job started")

            def on_interp(info: dict):
                job.interpretation = info
                job.persist()

            results = run_job(
                job.dir, document, reference_files, options, progress,
                on_interpretation=on_interp)
            interp = results.get("interpretation") or {}
            first = (interp.get("sessions") or [{}])[0]
            job.interpretation = {
                "provider": interp.get("provider"),
                "provider_label": interp.get("provider_label"),
                "session_id": first.get("session_id"),
                "session_url": first.get("url"),
                "cached": interp.get("cached"),
                "devin_calls": interp.get("devin_calls"),
                "api_version": interp.get("api_version"),
            }
            st = results.get("status", "failed")
            if st == "completed":
                job.set("completed", "export", 1.0, "completed")
            elif st in ("needs_input", "unsupported"):
                job.set(st, "parse", 1.0, st)
            else:
                job.error = "; ".join(results.get("warnings") or []) or "job failed"
                job.set("failed", "export", 1.0, "failed")
        except Exception as e:  # noqa: BLE001
            job.error = str(e)
            job.set("failed", "export", 1.0, f"failed: {e}")
        finally:
            job.persist()
