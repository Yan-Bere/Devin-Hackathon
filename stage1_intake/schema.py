"""Canonical intake schema and field validation."""

from dataclasses import dataclass
import math
from typing import Any, Callable

import units


GROUPS = {
    1: "Limits and scoring",
    2: "Package and heat sources",
    3: "Cold plate geometry and manufacturing",
    4: "Flow path",
    5: "Coolant and operating points",
    6: "Design exploration",
}


@dataclass(frozen=True)
class Field:
    id: str
    group: int
    label: str
    type: str
    quantity: str | None
    required: bool | Callable[[dict], bool]
    default: Any = None
    is_assumption: bool = False
    min: float | None = None
    max: float | None = None
    choices: tuple | None = None
    help: str = ""
    subfields: dict[str, str | None] | None = None

    @property
    def unit(self):
        return units.QUANTITIES.get(self.quantity) if self.quantity else None


def _field(
    field_id, group, label, kind, quantity=None, required=True, default=None,
    is_assumption=False, min_value=None, max_value=None, choices=None, help_text="",
    subfields=None,
):
    return Field(
        id=field_id,
        group=group,
        label=label,
        type=kind,
        quantity=quantity,
        required=required,
        default=default,
        is_assumption=is_assumption,
        min=min_value,
        max=max_value,
        choices=tuple(choices) if choices is not None else None,
        help=help_text,
        subfields=subfields,
    )


_HEAT_SOURCES = [
    {"name": "GPU1", "type": "GPU", "x0": 0.00, "y0": 10.15, "w": 26.0, "h": 30.0, "power_W": 554.4},
    {"name": "GPU2", "type": "GPU", "x0": 26.15, "y0": 10.15, "w": 26.0, "h": 30.0, "power_W": 554.4},
    {"name": "H1", "type": "HBM", "x0": 0.00, "y0": 40.30, "w": 12.0, "h": 10.0, "power_W": 48.0},
    {"name": "H2", "type": "HBM", "x0": 14.00, "y0": 40.30, "w": 12.0, "h": 10.0, "power_W": 48.0},
    {"name": "H3", "type": "HBM", "x0": 26.15, "y0": 40.30, "w": 12.0, "h": 10.0, "power_W": 48.0},
    {"name": "H4", "type": "HBM", "x0": 40.15, "y0": 40.30, "w": 12.0, "h": 10.0, "power_W": 48.0},
    {"name": "H5", "type": "HBM", "x0": 0.00, "y0": 0.00, "w": 12.0, "h": 10.0, "power_W": 48.0},
    {"name": "H6", "type": "HBM", "x0": 14.00, "y0": 0.00, "w": 12.0, "h": 10.0, "power_W": 48.0},
    {"name": "H7", "type": "HBM", "x0": 26.15, "y0": 0.00, "w": 12.0, "h": 10.0, "power_W": 48.0},
    {"name": "H8", "type": "HBM", "x0": 40.15, "y0": 0.00, "w": 12.0, "h": 10.0, "power_W": 48.0},
]

_OUTPUT_CHOICES = (
    "component_tmax_tmean",
    "component_rth",
    "dp_per_flow",
    "pumping_power",
    "chip_plane_t_contour",
    "fin_layer_velocity_field",
)

