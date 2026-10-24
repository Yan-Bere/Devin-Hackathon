from app.pareto import pareto_ids


def test_pareto_minimizes_both_and_keeps_ties_and_duplicates():
    runs = [
        {"id": "a", "status": "completed", "metrics": {"pressure_drop_pa": 10, "max_temperature_k": 400}},
        {"id": "b", "status": "completed", "metrics": {"pressure_drop_pa": 20, "max_temperature_k": 350}},
        {"id": "c", "status": "completed", "metrics": {"pressure_drop_pa": 15, "max_temperature_k": 420}},
        {"id": "d", "status": "completed", "metrics": {"pressure_drop_pa": 10, "max_temperature_k": 400}},
        {"id": "e", "status": "running", "metrics": {"pressure_drop_pa": 1, "max_temperature_k": 1}},
        {"id": "f", "status": "completed", "metrics": {"pressure_drop_pa": None, "max_temperature_k": 300}},
    ]
    assert pareto_ids(runs) == {"a", "b", "d"}
