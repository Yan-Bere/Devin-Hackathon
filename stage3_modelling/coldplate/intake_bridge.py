"""Render the chat's finalized fields into a requirements markdown document.

final_doc: {"session_id", "finalized", "schema_version",
            "fields": {id: {"value": ..., ...}}}.  Null fields are omitted;
values are never invented.
"""

from __future__ import annotations

_FLOW_SENTENCES = {
    "split_flow_edges_to_center": (
        "**Flow path:** split flow. Coolant enters along the two outer edges, "
        "flows through the fins toward the centerline, and exits through the "
        "center outlet over the GPU hotspots."),
    "center_in_edges_out": (
        "**Flow path:** split flow. Coolant enters at the center, flows "
        "through the fins toward the edges, and exits through the two outer "
        "edge outlets."),
    "cross_flow": (
        "**Flow path:** straight. Coolant enters at one edge and exits at "
        "the opposite edge, crossing the fins in one direction."),
    "custom": "**Flow path:** custom (see notes).",
}

_OUTPUT_MAP = {
    "component_temps": "Max and mean temperature for each component",
    "thermal_resistance": "Thermal resistance for each component: R_th = (T_max - T_inlet) / P",
    "pressure_drop": "Pressure drop at every flow point",
    "pumping_power": "Pumping power = dP x Q",
    "chip_plane_field": "Temperature contour on the chip plane",
    "velocity_field": "Velocity field in the fin layer",
}


def _v(fields: dict, fid: str, default=None):
    f = fields.get(fid) or {}
    v = f.get("value", f.get("default", default))
    return default if v is None else v


