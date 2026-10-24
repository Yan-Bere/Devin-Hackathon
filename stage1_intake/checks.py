"""Cross-field consistency checks C1–C8 (C9 is out of scope)."""

from dataclasses import dataclass

TOL = 1e-6
C7_MIN_HEADROOM = 15.0


@dataclass
class CheckResult:
    id: str
    level: str  # "ok" | "info" | "warning" | "error"
    message: str
    acknowledged: bool = False


def _num(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def _vec(x, n):
    return isinstance(x, (list, tuple)) and len(x) >= n and all(_num(v) for v in x[:n])


def _sources(values):
    rows = values.get("heat_sources")
    if not isinstance(rows, list) or not rows:
        return None
    keys = ("x0", "y0", "w", "h", "power_W")
    if not all(isinstance(r, dict) and all(_num(r.get(k)) for k in keys) for r in rows):
        return None
    return rows


def _name(row, i):
    return str(row.get("name") or f"source {i + 1}")


def _c1(v):
    rows, total = _sources(v), v.get("total_power")
    if rows is None or not _num(total):
        return None
    s = sum(r["power_W"] for r in rows)
    if abs(s - total) > 0.1:
        return CheckResult("C1", "error", f"Heat sources sum to {s:.1f} W but total power is {total:.1f} W.")
    return CheckResult("C1", "ok", f"Heat sources sum to {s:.1f} W = total power.")


def _c2(v):
    rows, die = _sources(v), v.get("die_region_size")
    if rows is None or not _vec(die, 2):
        return None
    W, H = die[0], die[1]
    problems = []
    for i, r in enumerate(rows):
        if r["w"] <= 0 or r["h"] <= 0:
            problems.append(f"{_name(r, i)} has non-positive size")
        elif r["x0"] < -TOL or r["y0"] < -TOL or r["x0"] + r["w"] > W + TOL or r["y0"] + r["h"] > H + TOL:
            problems.append(f"{_name(r, i)} extends outside the {W:g} × {H:g} mm die region")
    for i, a in enumerate(rows):
        for j in range(i + 1, len(rows)):
            b = rows[j]
            ox = min(a["x0"] + a["w"], b["x0"] + b["w"]) - max(a["x0"], b["x0"])
            oy = min(a["y0"] + a["h"], b["y0"] + b["h"]) - max(a["y0"], b["y0"])
            if ox > TOL and oy > TOL:
                problems.append(f"{_name(a, i)} overlaps {_name(b, j)}")
    if problems:
        return CheckResult("C2", "error", "Heat-source layout: " + "; ".join(problems) + ".")
    return CheckResult("C2", "ok", f"All {len(rows)} heat sources lie inside the die region without overlap.")


def _c3(v):
    fin, base = v.get("fin_design_space"), v.get("base_plate_size")
    if not _vec(fin, 2) or not _vec(base, 2):
        return None
    if fin[0] > base[0] + TOL or fin[1] > base[1] + TOL:
        return CheckResult("C3", "error", f"Fin design space {fin[0]:g} × {fin[1]:g} mm does not fit on the {base[0]:g} × {base[1]:g} mm base plate.")
    return CheckResult("C3", "ok", "Fin design space fits on the base plate.")


def _c4(v):
    lo, hi, res_um = v.get("min_feature"), v.get("max_feature"), v.get("resolution_xy")
    if not _num(lo) or not _num(hi):
        return None
    problems = []
    if not lo < hi:
        problems.append(f"minimum feature {lo:g} mm must be smaller than maximum feature {hi:g} mm")
    if _num(res_um) and lo < res_um / 1000 - TOL:
        problems.append(f"minimum feature {lo:g} mm is finer than the {res_um:g} µm XY resolution")
    if problems:
        return CheckResult("C4", "error", "Feature limits: " + "; ".join(problems) + ".")
    return CheckResult("C4", "ok", "Feature limits are consistent with the manufacturing resolution.")


def _bulk_rise(power_w, flow_lpm, props):
    return power_w / (props["rho"] * flow_lpm / 60000.0 * props["cp"])


def _props(v):
    p = v.get("fluid_properties")
    if isinstance(p, dict) and _num(p.get("rho")) and _num(p.get("cp")) and p["rho"] > 0 and p["cp"] > 0:
        return p
    return None


def _power(v):
    if _num(v.get("total_power")):
        return v["total_power"]
    rows = _sources(v)
    return sum(r["power_W"] for r in rows) if rows else None


def _flows(v):
    flows = [f for f in (v.get("flow_sweep") or []) if _num(f) and f > 0]
    if not flows and _num(v.get("flow_nominal")) and v["flow_nominal"] > 0:
        flows = [v["flow_nominal"]]
    return flows


def _inlets(v):
    if v.get("sweep_mode") == "flow_sweep_at_nominal_temp" and _num(v.get("inlet_temp_nominal")):
        return [v["inlet_temp_nominal"]]
    temps = [t for t in (v.get("inlet_temp_sweep") or []) if _num(t)]
    if not temps and _num(v.get("inlet_temp_nominal")):
        temps = [v["inlet_temp_nominal"]]
    return temps


def _c5(v):
    props, power, flows, limit = _props(v), _power(v), _flows(v), v.get("max_coolant_rise")
    if props is None or power is None or not flows or not _num(limit):
        return None
    bad = [(f, _bulk_rise(power, f, props)) for f in sorted(flows)]
    bad = [(f, dt) for f, dt in bad if dt > limit + TOL]
    if bad:
        parts = ", ".join(f"{f:g} L/min → {dt:.1f} K" for f, dt in bad)
        return CheckResult("C5", "warning", f"Coolant rise exceeds the {limit:g} K limit at {parts} (ΔT = P / (ρ·V̇·cp), P = {power:g} W).")
    return CheckResult("C5", "ok", f"Coolant rise stays within {limit:g} K at every swept flow.")


def _c6(v):
    rule = v.get("dp_over_limit_rule")
    if rule in (None, ""):
        return CheckResult("C6", "info", "Pressure rule conflict: the inputs doc calls exceeding 4 psi a disqualification, but the slides score it as a 0.1 FoM/psi penalty. Ask the user which applies.")
    return CheckResult("C6", "ok", f"Over-limit pressure rule set to {rule}.")


def _c7(v):
    props, power, flows, inlets = _props(v), _power(v), _flows(v), _inlets(v)
    hbm, margin = v.get("hbm_tmax_limit"), v.get("temp_safety_margin")
    if props is None or power is None or not flows or not inlets or not _num(hbm) or not _num(margin):
        return None
    t_in, q = max(inlets), min(flows)
    t_out = t_in + _bulk_rise(power, q, props)
    threshold = hbm - margin
    headroom = threshold - t_out
    if headroom < C7_MIN_HEADROOM - TOL:
        return CheckResult("C7", "warning", f"At the worst point ({t_in:g} °C inlet, {q:g} L/min) the coolant outlet reaches {t_out:.1f} °C, leaving only {headroom:.1f} K of headroom below the HBM limit minus margin ({threshold:g} °C). The chip runs hotter than the coolant, so under {C7_MIN_HEADROOM:g} K of headroom this point is likely infeasible.")
    return CheckResult("C7", "ok", f"Worst-point coolant outlet {t_out:.1f} °C leaves {headroom:.1f} K of headroom below {threshold:g} °C ({t_in:g} °C inlet, {q:g} L/min).")

def _c8(v):
    rows = _sources(v)
    if rows is None:
        return None
    bad = []
    for i, r in enumerate(rows):
        area_cm2 = r["w"] * r["h"] / 100.0
        if area_cm2 <= 0:
            continue
        flux = r["power_W"] / area_cm2
        if not 1.0 <= flux <= 500.0:
            bad.append(f"{_name(r, i)} {flux:.3g} W/cm²")
    if bad:
        return CheckResult("C8", "warning", "Heat flux outside 1–500 W/cm² (check mm vs cm): " + ", ".join(bad) + ".")
    return CheckResult("C8", "ok", "All heat fluxes are between 1 and 500 W/cm².")


def run_checks(values: dict) -> list[CheckResult]:
    results = []
    for check in (_c1, _c2, _c3, _c4, _c5, _c6, _c7, _c8):
        try:
            result = check(values)
        except (TypeError, ValueError, KeyError, ZeroDivisionError):
            result = None
        if result is not None:
            results.append(result)
    return results
