"""Offline pipeline tests: normalize_extraction, parse_requirements, harness."""

from __future__ import annotations

import copy
import json
from collections import deque
from pathlib import Path

import pytest

from coldplate.devin_client import DevinError, SessionResult
from coldplate.eval.harness import score_extraction
from coldplate.eval.rubric import RUBRICS
from coldplate.extraction_schema import RequirementsExtraction
from coldplate.normalize import normalize_extraction
from coldplate.parser import parse_requirements
from coldplate.spec import ColdPlateSpec
from coldplate import units

FIXTURES = Path(__file__).parent / "fixtures"
GOLDEN_RAW = json.loads(
    (FIXTURES / "golden" / "A_canonical.extraction.json").read_text(encoding="utf-8")
)
REF = {
    "power_map_W_per_mm2.csv": (
        FIXTURES / "reference_files" / "power_map_W_per_mm2.csv"
    ).read_bytes()
}
DOCS = {
    p.stem: p.read_text(encoding="utf-8")
    for p in FIXTURES.glob("*.md")
}


def golden() -> dict:
    return copy.deepcopy(GOLDEN_RAW)


def validate(raw: dict) -> RequirementsExtraction:
    return RequirementsExtraction.model_validate(raw)


def norm(raw: dict, doc_stem: str = "A_canonical", ref=None):
    return normalize_extraction(
        validate(raw), document=DOCS[doc_stem],
        reference_files=REF if ref is None else ref,
    )


# --- variants ---------------------------------------------------------------

def variant_B():
    g = golden()
    g["coolant"]["flow_rate"] = {
        "value": 3.0, "unit": "L/min", "source": "input_flagged_assumption",
        "evidence": "| Flow, nominal (**ASSUMPTION**) | 3.0 L/min |", "note": None,
    }
    return g


def variant_C():
    g = golden()
    g["heat_sources"][0] = {
        **g["heat_sources"][0],
        "power": 665.28,
        "evidence": "| GPU1 | GPU | 0.00 | 10.15 | 26.0 | 30.0 | 665.28 | 85.3 |",
    }
    g["stated_total_power"] = {
        "value": 1603.68, "unit": "W", "source": "input",
        "evidence": "Total power: **1603.68 W**.", "note": None,
    }
    return g


def variant_D():
    g = golden()
    row = "| Base plate | 90 × 84 × 2.5 mm, rolled copper (C110 assumed, k = 391 W/m·K), centered on package |"
    g["plate"]["length_x"] = {"value": 90.0, "unit": "mm", "source": "input", "evidence": row, "note": None}
    g["plate"]["width_y"] = {"value": 84.0, "unit": "mm", "source": "input", "evidence": row, "note": None}
    g["plate"]["thickness"] = {"value": 2.5, "unit": "mm", "source": "input", "evidence": row, "note": None}
    frow = "| Fin design space | 56.00 × 54.00 × 2.0 mm, centered on package |"
    g["fin_region"]["length_x"] = {"value": 56.0, "unit": "mm", "source": "input", "evidence": frow, "note": None}
    g["fin_region"]["width_y"] = {"value": 54.0, "unit": "mm", "source": "input", "evidence": frow, "note": None}
    g["fin_region"]["height"] = {"value": 2.0, "unit": "mm", "source": "input", "evidence": frow, "note": None}
    g["fin_region"]["placement"]["evidence"] = frow
    return g


def variant_E(flow_assumed: bool = False):
    g = golden()
    if flow_assumed:
        g["coolant"]["flow_rate"] = {
            "value": 2.0, "unit": "L/min", "source": "assumed",
            "evidence": None, "note": "guessed typical flow",
        }
    else:
        g["coolant"]["flow_rate"] = {
            "value": None, "unit": None, "source": "missing",
            "evidence": None, "note": "not stated",
        }
    g["coolant"]["flow_rate_sweep"] = {
        "values": [], "unit": None, "source": "missing", "evidence": None, "note": None,
    }
    g["missing_fields"].append(
        {"field": "coolant.flow_rate", "reason": "not stated", "essential": True}
    )
    return g


def variant_F():
    g = golden()
    gpu_ev = "| GPU max temp | 40 °C | ≤ 38 °C | ≤ 36 °C |"
    hbm_ev = "| HBM max temp | 35 °C | ≤ 34 °C | ≤ 33 °C |"
    vals = {"GPU": (40.0, 38.0, 36.0, gpu_ev), "HBM": (35.0, 34.0, 33.0, hbm_ev)}
    for tl in g["temperature_limits"]:
        h, t, s, ev = vals[tl["component_type"]]
        tl["hard_max"] = {"value": h, "unit": "°C", "source": "input", "evidence": ev, "note": None}
        tl["target_max"] = {"value": t, "unit": "°C", "source": "input", "evidence": ev, "note": None}
        tl["stretch_max"] = {"value": s, "unit": "°C", "source": "input", "evidence": ev, "note": None}
    return g


