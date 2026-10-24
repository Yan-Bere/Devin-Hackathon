"""Devin-facing structured-output schema for cold-plate requirements extraction.

This module is prompt-coupled: the field names and descriptions below are sent to
Devin as ``structured_output_schema`` and therefore act as part of the prompt.
Change them only together with a new prompt version under ``prompts/``.

Devin reports every number with its unit *exactly as written*; unit conversion to
the engine's canonical units happens deterministically in Python afterwards
(see ``QUANTITY_KINDS`` and ``CANONICAL_UNITS``).
"""

from __future__ import annotations

import copy
import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

SCHEMA_VERSION = "coldplate-extraction/1"
MAX_DEVIN_SCHEMA_BYTES = 64 * 1024

Source = Literal["input", "input_flagged_assumption", "assumed", "missing"]
_EVIDENCE = "Verbatim quote (<=160 chars) from the document containing the value; null unless source is input or input_flagged_assumption."


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Quantity(_Strict):
    value: float | None = Field(description="Number exactly as written; null if missing.")
    unit: str | None = Field(description="Unit exactly as written, e.g. 'mm', 'L/min', 'psi', '°C'.")
    source: Source
    evidence: str | None = Field(description=_EVIDENCE)
    note: str | None


class Text(_Strict):
    value: str | None
    source: Source
    evidence: str | None = Field(description=_EVIDENCE)
    note: str | None


class NumberList(_Strict):
    values: list[float] = Field(description="All listed values exactly as written; empty if missing.")
    unit: str | None
    source: Source
    evidence: str | None = Field(description=_EVIDENCE)
    note: str | None


class Plate(_Strict):
    length_x: Quantity
    width_y: Quantity
    thickness: Quantity
    material: Text
    thermal_conductivity: Quantity
    placement: Text = Field(description="Position relative to the package, e.g. 'centered on package'.")


class FinRegion(_Strict):
    length_x: Quantity = Field(description="Fin/channel design-space size along x.")
    width_y: Quantity
    height: Quantity = Field(description="Design-space height available for fins.")
    placement: Text


class DieRegion(_Strict):
    width_x: Quantity = Field(description="Size along x of the region the heat-source coordinates refer to.")
    height_y: Quantity
    placement: Text


class HeatSource(_Strict):
    name: str
    type: Literal["GPU", "HBM", "CPU", "ASIC", "memory", "VRM", "other"]
    x0: float | None = Field(description="Lower-left x in coordinate_frame.")
    y0: float | None = Field(description="Lower-left y in coordinate_frame.")
    width: float | None = Field(description="Size along x.")
    height: float | None = Field(description="Size along y.")
    length_unit: str | None
    power: float | None
    power_unit: str | None
    source: Source
    evidence: str | None = Field(description="Verbatim table row or sentence defining this source.")
    note: str | None


class PowerMap(_Strict):
    distribution: Literal["uniform", "non_uniform_file", "non_uniform_described", "unspecified"] = Field(
        description="'non_uniform_file' if a power/heat-flux map file is referenced; 'uniform' if heat is stated to be spread evenly over every source."
    )
    file_name: str | None
    file_units: str | None = Field(description="Units of the map values, e.g. 'W/mm^2'.")
    grid_pitch: Quantity
    grid_origin: Text = Field(description="Row/column orientation of the map file as stated.")
    stated_peak_flux: Quantity
    uniform_components: list[str] = Field(description="Source names or types the document says have evenly spread heat.")
    source: Source
    evidence: str | None = Field(description=_EVIDENCE)
    note: str | None


class TemperatureLimit(_Strict):
    component_type: str
    hard_max: Quantity = Field(description="Disqualifying maximum temperature.")
    target_max: Quantity
    stretch_max: Quantity