FIELDS = [
    _field("dp_hard_limit", 1, "Pressure-drop hard limit", "float", "pressure", default=27.6, min_value=0, max_value=500, help_text="The pressure-drop hard limit is 4.0 psi (27.6 kPa), above which a design is disqualified."),
    _field("dp_over_limit_rule", 1, "Over-limit scoring rule", "enum", required=True, choices=("disqualify", "penalty"), help_text="The source notes say to disqualify over-limit designs, while the slides specify a 0.1 FoM-per-psi penalty."),
    _field("dp_penalty_per_psi", 1, "Pressure penalty per psi", "float", "penalty", required=lambda v: v.get("dp_over_limit_rule") == "penalty", default=0.1, min_value=0, max_value=100, help_text="The slides specify a 0.1 FoM-per-psi penalty when pressure drop exceeds the limit."),
    _field("gpu_tmax_limit", 1, "GPU maximum temperature limit", "float", "temperature", default=100, min_value=0, max_value=200, help_text="Reject a design if any GPU exceeds the 100 °C hard limit."),
    _field("hbm_tmax_limit", 1, "HBM maximum temperature limit", "float", "temperature", default=70, min_value=0, max_value=200, help_text="Reject a design if any HBM stack exceeds the 70 °C hard limit."),
    _field("gpu_t_target", 1, "GPU temperature target", "float", "temperature", required=False, default=85, min_value=0, max_value=200, help_text="The GPU design target is no more than 85 °C."),
    _field("hbm_t_target", 1, "HBM temperature target", "float", "temperature", required=False, default=63, min_value=0, max_value=200, help_text="The HBM design target is no more than 63 °C."),
    _field("dp_target", 1, "Pressure-drop target", "float", "pressure", required=False, default=13.8, min_value=0, max_value=500, help_text="The pressure-drop design target is no more than 13.8 kPa (2.0 psi)."),
    _field("dp_stretch", 1, "Pressure-drop stretch goal", "float", "pressure", required=False, default=6.9, min_value=0, max_value=500, help_text="The pressure-drop stretch goal is no more than 6.9 kPa (1.0 psi)."),
    _field("gpu_t_stretch", 1, "GPU temperature stretch goal", "float", "temperature", required=False, default=80, min_value=0, max_value=200, help_text="The GPU temperature stretch goal is no more than 80 °C."),
    _field("hbm_t_stretch", 1, "HBM temperature stretch goal", "float", "temperature", required=False, default=60, min_value=0, max_value=200, help_text="The HBM temperature stretch goal is no more than 60 °C."),
    _field("temp_safety_margin", 1, "Temperature safety margin", "float", "temperature_difference", default=5, min_value=0, max_value=50, help_text="Reject a design within 5 K of either temperature hard limit at the worst sweep point."),
    _field("dp_design_cap_at_max_flow", 1, "Pressure cap at maximum flow", "float", "pressure", default=24.1, min_value=0, max_value=500, help_text="Reject a design above 24.1 kPa (3.5 psi) at the highest test flow."),
    _field("max_coolant_rise", 1, "Maximum coolant temperature rise", "float", "temperature_difference", default=12, min_value=0, max_value=100, help_text="Keep the coolant outlet within 12 K of its inlet temperature."),
    _field("fom_weight_gpu", 1, "GPU figure-of-merit weight", "float", "dimensionless", default=0.3, min_value=0, max_value=1, help_text="The GPU figure-of-merit weight is 0.3."),
    _field("fom_weight_hbm", 1, "HBM figure-of-merit weight", "float", "dimensionless", default=0.7, min_value=0, max_value=1, help_text="The HBM figure-of-merit weight is 0.7, and HBM is the binding temperature limit."),
    _field("die_region_size", 2, "Die region size", "vec2", "length", default=[52.15, 50.30], min_value=0, max_value=500, help_text="The package heat-source origin is the lower-left corner of the 52.15 × 50.30 mm die region."),
    _field("heat_sources", 2, "Heat sources", "table", default=_HEAT_SOURCES, help_text="The package contains two 554.4 W GPUs and eight 48 W HBM stacks at the listed die coordinates."),
    _field("total_power", 2, "Total heat-source power", "float", "power", default=1492.8, min_value=0, max_value=100000, help_text="The combined heat-source power is 1492.8 W."),
    _field("power_map_mode", 2, "GPU power-map mode", "enum", default="uniform_per_source", is_assumption=True, choices=("uniform_per_source", "grid_file"), help_text="GPU power is estimated non-uniformly from competition-figure color bands, so uniform per-source power is the default assumption."),
    _field("power_map_file", 2, "GPU power-map file", "file", required=lambda v: v.get("power_map_mode") == "grid_file", help_text="The supplied non-uniform GPU power map is a 0.5 mm heat-flux grid, with its first row and column at cell centers."),
    _field("power_map_pitch", 2, "GPU power-map pitch", "float", "length", required=lambda v: v.get("power_map_mode") == "grid_file", default=0.5, min_value=0, max_value=10, help_text="The supplied GPU power-map grid has a 0.5 mm pitch."),
    _field("base_plate_size", 3, "Base-plate size", "vec3", "length", default=[78, 78, 2], min_value=0, max_value=500, help_text="The base plate is 78 × 78 × 2 mm and is centered on the package."),
    _field("base_material", 3, "Base-plate material", "object", required=True, default={"name": "copper C110", "k": 391}, is_assumption=True, subfields={"name": None, "k": "conductivity"}, help_text="The base material is assumed to be rolled C110 copper with conductivity 391 W/m·K."),
    _field("fin_design_space", 3, "Fin design-space size", "vec3", "length", default=[52.15, 52.15, 2.0], min_value=0, max_value=500, help_text="The fin design space is 52.15 × 52.15 × 2.0 mm and is centered on the package."),
    _field("min_feature", 3, "Minimum feature size", "float", "length", default=0.1, min_value=0, max_value=10, help_text="The minimum manufacturable feature is 0.1 mm."),
    _field("max_feature", 3, "Maximum feature size", "float", "length", default=0.5, min_value=0, max_value=10, help_text="The maximum manufacturable feature is 0.5 mm."),
    _field("resolution_xy", 3, "XY manufacturing resolution", "float", "small_length", default=33.33, min_value=0, max_value=1000, help_text="The assumed manufacturing resolution is 33.33 µm in XY."),
    _field("resolution_z", 3, "Z manufacturing resolution", "float", "small_length", default=30, min_value=0, max_value=1000, help_text="The assumed manufacturing resolution is 30 µm in Z."),
    _field("min_overhang_angle", 3, "Minimum overhang angle", "float", "angle", default=20, min_value=0, max_value=90, help_text="The minimum overhang angle is 20°."),
    _field("gasket", 3, "Gasket", "object", required=True, default={"material": "silicone", "thickness": 3.0, "notes": "seals top of fins so flow can't bypass"}, subfields={"material": None, "thickness": "length", "notes": None}, help_text="A 3 mm silicone gasket seals the top of the fin plate so flow cannot bypass the fins."),
    _field("tim_resistance", 3, "TIM area resistance", "float", "area_resistance", default=0.05, is_assumption=True, min_value=0, max_value=10, help_text="The assumed thermal interface material area resistance is 0.05 cm²·K/W."),
    _field("tim_thickness", 3, "TIM thickness", "float", "length", default=0.05, is_assumption=True, min_value=0, max_value=5, help_text="The assumed thermal interface material thickness is 0.05 mm."),
    _field("flow_configuration", 4, "Flow configuration", "enum", default="split_flow_edges_to_center", choices=("split_flow_edges_to_center", "cross_flow", "center_in_edges_out", "custom"), help_text="The source flow path splits inlet flow along both outer edges and exits at the center over the GPU hotspots."),
    _field("flow_path_notes", 4, "Flow-path notes", "str", required=False, help_text="Use notes to capture any flow-path details that are not represented by the selected configuration."),
    _field("fluid", 5, "Coolant", "enum", default="water", is_assumption=True, choices=("water", "PG25", "other"), help_text="Water is the assumed coolant, pending confirmation against the official rules."),
    _field("fluid_properties", 5, "Coolant properties", "object", required=True, default={"rho": 997, "cp": 4180, "mu": 7.97e-4, "k": 0.615}, subfields={"rho": "density", "cp": "specific_heat", "mu": "viscosity", "k": "conductivity"}, help_text="The listed water density, specific heat, 30 °C viscosity, and thermal conductivity are the source values."),
    _field("inlet_temp_nominal", 5, "Nominal inlet temperature", "float", "temperature", default=30, is_assumption=True, min_value=0, max_value=100, help_text="The nominal coolant inlet temperature is assumed to be 30 °C and should be checked against the official rules."),
    _field("inlet_temp_sweep", 5, "Inlet-temperature sweep", "list", "temperature", default=[20, 25, 30, 35], min_value=0, max_value=100, help_text="Test inlet temperatures of 20, 25, 30, and 35 °C, with the worst case at the highest inlet temperature."),
    _field("flow_nominal", 5, "Nominal flow rate", "float", "flow", default=2.0, is_assumption=True, min_value=0, max_value=50, help_text="The nominal coolant flow rate is assumed to be 2.0 L/min."),
    _field("flow_sweep", 5, "Flow-rate sweep", "list", "flow", default=[1.0, 1.5, 2.0, 2.5, 3.0], min_value=0, max_value=50, help_text="Report pressure drop at every test flow rate from 1.0 to 3.0 L/min."),
    _field("sweep_mode", 5, "Sweep mode", "enum", choices=("full_grid", "flow_sweep_at_nominal_temp", "custom"), help_text="Choose whether to test the full inlet-temperature and flow grid, vary flow at nominal temperature, or define a custom sweep."),
    _field("design_families", 6, "Design families", "multi", default=["straight_fins", "staggered_pins"], choices=("straight_fins", "staggered_pins", "herringbone", "gyroid", "topology_opt"), help_text="The first test case is a straight-fin plate, with staggered pins also available as a design family."),
    _field("baseline_design", 6, "Baseline design", "str", default="straight fins, 0.3 mm fin, 0.3 mm gap, 2 mm tall, split flow", help_text="Run a plain straight-fin plate first using 0.3 mm fins, 0.3 mm gaps, and 2 mm height."),
    _field("required_outputs", 6, "Required outputs", "multi", required=False, default=list(_OUTPUT_CHOICES), choices=_OUTPUT_CHOICES, help_text="Report component maximum and mean temperatures, component thermal resistance, pressure drop by flow, pumping power, and chip-plane and fin-layer fields."),
]

