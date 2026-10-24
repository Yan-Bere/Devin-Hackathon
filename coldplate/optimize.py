"""Candidate generation, parallel evaluation, Pareto selection, sweeps."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Callable, Optional

import numpy as np
from scipy.stats import qmc

from coldplate.evaluate import bulk_temperature_rise, evaluate
from coldplate.geometry import (
    ChannelDesign, FinZone, GeometryError, baseline_design,
    build_layout, derive_zone_bands,
)
from coldplate.spec import EngineInputs

_STEP_MM = 0.05


def _levels(inputs: EngineInputs, assumptions_out: Optional[list] = None) -> list[float]:
    lo = inputs.min_feature_mm
    hi = inputs.max_feature_mm
    if lo is None or hi is None:
        if assumptions_out is not None:
            assumptions_out.append(
                "manufacturing feature bounds missing; used default 0.1-1.0 mm "
                "candidate levels"
            )
        lo, hi = 0.1, 1.0
    n = int(round((hi - lo) / _STEP_MM)) + 1
    return [round(lo + i * _STEP_MM, 4) for i in range(max(n, 1))]


def generate_candidates(
    inputs: EngineInputs,
    *,
    n: int = 48,
    seed: int = 42,
    assumptions_out: Optional[list] = None,
) -> tuple[list[ChannelDesign], list[dict]]:
    """LHS over (shared fin thickness, per-zone-label channel width) on
    0.05 mm manufacturing levels. Returns (designs, rejected)."""
    levels = _levels(inputs, assumptions_out)
    bands = derive_zone_bands(inputs, inputs.flow_axis)
    labels = []
    for label, _, _ in bands:
        if label not in labels:
            labels.append(label)
    d = 1 + len(labels)
    base = baseline_design(inputs)
    openings = dict(
        inlet_opening_mm=inputs.inlet_opening_mm,
        outlet_opening_mm=inputs.outlet_opening_mm,
    )
    H = inputs.fin_height_max_mm  # fins must touch the gasket; no bypass modelled

    designs: list[ChannelDesign] = []
    rejected: list[dict] = []
    seen: set = set()

    def build(t: float, widths: list[float], cid: str) -> Optional[ChannelDesign]:
        zones = tuple(
            FinZone(label, v0, v1, t, widths[labels.index(label)])
            for label, v0, v1 in bands
        )
        d_ = ChannelDesign(
            design_id=cid, arrangement=inputs.arrangement,
            flow_axis=inputs.flow_axis, fin_height_mm=H, zones=zones,
            **openings,
        )
        try:
            build_layout(inputs, d_)
        except GeometryError as e:
            rejected.append({
                "candidate_id": cid,
                "params": {
                    "fin_thickness_mm": t,
                    "channel_width_by_zone_mm": dict(zip(labels, widths)),
                },
                "reason": str(e),
            })
            return None
        return d_

    # c000 = baseline when it builds
    k = 0
    try:
        build_layout(inputs, base)
        designs.append(base)
        k = 1
    except GeometryError:
        pass

    sampler = qmc.LatinHypercube(d, seed=seed)
    draws_needed = n - len(designs)
    made = 0
    total_draws = 0
    while made < draws_needed and total_draws < 10 * n:
        batch = sampler.random(n=max(draws_needed - made, 4))
        total_draws += len(batch)
        for row in batch:
            if made >= draws_needed:
                break
            idx = [min(int(u * len(levels)), len(levels) - 1) for u in row]
            key = tuple(idx)
            if key in seen:
                continue
            seen.add(key)
            t = levels[idx[0]]
            ws = [levels[i] for i in idx[1:]]
            cid = f"c{len(designs) + len(rejected) + 0:03d}"
            # keep candidate ids dense-ish: c001...
            cid = f"c{len(designs):03d}"
            dsg = build(t, ws, cid)
            if dsg is not None:
                designs.append(dsg)
                made += 1
    return designs, rejected


@dataclass
class CandidateEval:
    candidate_id: str
    design: ChannelDesign
    params: dict
    metrics: dict
    feasible: bool
    violations: list
    targets_met: dict
    worst_case: dict
    nondominated: bool = False
    rank: int = 0
    selected: bool = False
    role: Optional[str] = None
    status_label: str = "dominated"
    nominal_eval: object = None


@dataclass
class OptimizationResult:
    candidates: list
    rejected: list
    n_evaluated: int
    n_feasible: int
    n_nondominated: int
    front_candidate_ids: list
    all_infeasible: bool
    critical_type: Optional[str]
    seed: int
    warnings: list = field(default_factory=list)


def _violations(inputs: EngineInputs, ev) -> list:
    """One entry per offending component; keys = metric keys, metric units."""
    out = []
    for c in ev.thermal.components:
        hard = (inputs.limits_C or {}).get(c["type"])
        if hard is not None and c["max_C"] > hard:
            out.append({"constraint": f"{c['type'].lower()}_max_C",
                        "component": c["name"],
                        "value": round(c["max_C"], 3), "limit": hard})
    if inputs.dp_hard_Pa is not None and ev.hydraulics.dP_total_Pa > inputs.dp_hard_Pa:
        out.append({"constraint": "pressure_drop_kPa", "component": None,
                    "value": round(ev.hydraulics.dP_total_Pa / 1000.0, 3),
                    "limit": inputs.dp_hard_Pa / 1000.0})
    if inputs.max_outlet_rise_K is not None and ev.thermal.rise_K > inputs.max_outlet_rise_K:
        out.append({"constraint": "coolant_rise_K", "component": None,
                    "value": round(ev.thermal.rise_K, 3),
                    "limit": inputs.max_outlet_rise_K})
    return out


def _metrics(inputs: EngineInputs, ev, critical_type) -> dict:
    t = ev.thermal
    comps = {c["name"]: {"type": c["type"], "max_C": c["max_C"], "mean_C": c["mean_C"],
                         "R_th_K_per_W": c["R_th_K_per_W"], "power_W": c["power_W"]}
             for c in t.components}
    if critical_type:
        crit_vals = [c for c in t.components if c["type"] == critical_type]
        crit_T = max(c["max_C"] for c in crit_vals) if crit_vals else t.critical_max_C
    else:
        crit_T = t.critical_max_C
    gpus = {c["name"]: c["max_C"] for c in t.components if c["type"] == "GPU"}
    hbms = {c["name"]: c["max_C"] for c in t.components if c["type"] == "HBM"}
    margins = {c["name"]: (inputs.limits_C.get(c["type"]) - c["max_C"])
               for c in t.components if inputs.limits_C.get(c["type"]) is not None}
    worst_name = min(margins, key=margins.get) if margins else None
    return {
        "critical_temperature_C": crit_T,
        "hbm_max_C": max(hbms.values()) if hbms else None,
        "hbm_hottest": max(hbms, key=hbms.get) if hbms else None,
        "gpu_max_C": max(gpus.values()) if gpus else None,
        "gpu_hottest": max(gpus, key=gpus.get) if gpus else None,
        "pressure_drop_kPa": ev.hydraulics.dP_total_Pa / 1000.0,
        "pumping_power_W": ev.hydraulics.pumping_power_W,
        "coolant_outlet_C": t.outlet_C,
        "coolant_rise_K": t.rise_K,
        "worst_margin_K": margins.get(worst_name),
        "worst_margin_component": worst_name,
        "components": comps,
        "energy_residual": t.energy_residual,
    }


def _dominates(a: tuple, b: tuple) -> bool:
    return (a[0] <= b[0] and a[1] <= b[1]) and (a[0] < b[0] or a[1] < b[1])


def run_optimization(
    inputs: EngineInputs,
    *,
    n: int = 48,
    seed: int = 42,
    grid_mm: float = 0.5,
    progress: Optional[Callable] = None,
) -> OptimizationResult:
    assumptions: list[str] = []
    designs, rejected = generate_candidates(
        inputs, n=n, seed=seed, assumptions_out=assumptions
    )
    crit_type = inputs.critical_type
    flows = list(inputs.flow_sweep_Lpm or [])
    wc_flow = min(flows) if flows else None
    inlets = list(inputs.inlet_sweep_C or [])
    wc_inlet = max(inlets) if inlets else None

    cands: list[CandidateEval] = []
    for k, des in enumerate(designs):
        ev = evaluate(inputs, des, grid_mm=grid_mm)
        viol = _violations(inputs, ev)
        # worst case: min flow (full solve at nominal inlet) + inlet shift
        if wc_flow is not None and wc_flow != inputs.flow_Lpm:
            ev_wc = evaluate(inputs, des, flow_Lpm=wc_flow, grid_mm=grid_mm)
        else:
            ev_wc = ev
        d_in = (wc_inlet - inputs.inlet_C) if wc_inlet is not None else 0.0
        wc_gpu = (ev_wc.thermal.gpu_max_C or 0) + d_in
        wc_hbm = (ev_wc.thermal.hbm_max_C or 0) + d_in
        wc = {
            "flow_Lpm": wc_flow if wc_flow is not None else inputs.flow_Lpm,
            "inlet_C": wc_inlet if wc_inlet is not None else inputs.inlet_C,
            "gpu_max_C": wc_gpu, "hbm_max_C": wc_hbm,
            "coolant_rise_K": ev_wc.thermal.rise_K,
            "margin_ok": True,
            "failures": [],
        }
        for c in ev_wc.thermal.components:
            lim = (inputs.limits_C or {}).get(c["type"])
            if lim is not None and c["max_C"] + d_in > lim:
                wc["failures"].append(
                    {"component": c["name"], "max_C": c["max_C"] + d_in, "limit_C": lim}
                )
        wc["margin_ok"] = not wc["failures"]
        tgts = {}
        for c in ev.thermal.components:
            t_lim = (inputs.targets_C or {}).get(c["type"])
            if t_lim is not None:
                tgts[c["name"]] = c["max_C"] <= t_lim
        cands.append(CandidateEval(
            candidate_id=des.design_id, design=des,
            params=_params(inputs, des),
            metrics=_metrics(inputs, ev, crit_type),
            feasible=not viol, violations=viol, targets_met=tgts,
            worst_case=wc, nominal_eval=ev,
        ))
        if progress:
            progress(k + 1, len(designs), f"evaluated {k + 1}/{len(designs)}")

    feas = [c for c in cands if c.feasible]
    xy = [(c.metrics["pressure_drop_kPa"], c.metrics["critical_temperature_C"]) for c in feas]
    nd = [i for i in range(len(feas))
          if not any(i != j and _dominates(xy[j], xy[i]) for j in range(len(feas)))]
    for i in nd:
        feas[i].nondominated = True
    # fast nondominated-sort ranks among feasible
    cur = [i for i in range(len(feas))]
    rank = 0
    remaining = set(cur)
    while remaining:
        front = [i for i in remaining
                 if not any(j != i and j in remaining and _dominates(xy[j], xy[i])
                            for j in remaining)]
        for i in front:
            feas[i].rank = rank
        remaining -= set(front)
        rank += 1
    for c in cands:
        c.status_label = (
            "nondominated" if c.nondominated
            else ("dominated" if c.feasible else "infeasible")
        )
    front_ids = [c.candidate_id for c in sorted(
        (c for c in cands if c.nondominated),
        key=lambda c: c.metrics["pressure_drop_kPa"])]
    return OptimizationResult(
        candidates=cands, rejected=rejected,
        n_evaluated=len(cands), n_feasible=len(feas),
        n_nondominated=len(nd), front_candidate_ids=front_ids,
        all_infeasible=not feas, critical_type=crit_type, seed=seed,
        warnings=assumptions,
    )


def _params(inputs: EngineInputs, des: ChannelDesign) -> dict:
    layout = build_layout(inputs, des)
    widths = {}
    for ch in layout.channels:
        widths.setdefault(ch["zone"], ch["width_mm"])
    return {
        "arrangement": des.arrangement, "flow_axis": des.flow_axis,
        "fin_height_mm": des.fin_height_mm,
        "fin_thickness_mm": des.zones[0].fin_thickness_mm if des.zones else None,
        "channel_width_by_zone_mm": {z.label: z.channel_width_mm for z in des.zones},
        "zones": [
            {"label": z.label, "v_start_mm": z.v_start_mm, "v_end_mm": z.v_end_mm,
             "channel_width_mm": z.channel_width_mm,
             "actual_channel_width_mm": widths.get(z.label),
             "fin_thickness_mm": z.fin_thickness_mm,
             "n_channels": sum(1 for c in layout.channels if c["zone_index"] == zi)}
            for zi, z in enumerate(des.zones)
        ],
        "n_channels": len(layout.channels), "n_fins": len(layout.fins),
        "inlet_opening_mm": des.inlet_opening_mm,
        "outlet_opening_mm": des.outlet_opening_mm,
    }


def select_designs(result: OptimizationResult) -> list:
    """Five designs: pressure/cooling focused, knee, leanings, then fills."""
    feas = [c for c in result.candidates if c.nondominated]
    picked: list = []
    if feas:
        xs = np.array([c.metrics["pressure_drop_kPa"] for c in feas])
        ys = np.array([c.metrics["critical_temperature_C"] for c in feas])
        xr = max(xs.max() - xs.min(), 1e-9)
        yr = max(ys.max() - ys.min(), 1e-9)
        order = np.argsort(xs)
        feas_s = [feas[i] for i in order]
        xn = (xs[order] - xs.min()) / xr
        yn = (ys[order] - ys.min()) / yr

        def take(c, role):
            if c in picked:
                return c
            c.selected = True
            c.role = role
            picked.append(c)
            return c

        pf = take(feas_s[0], "pressure_focused")
        if len(feas_s) > 1:
            cf = take(feas_s[-1], "cooling_focused")
        if len(feas_s) > 2:
            d_ut = np.sqrt(xn**2 + yn**2)
            knee_i = int(np.argmin(d_ut))
            # skip near-duplicates of already-picked
            def is_dup(i):
                return any(
                    abs(xn[i] - xn[j]) < 0.01 and abs(yn[i] - yn[j]) < 0.01
                    for j in [feas_s.index(p) for p in picked if p in feas_s]
                )
            while knee_i < len(feas_s) and is_dup(knee_i):
                d_ut[knee_i] = np.inf
                knee_i = int(np.argmin(d_ut))
            bal = take(feas_s[knee_i], "balanced")
            # arc-length midpoints pf->bal and bal->cf along the front
            bi = feas_s.index(bal)
            seg1 = feas_s[:bi + 1]
            seg2 = feas_s[bi:]
            def mid_of(seg):
                if len(seg) < 2:
                    return seg[0]
                idx = [feas_s.index(c) for c in seg]
                pts = np.column_stack([xn[idx], yn[idx]])
                seglen = np.cumsum(np.r_[0.0, np.linalg.norm(np.diff(pts, axis=0), axis=1)])
                target = seglen[-1] / 2.0
                return seg[int(np.argmin(np.abs(seglen - target)))]
            for seg, role in ((seg1, "pressure_leaning"), (seg2, "cooling_leaning")):
                cand = mid_of(seg)
                if cand in picked:
                    # nearest unpicked along segment
                    alts = [c for c in seg if c not in picked]
                    cand = alts[0] if alts else cand
                if cand not in picked:
                    take(cand, role)
    # fill from dominated feasible (by rank then distance to front), then infeasible
    if len(picked) < 5:
        dom = [c for c in result.candidates if c.feasible and not c.selected]
        dom.sort(key=lambda c: (c.rank, c.metrics["pressure_drop_kPa"]))
        for c in dom:
            if len(picked) >= 5:
                break
            c.selected = True
            c.role = "dominated"
            picked.append(c)
    if len(picked) < 5:
        infeas = [c for c in result.candidates if not c.feasible and not c.selected]
        def viol_sum(c):
            tot = 0.0
            for v in c.violations:
                lim = v["limit"] or 1.0
                tot += (v["value"] - lim) / lim
            return tot
        infeas.sort(key=viol_sum)
        for c in infeas:
            if len(picked) >= 5:
                break
            c.selected = True
            c.role = "infeasible"
            picked.append(c)
    picked.sort(key=lambda c: c.metrics["pressure_drop_kPa"])
    return picked[:5]


def sweep_design(inputs: EngineInputs, design: ChannelDesign, grid_mm: float = 0.5) -> dict:
    """Sweeps per the contract: flows x inlet temperatures, acceptance block."""
    nominal_f = inputs.flow_Lpm
    nominal_t = inputs.inlet_C
    flows = sorted(set([nominal_f] + list(inputs.flow_sweep_Lpm or [])))
    inlets = sorted(set([nominal_t] + list(inputs.inlet_sweep_C or [])))
    P = sum(s.power_W for s in inputs.sources)
    points = []
    for f in flows:
        ev = evaluate(inputs, design, flow_Lpm=f, grid_mm=grid_mm)
        rise = bulk_temperature_rise(P, f, inputs.rho_kg_m3, inputs.cp_J_kgK)
        by_in = []
        for tin in inlets:
            shift = tin - nominal_t
            gpu = (ev.thermal.gpu_max_C or 0) + shift
            hbm = (ev.thermal.hbm_max_C or 0) + shift
            crit = max(
                [c["max_C"] + shift for c in ev.thermal.components
                 if inputs.critical_type is None or c["type"] == inputs.critical_type]
                or [0]
            )
            ok = True
            for c in ev.thermal.components:
                lim = (inputs.limits_C or {}).get(c["type"])
                if lim is not None and c["max_C"] + shift > lim:
                    ok = False
            by_in.append({
                "inlet_C": tin, "gpu_max_C": gpu, "hbm_max_C": hbm,
                "critical_temperature_C": crit, "hard_ok": ok,
                "margin_ok": ok,
            })
        points.append({
            "flow_Lpm": f,
            "pressure_drop_kPa": ev.hydraulics.dP_total_Pa / 1000.0,
            "pumping_power_W": ev.hydraulics.pumping_power_W,
            "coolant_rise_K": rise,
            "rise_ok": (inputs.max_outlet_rise_K is None
                        or rise <= inputs.max_outlet_rise_K),
            "by_inlet": by_in,
        })
    # acceptance
    margin = inputs.temperature_margin_K or 0.0
    thresholds = {tp: lim - margin for tp, lim in (inputs.limits_C or {}).items()}
    # document rule: worst sweep point = highest inlet temp, LOWEST flow
    worst_p, worst_bi = points[0], points[0]["by_inlet"][-1]
    failures = []
    for tp, thr in thresholds.items():
        key = f"{tp.lower()}_max_C"
        if worst_bi.get(key, worst_bi.get("critical_temperature_C", 0)) > thr:
            failures.append({"constraint": key, "limit_C": thr})
    hi = points[-1]
    dp_hi_ok = (inputs.dp_acceptance_Pa is None
                or hi["pressure_drop_kPa"] * 1000 <= inputs.dp_acceptance_Pa)
    rise_fails = [p["flow_Lpm"] for p in points if not p["rise_ok"]]
    acc = {
        "worst_point": {
            "flow_Lpm": worst_p["flow_Lpm"], "inlet_C": worst_bi["inlet_C"],
            "gpu_max_C": worst_bi["gpu_max_C"], "hbm_max_C": worst_bi["hbm_max_C"],
            "thresholds_C": thresholds, "failures": failures,
            "ok": not failures,
        },
        "pressure_at_highest_flow": {
            "flow_Lpm": hi["flow_Lpm"], "dP_kPa": hi["pressure_drop_kPa"],
            "limit_kPa": (inputs.dp_acceptance_Pa or 0) / 1000.0,
            "ok": dp_hi_ok,
        },
        "outlet_rise": {
            "by_flow_K": {str(p["flow_Lpm"]): p["coolant_rise_K"] for p in points},
            "limit_K": inputs.max_outlet_rise_K,
            "geometry_independent": True,
        },
    }
    acc["accepted"] = not failures and dp_hi_ok and not rise_fails
    if acc["accepted"]:
        acc["summary"] = "Accepted: all sweep points satisfy the stated rules."
    else:
        parts = []
        if rise_fails:
            parts.append(
                f"outlet rise exceeds {inputs.max_outlet_rise_K:g} K at "
                f"{' and '.join(f'{f:g}' for f in rise_fails)} L/min for any "
                f"geometry (energy balance)"
            )
        if failures:
            parts.append("worst-point temperature margin violated")
        else:
            parts.append("worst-point temperature margin OK")
        parts.append(
            f"ΔP at {hi['flow_Lpm']:g} L/min {hi['pressure_drop_kPa']:.2f} kPa "
            f"{'≤' if dp_hi_ok else '>'} "
            f"{((inputs.dp_acceptance_Pa or 0) / 1000.0):g} kPa"
        )
        acc["summary"] = "Not accepted under the stated rules: " + "; ".join(parts) + "."
    return {"flows_Lpm": flows, "inlet_temperatures_C": inlets,
            "points": points, "acceptance": acc}


def requirement_conflicts(inputs: EngineInputs) -> list[str]:
    """Geometry-independent impossibilities from the bulk energy balance."""
    out = []
    if inputs.max_outlet_rise_K is None:
        return out
    P = sum(s.power_W for s in inputs.sources)
    flows = sorted(set([inputs.flow_Lpm] + list(inputs.flow_sweep_Lpm or [])))
    for f in flows:
        rise = bulk_temperature_rise(P, f, inputs.rho_kg_m3, inputs.cp_J_kgK)
        if rise > inputs.max_outlet_rise_K + 1e-9:
            f_min = P / (inputs.rho_kg_m3 * inputs.cp_J_kgK * inputs.max_outlet_rise_K) * 60e3
            out.append(
                f"At {f:g} L/min the bulk coolant rise is {rise:.2f} K, above the "
                f"{inputs.max_outlet_rise_K:g} K limit, for any fin geometry "
                f"(energy balance P/(rho*cp*Q)); minimum compliant flow is "
                f"{f_min:.2f} L/min."
            )
    return out