# ---------------------------------------------------------------------------
# normalizer
# ---------------------------------------------------------------------------


def test_A_golden_normalizes_ok():
    res = norm(golden())
    assert res.status == "ok"
    assert res.blocking_errors == []
    assert res.missing_essential == []
    spec = res.spec
    assert len(spec.heat_sources) == 10
    assert spec.total_power_W == pytest.approx(1492.8)
    g1 = next(s for s in spec.heat_sources if s.name == "GPU1")
    assert g1.x0_plate_mm == pytest.approx(12.925)
    assert g1.y0_plate_mm == pytest.approx(24.0)
    # die region centered on the 78x78 plate
    assert spec.die_region.origin_plate_mm == pytest.approx([12.925, 13.85])
    assert spec.fin_region.origin_plate_mm == pytest.approx([12.925, 12.925])
    # provenance flags
    assert spec.coolant.flow_rate_Lpm.source == "input_flagged_assumption"
    assert spec.coolant.flow_rate_Lpm.value == 2.0
    assert spec.tim.r_m2K_W.value == pytest.approx(5e-6)
    assert spec.flow.arrangement == "split_edges_to_center"
    assert spec.flow.flow_axis == "x"  # assumed
    assert spec.flow.inlet_opening_mm.value == pytest.approx(0.212 * 52.15, abs=1e-3)
    assert spec.flow.outlet_opening_mm.value == pytest.approx(0.115 * 52.15, abs=1e-3)
    assert spec.flow.inlet_opening_mm.source == "engine_default"
    # power map file applied
    assert spec.power_map.applied == "file"
    # unit conversions
    assert spec.pressure.hard_Pa.value == pytest.approx(27600)
    assert spec.tim.r_m2K_W.value == pytest.approx(5e-6)
    # engine_inputs works
    ei = spec.engine_inputs()
    assert ei.flow_Lpm == 2.0 and ei.inlet_C == 30.0
    assert ei.limits_C == {"GPU": 100.0, "HBM": 70.0}
    assert ei.critical_type == "HBM"


def test_B_flow_3():
    res = norm(variant_B(), "B_flow_3lpm")
    assert res.status == "ok"
    assert res.spec.coolant.flow_rate_Lpm.value == 3.0


def test_C_total_power():
    res = norm(variant_C(), "C_gpu1_power_plus20")
    assert res.status == "ok"
    assert res.spec.total_power_W == pytest.approx(1603.68)


def test_D_plate():
    res = norm(variant_D(), "D_plate_90x84")
    assert res.status == "ok", res.blocking_errors
    spec = res.spec
    assert spec.plate.length_x_mm.value == 90.0
    assert spec.plate.width_y_mm.value == 84.0
    assert spec.plate.thickness_mm.value == 2.5
    assert spec.fin_region.length_x_mm.value == 56.0
    assert spec.fin_region.width_y_mm.value == 54.0
    # 56 x 54 centered on 90 x 84
    assert spec.fin_region.origin_plate_mm == pytest.approx([17.0, 15.0])


def test_E_missing_flow_needs_input():
    res = norm(variant_E(), "E_missing_flow")
    assert res.status == "needs_input"
    assert "coolant.flow_rate" in res.missing_essential
    assert res.spec.coolant.flow_rate_Lpm.value is None
    with pytest.raises(ValueError):
        res.spec.engine_inputs()


def test_E_assumed_flow_rejected():
    res = norm(variant_E(flow_assumed=True), "E_missing_flow")
    assert res.blocking_errors  # repair-worthy
    assert any("coolant.flow_rate" in u for u in res.unsupported_assumptions)
    # value is never used
    assert res.spec.coolant.flow_rate_Lpm.value is None
    assert "coolant.flow_rate" in res.missing_essential


def test_unsupported_arrangement():
    g = golden()
    g["flow"]["arrangement"] = "serpentine"
    res = norm(g)
    assert res.status == "unsupported"
    assert res.spec is None
    assert any("serpentine" in e for e in res.blocking_errors)


def test_source_outside_plate_blocking():
    g = golden()
    g["heat_sources"][0]["x0"] = 90.0
    g["heat_sources"][0]["evidence"] = "| GPU1 | GPU | 90.00 | 10.15 | 26.0 | 30.0 | 554.4 | 71.1 |"
    # note: doc has no such row -> evidence failure also fires; keep the check on blocking
    res = normalize_extraction(
        validate(g), document=DOCS["A_canonical"], reference_files=REF
    )
    assert res.status == "invalid" or res.blocking_errors
    assert any("outside the plate" in e or "evidence" in e for e in res.blocking_errors)


