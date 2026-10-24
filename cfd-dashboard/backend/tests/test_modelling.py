"""Stage-3 modelling campaign: live path with a fake engine + start/status API."""

import time
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.config import AppConfig
from app.main import create_app
from app import modelling


def _fake_run_job():
    def fake(job_dir, document, reference_files, options,
             on_interpretation=None, on_candidate=None, **kw):
        if on_interpretation:
            on_interpretation({"provider": "devin",
                               "provider_label": "Devin (v3)",
                               "session_url": "https://app.devin.ai/sessions/devin-fake",
                               "cached": False, "devin_calls": 1,
                               "api_version": "v3"})
        for i in range(3):
            cand = SimpleNamespace(
                candidate_id=f"c{i:03d}",
                params={"fin_thickness_mm": 0.3,
                        "channel_width_by_zone_mm": {"GPU": 0.3},
                        "fin_height_mm": 2.0, "n_channels": 86},
                metrics={"pressure_drop_kPa": 0.5 + i,
                         "critical_temperature_C": 60 + i,
                         "hbm_max_C": 55 + i, "gpu_max_C": 75 + i,
                         "hbm_hottest": "H6", "gpu_hottest": "GPU1",
                         "coolant_rise_K": 10.7, "coolant_outlet_C": 40.7},
                feasible=True, violations=[], design_id=f"c{i:03d}")
            if on_candidate:
                on_candidate(cand)
        return {"status": "completed"}
    return fake


def _wait_finished(deadline=15.0):
    end = time.monotonic() + deadline
    while time.monotonic() < end:
        s = modelling.status()
        if s["status"] in ("completed", "failed"):
            return s
        time.sleep(0.1)
    raise AssertionError("campaign did not finish")


def test_live_campaign_streams_runs(tmp_path, monkeypatch):
    import coldplate.pipeline
    monkeypatch.setattr(coldplate.pipeline, "run_job", _fake_run_job())
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir()
    client = TestClient(create_app(AppConfig(runs_dir=runs_dir, budget=10)))
    body = {"demo": False,
            "requirements_final": {"finalized": True,
                                   "fields": {"flow_nominal": {"value": 2.0}}}}
    r = client.post("/api/modelling/start", json=body)
    assert r.status_code == 200, r.text
    final = _wait_finished()
    assert final["status"] == "completed", final
    assert final["mode"] == "live"
    # the three candidates were streamed into run folders
    client.app.state.store.scan()
    runs = client.app.state.store.list_runs()
    assert len(runs) == 3
    assert all(r["metrics"]["pressure_drop_pa"] > 0 for r in runs)
    assert all(r["details"]["source"] == "stage3-reduced-order-model" for r in runs)
    assert client.get("/api/modelling/status").json()["status"] == "completed"


def test_live_campaign_failure_surfaces(tmp_path, monkeypatch):
    import coldplate.pipeline
    def boom(*a, **k):
        raise RuntimeError("engine exploded")
    monkeypatch.setattr(coldplate.pipeline, "run_job", boom)
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir()
    client = TestClient(create_app(AppConfig(runs_dir=runs_dir, budget=10)))
    client.post("/api/modelling/start", json={
        "demo": False, "requirements_final": {"finalized": True, "fields": {}}})
    final = _wait_finished()
    assert final["status"] == "failed"
    assert "engine exploded" in final["error"]
    assert "engine exploded" in client.get("/api/modelling/status").json()["error"]