FIELD_BY_ID = {field.id: field for field in FIELDS}

_STRICT_MINIMUMS = {
    "dp_penalty_per_psi",
    "die_region_size",
    "total_power",
    "power_map_pitch",
    "base_plate_size",
    "fin_design_space",
    "min_feature",
    "max_feature",
    "resolution_xy",
    "resolution_z",
    "tim_resistance",
    "tim_thickness",
    "fluid_properties",
    "flow_nominal",
    "flow_sweep",
}


def is_required(field, values):
    return field.required(values) if callable(field.required) else field.required


def _number_with_quantity(value, quantity, unit=None, context="value"):
    value_unit = unit
    if isinstance(value, str):
        try:
            number, parsed_unit = units.parse_quantity(value)
        except ValueError as exc:
            raise ValueError(f"{context} must be numeric ({exc})") from exc
        if parsed_unit is not None:
            value_unit = parsed_unit
    elif isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{context} must be numeric")
    else:
        number = value
    try:
        return units.to_canonical(number, value_unit, quantity)
    except units.UnitError as exc:
        raise ValueError(f"{context}: {exc}") from exc


def _check_bounds(field, value, context=None):
    label = context or field.id
    lower_bad = value < field.min if field.id not in _STRICT_MINIMUMS else value <= field.min
    upper_bad = field.max is not None and value > field.max
    if lower_bad or upper_bad:
        minimum = units.format_value(field.min, field.unit) if field.min is not None else None
        maximum = units.format_value(field.max, field.unit) if field.max is not None else None
        if minimum is not None and maximum is not None:
            if field.id in _STRICT_MINIMUMS:
                bounds = f"greater than {minimum} and at most {maximum}"
            else:
                bounds = f"between {minimum} and {maximum}"
        elif minimum is not None:
            bounds = f"greater than {minimum}" if field.id in _STRICT_MINIMUMS else f"at least {minimum}"
        else:
            bounds = f"at most {maximum}"
        raise ValueError(
            f"{label} must be {bounds} (got {units.format_value(value, field.unit)})"
        )


