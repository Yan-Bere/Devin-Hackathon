import json

from stage2_optimizer import model


def test_baseline_sanity_at_nominal_point(finalized_requirements):
    document = json.loads(finalized_requirements.read_text(encoding="utf-8"))
    values = {
        field_id: entry["value"]
        for field_id, entry in document["fields"].items()
    }
    result = model.evaluate_point(values, 0.3, 0.3, 2.0, 30.0)

    print(
        "| Design | t_f (mm) | gap (mm) | fins | GPU max (°C) | "
        "HBM max (°C) | ΔP (kPa) | ΔP (psi) | Pumping power (W) |"
    )
    print(
        "| Baseline | 0.3 | 0.3 | "
        f"{result['fin_count']} | {result['max_gpu_C']:.2f} | "
        f"{result['max_hbm_C']:.2f} | {result['delta_p_kPa']:.2f} | "
        f"{result['delta_p_psi']:.2f} | {result['pumping_power_W']:.2f} |"
    )
    assert 1 <= result["delta_p_kPa"] <= 60
    assert 40 <= result["max_gpu_C"] <= 120
    assert result["flow_L_min"] == 2.0
    assert result["inlet_temp_C"] == 30.0