class Coolant(_Strict):
    fluid: Text
    density: Quantity
    specific_heat: Quantity
    dynamic_viscosity: Quantity
    thermal_conductivity: Quantity
    inlet_temperature: Quantity = Field(description="Nominal inlet temperature.")
    inlet_temperature_sweep: NumberList
    flow_rate: Quantity = Field(description="Nominal volumetric flow rate.")
    flow_rate_sweep: NumberList
    max_outlet_temperature_rise: Quantity = Field(description="Maximum allowed outlet-minus-inlet temperature.")


class Flow(_Strict):
    arrangement: Literal[
        "split_edges_to_center", "split_center_to_edges", "straight", "u_turn", "serpentine", "radial", "other", "unspecified"
    ] = Field(description="split_edges_to_center: coolant enters along two opposite outer edges and leaves at a center outlet.")
    flow_axis: Literal["x", "y", "unspecified"] = Field(
        description="Axis along which coolant crosses the fin region in coordinate_frame; 'unspecified' unless stated or unambiguous."
    )
    inlet: Text
    outlet: Text
    source: Source
    evidence: str | None = Field(description=_EVIDENCE)
    note: str | None


class Manufacturing(_Strict):
    min_feature: Quantity
    max_feature: Quantity
    xy_resolution: Quantity
    z_resolution: Quantity
    min_overhang_angle: Quantity
    process: Text


class BaselineDesign(_Strict):
    fin_type: Text = Field(description="Reference/first-test design the document asks to run, e.g. 'straight fins'.")
    fin_thickness: Quantity
    channel_width: Quantity = Field(description="Gap between fins.")
    fin_height: Quantity


class Tim(_Strict):
    area_resistance: Quantity = Field(description="Area-specific thermal resistance R''.")
    thickness: Quantity


class PressureDrop(_Strict):
    hard_limit: Quantity
    design_target: Quantity
    stretch_goal: Quantity
    acceptance_limit: Quantity = Field(description="Stricter limit used to accept designs, if stated.")
    acceptance_condition: Text = Field(description="Where acceptance_limit applies, e.g. 'at the highest test flow'.")


class Acceptance(_Strict):
    temperature_margin: Quantity = Field(description="Required margin below the hard temperature limits.")
    worst_case_condition: Text = Field(description="Operating point at which the margin rule is checked.")


class Objective(_Strict):
    metric: Literal[
        "max_critical_temperature",
        "max_gpu_temperature",
        "max_hbm_temperature",
        "pressure_drop",
        "pumping_power",
        "thermal_resistance",
        "temperature_margin",
        "other",
    ]
    direction: Literal["minimize", "maximize"]
    description: str
    source: Source
    evidence: str | None = Field(description=_EVIDENCE)


class Assumption(_Strict):
    field: str = Field(description="Dotted field path, e.g. coolant.inlet_temperature.")
    statement: str
    source: Literal["input_flagged_assumption", "assumed"]


class MissingField(_Strict):
    field: str = Field(description="Dotted field path, e.g. coolant.flow_rate.")
    reason: str
    essential: bool


class RequirementsExtraction(_Strict):
    schema_version: Literal["coldplate-extraction/1"]
    document_title: str | None
    coordinate_frame: Text = Field(description="Origin and axes of the heat-source coordinates, as stated.")
    plate: Plate
    fin_region: FinRegion
    die_region: DieRegion
    heat_sources: list[HeatSource] = Field(description="Every heat source, one entry each, in document order.")
    stated_total_power: Quantity = Field(description="Total power only if the document states it; do not sum it yourself.")
    power_map: PowerMap
    temperature_limits: list[TemperatureLimit] = Field(description="One entry per component type with limits.")
    critical_component: Text = Field(description="Component type the document names as the binding temperature limit, if any.")
    coolant: Coolant
    flow: Flow
    manufacturing: Manufacturing
    baseline_design: BaselineDesign
    tim: Tim
    pressure_drop: PressureDrop
    acceptance: Acceptance
    objectives: list[Objective] = Field(description="Optimization objectives stated or clearly implied by the scoring rules.")
    assumptions: list[Assumption] = Field(description="Every value the document marks as an assumption or placeholder, plus any value you assumed.")
    missing_fields: list[MissingField] = Field(description="Every required engineering input the document does not give.")


