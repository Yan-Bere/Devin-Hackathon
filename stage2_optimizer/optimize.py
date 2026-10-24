"""Differential-evolution search, figure of merit, and constraints."""

from time import perf_counter

from scipy.optimize import differential_evolution

from .model import evaluate_point


def operating_points(values):
    mode = values["sweep_mode"]
    flows = values["flow_sweep"]
    if mode == "flow_sweep_at_nominal_temp":
        return [(flow, values["inlet_temp_nominal"]) for flow in flows]
    if mode == "full_grid":
        return [
            (flow, temperature)
            for temperature in values["inlet_temp_sweep"]
            for flow in flows
        ]
    raise ValueError(f"unsupported sweep_mode {mode!r}")


def _constraint_results(values, sweep):
    gpu_limit = values["gpu_tmax_limit"] - values["temp_safety_margin"]
    hbm_limit = values["hbm_tmax_limit"] - values["temp_safety_margin"]
    max_flow = max(point["flow_L_min"] for point in sweep)
    max_flow_pressure = max(
        point["delta_p_kPa"]
        for point in sweep
        if point["flow_L_min"] == max_flow
    )
    checks = [
        {
            "name": "GPU maximum temperature",
            "actual": max(point["max_gpu_C"] for point in sweep),
            "limit": gpu_limit,
            "unit": "°C",
        },
        {
            "name": "HBM maximum temperature",
            "actual": max(point["max_hbm_C"] for point in sweep),
            "limit": hbm_limit,
            "unit": "°C",
        },
        {
            "name": "Pressure drop at maximum flow",
            "actual": max_flow_pressure,
            "limit": values["dp_design_cap_at_max_flow"],
            "unit": "kPa",
        },
    ]
    if values["dp_over_limit_rule"] == "disqualify":
        checks.append(
            {
                "name": "Pressure-drop hard limit",
                "actual": max_flow_pressure,
                "limit": values["dp_hard_limit"],
                "unit": "kPa",
            }
        )
    elif values["dp_over_limit_rule"] != "penalty":
        raise ValueError(f"unsupported dp_over_limit_rule {values['dp_over_limit_rule']!r}")
    for check in checks:
        check["passed"] = check["actual"] <= check["limit"]
    return checks


def _figure_of_merit(values, nominal, baseline_nominal):
    penalty = 0.0
    if values["dp_over_limit_rule"] == "penalty":
        penalty = values["dp_penalty_per_psi"] * max(
            0.0, nominal["delta_p_psi"] - 4.0
        )
    return (
        values["fom_weight_gpu"]
        * (baseline_nominal["max_gpu_C"] - nominal["max_gpu_C"])
        / baseline_nominal["max_gpu_C"]
        + values["fom_weight_hbm"]
        * (baseline_nominal["max_hbm_C"] - nominal["max_hbm_C"])
        / baseline_nominal["max_hbm_C"]
        - penalty
    )


def _evaluate_design(values, t_f_mm, gap_mm, points, baseline_nominal):
    cache = {}

    def evaluate(flow, temperature):
        key = (float(flow), float(temperature))
        if key not in cache:
            cache[key] = evaluate_point(
                values, t_f_mm, gap_mm, flow, temperature
            )
        return cache[key]

    nominal = evaluate(values["flow_nominal"], values["inlet_temp_nominal"])
    sweep = [evaluate(flow, temperature) for flow, temperature in points]
    constraints = _constraint_results(values, sweep)
    failing = [check for check in constraints if not check["passed"]]
    return {
        "fin_thickness_mm": t_f_mm,
        "gap_mm": gap_mm,
        "fin_count": nominal["fin_count"],
        "feasible": not failing,
        "constraints": constraints,
        "failing_constraints": failing,
        "fom": _figure_of_merit(values, nominal, baseline_nominal),
        "nominal": nominal,
        "sweep": sweep,
        "T_hbm_max_C": max(point["max_hbm_C"] for point in sweep),
        "T_gpu_max_C": max(point["max_gpu_C"] for point in sweep),
        "delta_p_nominal_kPa": nominal["delta_p_kPa"],
        "delta_p_nominal_psi": nominal["delta_p_psi"],
    }


def optimize(values):
    """Optimize fin thickness and channel width for the supplied intake values."""
    start = perf_counter()
    points = operating_points(values)
    if not points:
        raise ValueError("the selected sweep_mode has no operating points")

    baseline_nominal = evaluate_point(
        values,
        0.3,
        0.3,
        values["flow_nominal"],
        values["inlet_temp_nominal"],
    )
    baseline = _evaluate_design(
        values,
        0.3,
        0.3,
        points,
        baseline_nominal,
    )

    evaluations = []

    def objective(parameters):
        record = _evaluate_design(
            values,
            float(parameters[0]),
            float(parameters[1]),
            points,
            baseline_nominal,
        )
        evaluations.append(record)
        if record["feasible"]:
            return -record["fom"]
        violation = sum(
            max(0.0, check["actual"] - check["limit"])
            / max(abs(check["limit"]), 1.0)
            for check in record["failing_constraints"]
        )
        return 1e6 + violation

    minimum = values["min_feature"]
    maximum = values["max_feature"]
    differential_evolution(
        objective,
        bounds=[(minimum, maximum), (minimum, maximum)],
        seed=0,
        polish=False,
        maxiter=40,
        popsize=15,
        tol=0.0,
        atol=0.0,
    )
    feasible = [record for record in evaluations if record["feasible"]]
    optimized = max(feasible or evaluations, key=lambda record: record["fom"])
    return {
        "baseline": baseline,
        "optimized": optimized,
        "feasible": optimized["feasible"],
        "failing_constraints": optimized["failing_constraints"],
        "sweep": optimized["sweep"],
        "evaluations": evaluations,
        "evaluation_count": len(evaluations),
        "elapsed_seconds": perf_counter() - start,
        "baseline_design_text": values["baseline_design"],
    }