def test_source_outside_plate_blocking_clean_evidence():
    # construct a case where the footprint (not the quote) is the problem
    g = golden()
    g["heat_sources"][0]["x0"] = 55.0  # die-frame; plate x0 -> 12.925+55=67.9, +26 wide -> 93.9 > 78
    g["heat_sources"][0]["evidence"] = "| GPU1 | GPU | 55.00 | 10.15 | 26.0 | 30.0 | 554.4 | 71.1 |"
    res = norm(g)
    assert any("outside the plate" in e for e in res.blocking_errors)


def test_power_map_missing_file_warns_and_uniform():
    res = norm(golden(), "A_canonical", ref={})
    assert res.status == "ok"
    assert res.spec.power_map.applied == "uniform"
    assert any("referenced but not provided" in w for w in res.warnings)


def test_power_map_rescale_C():
    res = norm(variant_C(), "C_gpu1_power_plus20")
    assert res.spec.power_map.applied == "file"
    assert any("GPU1" in w and "rescaled" in w for w in res.warnings)


def test_stated_total_mismatch_warns():
    g = golden()
    g["stated_total_power"]["value"] = 1000.0
    g["stated_total_power"]["evidence"] = "Total power: **1492.8 W**."  # keep findable evidence
    res = norm(g)
    assert any("stated total" in w for w in res.warnings)


def test_unit_error_blocking():
    g = golden()
    g["coolant"]["density"] = {
        "value": 997.0, "unit": "snarfs", "source": "input",
        "evidence": "| Density | 997 kg/m³ |", "note": None,
    }
    res = norm(g)
    assert res.status == "invalid"
    assert any("snarfs" in e for e in res.blocking_errors)


# ---------------------------------------------------------------------------
# harness self-tests (rubric perturbations)
# ---------------------------------------------------------------------------


def test_golden_scores_zero():
    rep = score_extraction(GOLDEN_RAW, DOCS["A_canonical"], RUBRICS["A_canonical.md"], units.convert)
    assert rep.findings == []


def test_wrong_flow_is_extraction_error():
    g = variant_B()  # flow 3.0 while the A document/rubric expect 2.0
    rep = score_extraction(g, DOCS["A_canonical"], RUBRICS["A_canonical.md"], units.convert)
    assert any(f.category == "extraction_error" and f.path == "coolant.flow_rate" for f in rep.findings)


def test_flagged_source_flipped_to_input_is_provenance_error():
    g = golden()
    g["coolant"]["flow_rate"]["source"] = "input"
    rep = score_extraction(g, DOCS["A_canonical"], RUBRICS["A_canonical.md"], units.convert)
    assert any(f.category == "provenance_error" and f.path == "coolant.flow_rate" for f in rep.findings)


def test_E_flow_assumed_flags_unsupported_and_forbidden():
    rep = score_extraction(
        variant_E(flow_assumed=True), DOCS["E_missing_flow"],
        RUBRICS["E_missing_flow.md"], units.convert,
    )
    assert any(f.category == "unsupported_assumption" for f in rep.findings)
    assert any(
        f.category == "extraction_error" and "forbidden" in f.detail
        for f in rep.findings
    )


def test_fake_quote_is_evidence_miss():
    g = golden()
    g["coolant"]["flow_rate"]["evidence"] = "a quote that is nowhere in the document"
    rep = score_extraction(g, DOCS["A_canonical"], RUBRICS["A_canonical.md"], units.convert)
    assert any(f.category == "evidence_miss" for f in rep.findings)


def test_E_golden_variant_scores_clean():
    rep = score_extraction(
        variant_E(), DOCS["E_missing_flow"], RUBRICS["E_missing_flow.md"], units.convert
    )
    assert rep.findings == [], rep.findings


# ---------------------------------------------------------------------------
# parser with a scripted fake client
# ---------------------------------------------------------------------------


def _sr(output, sid="sess-1"):
    return SessionResult(
        session_id=sid,
        url=f"https://app.devin.ai/sessions/{sid}",
        status="exit",
        status_detail="finished",
        structured_output=output,
        acus_consumed=1.25,
        on_demand_usage=None,
        elapsed_s=12.0,
        polls=3,
        last_devin_message=None,
        raw={},
        api_version="v3",
    )