# Physical kind of every Quantity / NumberList path. The normalizer converts each
# value from the unit Devin reported to CANONICAL_UNITS[kind].
QUANTITY_KINDS: dict[str, str] = {
    "plate.length_x": "length",
    "plate.width_y": "length",
    "plate.thickness": "length",
    "plate.thermal_conductivity": "thermal_conductivity",
    "fin_region.length_x": "length",
    "fin_region.width_y": "length",
    "fin_region.height": "length",
    "die_region.width_x": "length",
    "die_region.height_y": "length",
    "stated_total_power": "power",
    "power_map.grid_pitch": "length",
    "power_map.stated_peak_flux": "heat_flux",
    "temperature_limits[].hard_max": "temperature",
    "temperature_limits[].target_max": "temperature",
    "temperature_limits[].stretch_max": "temperature",
    "coolant.density": "density",
    "coolant.specific_heat": "specific_heat",
    "coolant.dynamic_viscosity": "viscosity",
    "coolant.thermal_conductivity": "thermal_conductivity",
    "coolant.inlet_temperature": "temperature",
    "coolant.inlet_temperature_sweep": "temperature",
    "coolant.flow_rate": "flow_rate",
    "coolant.flow_rate_sweep": "flow_rate",
    "coolant.max_outlet_temperature_rise": "temperature_difference",
    "manufacturing.min_feature": "length",
    "manufacturing.max_feature": "length",
    "manufacturing.xy_resolution": "length",
    "manufacturing.z_resolution": "length",
    "manufacturing.min_overhang_angle": "angle",
    "baseline_design.fin_thickness": "length",
    "baseline_design.channel_width": "length",
    "baseline_design.fin_height": "length",
    "tim.area_resistance": "area_thermal_resistance",
    "tim.thickness": "length",
    "pressure_drop.hard_limit": "pressure",
    "pressure_drop.design_target": "pressure",
    "pressure_drop.stretch_goal": "pressure",
    "pressure_drop.acceptance_limit": "pressure",
    "acceptance.temperature_margin": "temperature_difference",
    "heat_sources[].length": "length",
    "heat_sources[].power": "power",
}

CANONICAL_UNITS: dict[str, str] = {
    "length": "mm",
    "power": "W",
    "temperature": "degC",
    "temperature_difference": "K",
    "flow_rate": "L/min",
    "pressure": "Pa",
    "density": "kg/m^3",
    "specific_heat": "J/(kg*K)",
    "viscosity": "Pa*s",
    "thermal_conductivity": "W/(m*K)",
    "heat_flux": "W/m^2",
    "area_thermal_resistance": "m^2*K/W",
    "angle": "deg",
}


def _strip(node: Any) -> Any:
    if isinstance(node, dict):
        return {k: _strip(v) for k, v in node.items() if k not in ("title", "default")}
    if isinstance(node, list):
        return [_strip(v) for v in node]
    return node


def _rewrite_refs(node: Any) -> Any:
    if isinstance(node, dict):
        return {
            k: (v.replace("#/$defs/", "#/definitions/") if k == "$ref" and isinstance(v, str) else _rewrite_refs(v))
            for k, v in node.items()
        }
    if isinstance(node, list):
        return [_rewrite_refs(v) for v in node]
    return node


def devin_json_schema() -> dict[str, Any]:
    """Self-contained JSON Schema (Draft 7) sent as Devin's structured_output_schema."""
    raw = copy.deepcopy(RequirementsExtraction.model_json_schema())
    defs = raw.pop("$defs", {})
    schema = {"$schema": "http://json-schema.org/draft-07/schema#", **raw, "definitions": defs}
    schema = _rewrite_refs(_strip(schema))
    size = len(json.dumps(schema, separators=(",", ":")).encode("utf-8"))
    if size > MAX_DEVIN_SCHEMA_BYTES:
        raise ValueError(f"structured_output_schema is {size} bytes; Devin's limit is {MAX_DEVIN_SCHEMA_BYTES}")
    return schema