def _sequence(value, field):
    if isinstance(value, str):
        result = [part.strip() for part in value.split(",")]
    elif isinstance(value, (list, tuple)):
        result = list(value)
    else:
        raise ValueError(f"{field.id} must be a list of values")
    if not result or any(part == "" for part in result):
        raise ValueError(f"{field.id} must not be empty")
    if field.type in {"vec2", "vec3"}:
        expected = int(field.type[-1])
        if len(result) != expected:
            raise ValueError(f"{field.id} must contain exactly {expected} values")
    return result


def _validate_table(field, value, unit):
    if not isinstance(value, list):
        raise ValueError(f"{field.id} must be a list of rows")
    rows = []
    names = set()
    for index, row in enumerate(value, 1):
        if not isinstance(row, dict):
            raise ValueError(f"{field.id} row {index} must be an object")
        required = {"name", "type", "x0", "y0", "w", "h", "power_W"}
        missing = required - row.keys()
        if missing:
            raise ValueError(f"{field.id} row {index} is missing {', '.join(sorted(missing))}")
        name = str(row["name"]).strip()
        if not name:
            raise ValueError(f"{field.id} row {index} name must not be empty")
        if name in names:
            raise ValueError(f"{field.id} names must be unique (duplicate {name!r})")
        names.add(name)
        source_type = str(row["type"])
        match = next((choice for choice in ("GPU", "HBM", "other") if choice.casefold() == source_type.casefold()), None)
        if match is None:
            raise ValueError(f"{field.id} row {name} type must be GPU, HBM, or other")
        converted = {"name": name, "type": match}
        for key in ("x0", "y0", "w", "h"):
            converted[key] = _number_with_quantity(row[key], "length", unit, f"{field.id} row {name} {key}")
            if key in {"x0", "y0"} and converted[key] < 0:
                raise ValueError(f"{field.id} row {name} {key} must be at least 0 mm")
            if key in {"w", "h"} and converted[key] <= 0:
                raise ValueError(f"{field.id} row {name} {key} must be greater than 0 mm")
        converted["power_W"] = _number_with_quantity(row["power_W"], "power", None, f"{field.id} row {name} power_W")
        if converted["power_W"] <= 0:
            raise ValueError(f"{field.id} row {name} power_W must be greater than 0 W")
        rows.append(converted)
    return rows


