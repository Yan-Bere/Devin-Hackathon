"""Reduced-order split-flow thermal and pressure model."""

import math


PSI_PER_KPA = 1 / 6.894757293168
SLICE_MM = 0.5


def _heat_in_interval(sources, lower_y, upper_y):
    total = 0.0
    for source in sources:
        overlap = max(
            0.0,
            min(upper_y, source["y0"] + source["h"])
            - max(lower_y, source["y0"]),
        )
        if overlap:
            total += source["power_W"] * overlap / source["h"]
    return total


def _temperature_profile(sources, start_y, end_y, inlet_temp_c, mass_cp):
    direction = 1.0 if end_y > start_y else -1.0
    distance = abs(end_y - start_y)
    steps = math.ceil(distance / SLICE_MM)
    segments = []
    temperature = inlet_temp_c
    position = start_y
    for index in range(steps):
        next_position = start_y + direction * min((index + 1) * SLICE_MM, distance)
        segments.append((position, next_position, temperature))
        temperature += (
            _heat_in_interval(
                sources,
                min(position, next_position),
                max(position, next_position),
            )
            / mass_cp
        )
        position = next_position
    return segments, temperature - inlet_temp_c


def _temperature_at(sources, segments, y, mass_cp):
    for start_y, end_y, start_temp in segments:
        if min(start_y, end_y) - 1e-9 <= y <= max(start_y, end_y) + 1e-9:
            heat = _heat_in_interval(
                sources,
                min(start_y, y),
                max(start_y, y),
            )
            return start_temp + heat / mass_cp
    raise ValueError(f"y={y} lies outside the coolant path")


def evaluate_point(values, t_f_mm, w_c_mm, flow_lpm, inlet_temp_c):
    """Evaluate one fin design at one flow and inlet temperature."""
    if t_f_mm <= 0 or w_c_mm <= 0 or flow_lpm <= 0:
        raise ValueError("fin thickness, channel width, and flow must be positive")

    _, die_y_mm = values["die_region_size"]
    fin_space_x_mm, fin_space_y_mm, height_mm = values["fin_design_space"]
    base_thickness_mm = values["base_plate_size"][2]
    base_conductivity = values["base_material"]["k"]
    rho = values["fluid_properties"]["rho"]
    cp = values["fluid_properties"]["cp"]
    mu = values["fluid_properties"]["mu"]
    fluid_k = values["fluid_properties"]["k"]
    sources = values["heat_sources"]
    fin_count = math.floor(fin_space_x_mm / (t_f_mm + w_c_mm))
    if fin_count <= 0:
        raise ValueError("design has no fins")

    t_f = t_f_mm / 1000
    w_c = w_c_mm / 1000
    height = height_mm / 1000
    base_thickness = base_thickness_mm / 1000
    hydraulic_diameter = 2 * w_c * height / (w_c + height)
    alpha = min(w_c, height) / max(w_c, height)
    f_re = 96 * (
        1
        - 1.3553 * alpha
        + 1.9467 * alpha**2
        - 1.7012 * alpha**3
        + 0.9564 * alpha**4
        - 0.2537 * alpha**5
    )
    nusselt = 8.235 * (
        1
        - 2.0421 * alpha
        + 3.0853 * alpha**2
        - 2.4765 * alpha**3
        + 1.0578 * alpha**4
        - 0.1861 * alpha**5
    )
    h = nusselt * fluid_k / hydraulic_diameter
    m = math.sqrt(2 * h / (base_conductivity * t_f))
    eta = math.tanh(m * height) / (m * height)
    r_conv = (t_f + w_c) / (h * (w_c + 2 * eta * height))
    r_tim = values["tim_resistance"] * 1e-4
    r_base = base_thickness / base_conductivity
    r_total = r_tim + r_base + r_conv

    flow_m3_s = flow_lpm * 1e-3 / 60
    flow_per_channel = flow_m3_s / (2 * fin_count)
    velocity = flow_per_channel / (w_c * height)
    reynolds = rho * velocity * hydraulic_diameter / mu
    length = fin_space_y_mm / 2000
    dynamic_pressure = rho * velocity**2 / 2
    pressure_pa = (
        (f_re / reynolds) * (length / hydraulic_diameter) * dynamic_pressure
        + 2.5 * dynamic_pressure
    )
    delta_p_kpa = pressure_pa / 1000
    delta_p_psi = delta_p_kpa * PSI_PER_KPA
    pumping_power_w = pressure_pa * flow_m3_s

    center_y = die_y_mm / 2
    mass_cp = rho * flow_m3_s / 2 * cp
    bottom_profile, bottom_rise = _temperature_profile(
        sources, 0.0, center_y, inlet_temp_c, mass_cp
    )
    top_profile, top_rise = _temperature_profile(
        sources, die_y_mm, center_y, inlet_temp_c, mass_cp
    )
    profiles = {
        "bottom": bottom_profile,
        "top": top_profile,
    }
    outlet_rise = max(bottom_rise, top_rise)

    component_temperatures = {}
    for source in sources:
        source_y0 = source["y0"]
        source_y1 = source_y0 + source["h"]
        downstream_temperatures = []
        if source_y0 < center_y:
            downstream_y = min(source_y1, center_y)
            downstream_temperatures.append(
                _temperature_at(
                    sources, bottom_profile, downstream_y, mass_cp
                )
            )
        if source_y1 > center_y:
            downstream_y = max(source_y0, center_y)
            downstream_temperatures.append(
                _temperature_at(
                    sources, top_profile, downstream_y, mass_cp
                )
            )
        source_center_y = source_y0 + source["h"] / 2
        if math.isclose(source_center_y, center_y, abs_tol=1e-9):
            center_fluid_temp = sum(
                _temperature_at(sources, profiles[side], center_y, mass_cp)
                for side in ("bottom", "top")
            ) / 2
        elif source_center_y < center_y:
            center_fluid_temp = _temperature_at(
                sources, bottom_profile, source_center_y, mass_cp
            )
        else:
            center_fluid_temp = _temperature_at(
                sources, top_profile, source_center_y, mass_cp
            )
        q_source = source["power_W"] / (
            source["w"] * source["h"] * 1e-6
        )
        temperature_offset = q_source * r_total
        component_temperatures[source["name"]] = {
            "type": source["type"],
            "T_max_C": max(downstream_temperatures) + temperature_offset,
            "T_mean_C": center_fluid_temp + temperature_offset,
        }

    gpu = [
        item for item in component_temperatures.values() if item["type"] == "GPU"
    ]
    hbm = [
        item for item in component_temperatures.values() if item["type"] == "HBM"
    ]
    if not gpu or not hbm:
        raise ValueError("heat_sources must include GPU and HBM components")

    return {
        "flow_L_min": flow_lpm,
        "inlet_temp_C": inlet_temp_c,
        "fin_thickness_mm": t_f_mm,
        "gap_mm": w_c_mm,
        "fin_count": fin_count,
        "components": component_temperatures,
        "max_gpu_C": max(item["T_max_C"] for item in gpu),
        "max_gpu_mean_C": max(item["T_mean_C"] for item in gpu),
        "max_hbm_C": max(item["T_max_C"] for item in hbm),
        "max_hbm_mean_C": max(item["T_mean_C"] for item in hbm),
        "delta_p_kPa": delta_p_kpa,
        "delta_p_psi": delta_p_psi,
        "pumping_power_W": pumping_power_w,
        "coolant_outlet_rise_K": outlet_rise,
        "Re": reynolds,
        "laminar": reynolds < 2300,
        "hydraulic_diameter_m": hydraulic_diameter,
        "R_conv_m2K_W": r_conv,
    }