class FakeDevinClient:
    def __init__(self, outputs=(), fail=None):
        self.outputs = deque(outputs)
        self.fail = fail
        self.calls: list[str] = []
        self.terminated: list[str] = []

    def run_structured(self, prompt, schema, **kw):
        self.calls.append("run_structured")
        if self.fail:
            raise self.fail
        return _sr(self.outputs.popleft())

    def continue_structured(self, session_id, message, **kw):
        self.calls.append("continue_structured")
        return _sr(self.outputs.popleft())

    def terminate_session(self, session_id):
        self.calls.append("terminate")
        self.terminated.append(session_id)


def _broken_extraction() -> dict:
    g = golden()
    del g["coolant"]["flow_rate"]  # schema-invalid
    return g


def test_parse_devin_success(tmp_path):
    client = FakeDevinClient(outputs=[golden()])
    res = parse_requirements(
        DOCS["A_canonical"], reference_files=REF, provider="devin",
        client=client, cache_dir=tmp_path,
    )
    assert res.status == "ok"
    assert res.devin_calls == 1
    assert res.sessions[0].kind == "initial"
    assert client.terminated == ["sess-1"]
    assert res.spec is not None


def test_parse_cache_hit_zero_calls(tmp_path):
    client = FakeDevinClient(outputs=[golden()])
    r1 = parse_requirements(
        DOCS["A_canonical"], reference_files=REF, provider="devin",
        client=client, cache_dir=tmp_path,
    )
    assert r1.status == "ok"

    class Exploding:
        def __getattr__(self, name):
            raise AssertionError("must not be called on a cache hit")

    r2 = parse_requirements(
        DOCS["A_canonical"], reference_files=REF, provider="devin",
        client=Exploding(), cache_dir=tmp_path,
    )
    assert r2.cached is True
    assert r2.devin_calls == 0
    assert r2.status == "ok"
    assert "cached result" in r2.provider_label


def test_parse_repair_once(tmp_path):
    client = FakeDevinClient(outputs=[_broken_extraction(), golden()])
    res = parse_requirements(
        DOCS["A_canonical"], reference_files=REF, provider="devin",
        client=client, cache_dir=tmp_path,
    )
    assert res.status == "ok"
    assert res.repaired is True
    assert res.devin_calls == 2  # 1 session + 1 repair message
    assert [s.kind for s in res.sessions] == ["initial", "repair"]
    assert res.initial_validation_errors != []
    assert client.terminated == ["sess-1"]


def test_parse_invalid_twice_fails(tmp_path):
    client = FakeDevinClient(outputs=[_broken_extraction(), _broken_extraction()])
    res = parse_requirements(
        DOCS["A_canonical"], reference_files=REF, provider="devin",
        client=client, cache_dir=tmp_path,
    )
    assert res.status == "failed"
    assert res.error and "validation" in res.error
    assert client.terminated == ["sess-1"]


def test_parse_devin_error_maps_to_failed(tmp_path):
    client = FakeDevinClient(fail=DevinError("quota exhausted"))
    res = parse_requirements(
        DOCS["A_canonical"], reference_files=REF, provider="devin",
        client=client, cache_dir=tmp_path,
    )
    assert res.status == "failed"
    assert "quota" in res.error


def test_parse_recorded_provider(tmp_path):
    res = parse_requirements(
        DOCS["A_canonical"], reference_files=REF, provider="recorded",
        recording={"structured_output": golden(),
                   "session": {"session_id": "sess-rec", "url": "u"}},
        cache_dir=tmp_path,
    )
    assert res.status == "ok"
    assert res.devin_calls == 0
    assert "RECORDED" in res.provider_label
    assert res.sessions[0].session_id == "sess-rec"


def test_parse_manual_extraction_and_spec(tmp_path):
    res = parse_requirements(
        DOCS["A_canonical"], reference_files=REF, provider="manual",
        manual=golden(), cache_dir=tmp_path,
    )
    assert res.status == "ok"
    assert "MANUAL" in res.provider_label

    spec_dict = res.spec.model_dump()
    res2 = parse_requirements(
        DOCS["A_canonical"], reference_files=REF, provider="manual",
        manual=spec_dict, cache_dir=tmp_path,
    )
    assert res2.status == "ok"
    assert res2.spec.plate.length_x_mm.value == 78.0


def test_parse_needs_input_E(tmp_path):
    client = FakeDevinClient(outputs=[variant_E()])
    res = parse_requirements(
        DOCS["E_missing_flow"], reference_files=REF, provider="devin",
        client=client, cache_dir=tmp_path,
    )
    assert res.status == "needs_input"
    assert "coolant.flow_rate" in res.missing_essential
    # needs_input extractions are cacheable
    assert (tmp_path / f"{res.cache_key}.json").exists()