def _validate_object(field, value):
    if not isinstance(value, dict):
        raise ValueError(f"{field.id} must be an object")
    result = {}
    for key, quantity in (field.subfields or {}).items():
        if key not in value:
            raise ValueError(f"{field.id} is missing {key}")
        item = value[key]
        if quantity is None:
            if not isinstance(item, str):
                raise ValueError(f"{field.id}.{key} must be text")
            result[key] = item
            continue
        item_unit = None
        if isinstance(item, dict):
            if "value" not in item:
                raise ValueError(f"{field.id}.{key} needs a value")
            item_unit = item.get("unit")
            item = item["value"]
        result[key] = _number_with_quantity(item, quantity, item_unit, f"{field.id}.{key}")
        if result[key] <= 0:
            raise ValueError(f"{field.id}.{key} must be greater than 0 {units.QUANTITIES[quantity]}")
    return result


def validate(field, value, unit):
    """Validate a field value and return it in canonical form."""
    if value is None:
        raise ValueError(f"{field.id} cannot be empty")
    if field.type in {"float", "int"}:
        canonical = _number_with_quantity(value, field.quantity, unit, field.id) if field.quantity else _number_with_quantity(value, "dimensionless", unit, field.id)
        if field.type == "int":
            if not canonical.is_integer():
                raise ValueError(f"{field.id} must be a whole number")
            canonical = int(canonical)
        _check_bounds(field, canonical)
        return canonical
    if field.type == "enum":
        if not isinstance(value, str):
            raise ValueError(f"{field.id} must be one of {', '.join(field.choices or ())}")
        match = next((choice for choice in field.choices or () if choice.casefold() == value.casefold()), None)
        if match is None:
            raise ValueError(f"{field.id} must be one of {', '.join(field.choices or ())} (got {value!r})")
        return match
    if field.type == "multi":
        if not isinstance(value, (list, tuple)):
            raise ValueError(f"{field.id} must be a list")
        selected = []
        for item in value:
            match = next((choice for choice in field.choices or () if choice.casefold() == str(item).casefold()), None)
            if match is None:
                raise ValueError(f"{field.id} must contain only {', '.join(field.choices or ())} (got {item!r})")
            if match not in selected:
                selected.append(match)
        if not selected and field.required is not False:
            raise ValueError(f"{field.id} must contain at least one choice")
        return selected
    if field.type in {"list", "vec2", "vec3"}:
        values = _sequence(value, field)
        result = []
        for index, item in enumerate(values, 1):
            converted = _number_with_quantity(item, field.quantity, unit, f"{field.id} item {index}")
            _check_bounds(field, converted, f"{field.id} item {index}")
            result.append(converted)
        return result
    if field.type == "object":
        return _validate_object(field, value)
    if field.type == "table":
        return _validate_table(field, value, unit)
    if field.type == "str":
        if not isinstance(value, str):
            raise ValueError(f"{field.id} must be text")
        return value.strip()
    if field.type == "file":
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{field.id} must be a non-empty file path")
        return value.strip()
    raise ValueError(f"unsupported field type {field.type!r} for {field.id}")
