import json
from time import perf_counter

from stage2_optimizer import optimize


def test_optimizer_records_candidates_and_finishes_under_30_seconds(
    finalized_requirements,
):
    document = json.loads(finalized_requirements.read_text(encoding="utf-8"))
    values = {
        field_id: entry["value"]
        for field_id, entry in document["fields"].items()
    }
    start = perf_counter()
    result = optimize.optimize(values)
    elapsed = perf_counter() - start

    assert set(result) >= {
        "baseline",
        "optimized",
        "feasible",
        "failing_constraints",
        "sweep",
        "evaluations",
        "evaluation_count",
        "elapsed_seconds",
    }
    assert 1000 <= result["evaluation_count"] <= 1500
    assert len(result["evaluations"]) == result["evaluation_count"]
    assert all(
        {"feasible", "T_hbm_max_C", "delta_p_nominal_kPa"} <= set(record)
        for record in result["evaluations"]
    )
    assert elapsed < 30
    assert result["optimized"]["fom"] == max(
        record["fom"] for record in result["evaluations"]
    )
    assert result["feasible"] is True
    assert result["failing_constraints"] == []
    assert all(
        item["name"] != "Coolant outlet rise"
        for item in result["optimized"]["constraints"]
    )