def render_requirements_markdown(final_doc: dict) -> str:
    fields = final_doc.get("fields") or {}
    L: list[str] = ["# Cold Plate: Simulation Inputs", ""]
    hs = _v(fields, "heat_sources", []) or []
    if hs:
        gpu_n = sum(1 for h in hs if (h.get("type") or "").upper() == "GPU")
        hbm_n = sum(1 for h in hs if (h.get("type") or "").upper() == "HBM")
        L.append(f"Package: {gpu_n} GPUs + {hbm_n} HBM stacks.")
    tot = _v(fields, "total_power")
    if tot is not None:
        L.append(f"Total power: **{tot:g} W**.")
    L.append("")

    # --- section 1: requirements -------------------------------------------
    L += ["## 1. Requirements", "", "| Item | Hard | Target | Stretch |",
          "|---|---|---|---|"]

    def _r(label, hid, tid, sid):
        h_, t_, s_ = _v(fields, hid), _v(fields, tid), _v(fields, sid)
        L.append(f"| {label} | {h_:g} °C | {t_:g} °C | {s_:g} °C |"
                 if t_ is not None else f"| {label} | {h_:g} °C | | |")

    if _v(fields, "gpu_tmax_limit") is not None:
        _r("GPU max temp", "gpu_tmax_limit", "gpu_t_target", "gpu_t_stretch")
    if _v(fields, "hbm_tmax_limit") is not None:
        _r("HBM max temp", "hbm_tmax_limit", "hbm_t_target", "hbm_t_stretch")
    if _v(fields, "dp_hard_limit") is not None:
        dp, dpt, dps = _v(fields, "dp_hard_limit"), _v(fields, "dp_target"), _v(fields, "dp_stretch")
        L.append(f"| Pressure drop | {dp:g} kPa | {dpt:g} kPa | {dps:g} kPa |")
    if _v(fields, "max_coolant_rise") is not None:
        L.append(f"| Coolant rise | {_v(fields, 'max_coolant_rise'):g} K | | |")
    if _v(fields, "temp_safety_margin") is not None:
        L.append(f"| Safety margin | {_v(fields, 'temp_safety_margin'):g} K below hard limit | | |")
    if _v(fields, "dp_design_cap_at_max_flow") is not None:
        L.append(f"| Pressure at max flow | {_v(fields, 'dp_design_cap_at_max_flow'):g} kPa | | |")
    L.append("")

    # --- section 2: heat sources -------------------------------------------
    die = _v(fields, "die_region_size")
    L += ["## 2. Heat sources", ""]
    if die:
        L.append(f"Source coordinates are in the die-region frame "
                 f"({die[0]:g} x {die[1]:g} mm; origin at its lower-left corner).")
    L += ["", "| Name | Type | x0 (mm) | y0 (mm) | w (mm) | h (mm) | Power (W) | Power share (%) |",
          "|---|---|---|---|---|---|---|---|"]
    for h in hs:
        share = 100.0 * (h.get("power_W") or 0) / tot if tot else ""
        share_s = f"{share:.1f}" if isinstance(share, float) else ""
        L.append(f"| {h.get('name','?')} | {h.get('type','?')} | {h.get('x0',0)} | "
                 f"{h.get('y0',0)} | {h.get('w',0)} | {h.get('h',0)} | "
                 f"{h.get('power_W',0)} | {share_s} |")
    if _v(fields, "power_map_mode") == "uniform_per_source":
        L.append("")
        L.append("Heat is spread evenly over each source (uniform per-source power).")
    elif _v(fields, "power_map_mode") == "grid_file":
        f_ = _v(fields, "power_map_file")
        pitch = _v(fields, "power_map_pitch")
        nm = f_.get("name") if isinstance(f_, dict) else f_
        L.append("")
        L.append(f"Non-uniform power map from file `{nm or 'power_map.csv'}` "
                 f"({pitch:g} mm grid, W/mm^2; first row and column at cell centers).")
    L.append("")

    # --- section 3: cold plate ---------------------------------------------
    L += ["## 3. Cold plate", "", "| Item | Value |", "|---|---|"]
    bp = _v(fields, "base_plate_size")
    bm = _v(fields, "base_material") or {}
    if bp:
        L.append(f"| Base plate | {bp[0]:g} x {bp[1]:g} x {bp[2]:g} mm"
                 + (f", {bm.get('name','')} (k = {bm.get('k')} W/m·K)" if bm else "")
                 + ", centered on package |")
    fds = _v(fields, "fin_design_space")
    if fds:
        L.append(f"| Fin design space | {fds[0]:g} x {fds[1]:g} x {fds[2]:g} mm, centered on package |")
    if _v(fields, "min_feature") is not None:
        L.append(f"| Min feature | {_v(fields, 'min_feature'):g} mm |")
    if _v(fields, "max_feature") is not None:
        L.append(f"| Max feature | {_v(fields, 'max_feature'):g} mm |")
    if _v(fields, "resolution_xy") is not None:
        L.append(f"| Resolution | {_v(fields,'resolution_xy')} um (XY), "
                 f"{_v(fields,'resolution_z','-')} um (Z) |")
    if _v(fields, "min_overhang_angle") is not None:
        L.append(f"| Min overhang angle | {_v(fields, 'min_overhang_angle'):g} deg |")
    g = _v(fields, "gasket") or {}
    if g:
        L.append(f"| Gasket | {g.get('material','')}, {g.get('thickness','?')} mm thick"
                 + (f", {g.get('notes')}" if g.get("notes") else "") + " |")
    tr, tt = _v(fields, "tim_resistance"), _v(fields, "tim_thickness")
    if tr is not None:
        L.append(f"| TIM | R'' = {tr:g} cm2·K/W, {tt:g} mm thick |" if tt else
                 f"| TIM | R'' = {tr:g} cm2·K/W |")
    L.append("")
    L.append(_FLOW_SENTENCES.get(_v(fields, "flow_configuration", "custom"),
                                 _FLOW_SENTENCES["custom"]))
    notes = _v(fields, "flow_path_notes")
    if notes:
        L.append(f"Flow-path notes: {notes}")
    L.append("")

    # --- section 4: coolant --------------------------------------------------
    L += ["## 4. Coolant", "", "| Property | Value |", "|---|---|"]
    fl = _v(fields, "fluid")
    if fl:
        L.append(f"| Fluid | {fl} |")
    fp = _v(fields, "fluid_properties") or {}
    for k, label, u in (("rho", "Density", "kg/m^3"), ("cp", "cp", "J/kg·K"),
                        ("mu", "Viscosity", "Pa·s"), ("k", "Thermal conductivity", "W/m·K")):
        if fp.get(k) is not None:
            L.append(f"| {label} | {fp[k]:g} {u} |")
    tin = _v(fields, "inlet_temp_nominal")
    if tin is not None:
        L.append(f"| Inlet temp, nominal | {tin:g} degC |")
    tins = _v(fields, "inlet_temp_sweep")
    if tins:
        L.append(f"| Inlet temp sweep | {', '.join(f'{t:g}' for t in tins)} degC |")
    flo = _v(fields, "flow_nominal")
    if flo is not None:
        L.append(f"| Flow, nominal | {flo:g} L/min |")
    if _v(fields, "flow_sweep"):
        L.append("")
        L.append("### Flow sweep")
        L.append("")
        L.append("| Flow (L/min) |")
        L.append("|---|")
        for f_ in _v(fields, "flow_sweep"):
            L.append(f"| {f_:g} |")
    L.append("")

    # --- 5/6: outputs + first test case --------------------------------------
    req = _v(fields, "required_outputs") or []
    if req:
        L += ["## 5. Required outputs", ""]
        for r in req:
            L.append(f"- {_OUTPUT_MAP.get(r, str(r).replace('_', ' '))}")
        L.append("")
    bl = _v(fields, "baseline_design")
    if bl:
        t_ = bl.get("fin_thickness", 0.3)
        w_ = bl.get("channel_width", 0.3)
        h_ = bl.get("fin_height", 2.0)
        L += ["## 6. First test case", "",
              "Run a plain straight-fin plate first to check the solver before optimizing:",
              f"- {t_:g} mm fins, {w_:g} mm gaps, {h_:g} mm tall", ""]
    return "\n".join(L)
