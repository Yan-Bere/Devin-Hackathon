"""The normalized cold-plate specification consumed by the engine.

``ColdPlateSpec`` mirrors the extraction sections but with every quantity
converted to canonical units (field names carry the unit) and a ``Provenance``
on every value. ``engine_inputs()`` distils it to plain floats for the physics
and CAD layers — and refuses to run while essential inputs are missing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, PrivateAttr

Provenance = Literal[
    "input", "input_flagged_assumption", "assumed", "derived", "engine_default", "missing"
]

SPEC_VERSION = "coldplate-spec/1"


class Val(BaseModel):
    """A scalar quantity in the canonical unit named by the field."""

    value: Optional[float] = None
    unit: str = ""
    source: Provenance = "missing"
    evidence: Optional[str] = None
    note: Optional[str] = None
    original: Optional[str] = None  # value+unit exactly as reported, e.g. "4.0 psi"


class TextVal(BaseModel):
    value: Optional[str] = None
    source: Provenance = "missing"
    evidence: Optional[str] = None
    note: Optional[str] = None
    original: Optional[str] = None


class ListVal(BaseModel):
    values: list[float] = []
    unit: str = ""
    source: Provenance = "missing"
    evidence: Optional[str] = None
    note: Optional[str] = None
    original: Optional[str] = None


class PlateSpec(BaseModel):
    length_x_mm: Val = Val()
    width_y_mm: Val = Val()
    thickness_mm: Val = Val()
    k_W_mK: Val = Val()
    material: TextVal = TextVal()


class FinRegionSpec(BaseModel):
    length_x_mm: Val = Val()
    width_y_mm: Val = Val()
    height_mm: Val = Val()
    origin_plate_mm: list[float] = []  # lower-left corner in plate frame
    placement: TextVal = TextVal()


class DieRegionSpec(BaseModel):
    width_x_mm: Val = Val()
    height_y_mm: Val = Val()
    origin_plate_mm: list[float] = []
    placement: TextVal = TextVal()


class HeatSourceSpec(BaseModel):
    name: str
    type: str = "other"
    x0_mm: Optional[float] = None  # document/heat-source frame
    y0_mm: Optional[float] = None
    width_mm: Optional[float] = None
    height_mm: Optional[float] = None
    x0_plate_mm: Optional[float] = None  # plate frame
    y0_plate_mm: Optional[float] = None
    power_W: Optional[float] = None
    source: Provenance = "missing"
    evidence: Optional[str] = None
    note: Optional[str] = None


class PowerMapSpec(BaseModel):
    distribution: Optional[str] = None
    file_name: Optional[str] = None
    grid_pitch_mm: Val = Val()
    grid_origin: TextVal = TextVal()
    stated_peak_flux_W_m2: Val = Val()
    uniform_components: list[str] = []
    applied: Literal["uniform", "file"] = "uniform"
    description: Optional[str] = None


class TempLimitSpec(BaseModel):
    component_type: str
    hard_C: Val = Val()
    target_C: Val = Val()
    stretch_C: Val = Val()


class CoolantSpec(BaseModel):
    fluid: TextVal = TextVal()
    density_kg_m3: Val = Val()
    cp_J_kgK: Val = Val()
    viscosity_Pa_s: Val = Val()
    k_W_mK: Val = Val()
    inlet_temperature_C: Val = Val()
    inlet_temperature_sweep_C: ListVal = ListVal()
    flow_rate_Lpm: Val = Val()
    flow_rate_sweep_Lpm: ListVal = ListVal()
    max_outlet_rise_K: Val = Val()


class FlowSpec(BaseModel):
    arrangement: str = "straight"  # straight|split_edges_to_center|split_center_to_edges
    flow_axis: str = "x"
    inlet: TextVal = TextVal()
    outlet: TextVal = TextVal()
    inlet_opening_mm: Val = Val()
    outlet_opening_mm: Val = Val()


class ManufacturingSpec(BaseModel):
    min_feature_mm: Val = Val()
    max_feature_mm: Val = Val()
    xy_resolution_mm: Val = Val()
    z_resolution_mm: Val = Val()
    min_overhang_angle_deg: Val = Val()
    process: TextVal = TextVal()


class BaselineSpec(BaseModel):
    fin_type: TextVal = TextVal()
    fin_thickness_mm: Val = Val()
    channel_width_mm: Val = Val()
    fin_height_mm: Val = Val()


class TimSpec(BaseModel):
    r_m2K_W: Val = Val()
    thickness_mm: Val = Val()


class PressureSpec(BaseModel):
    hard_Pa: Val = Val()
    target_Pa: Val = Val()
    stretch_Pa: Val = Val()
    acceptance_Pa: Val = Val()
    acceptance_condition: TextVal = TextVal()


class AcceptanceSpec(BaseModel):
    temperature_margin_K: Val = Val()
    worst_case_condition: TextVal = TextVal()


class ObjectiveSpec(BaseModel):
    metric: str = "other"
    direction: str = "minimize"
    description: str = ""
    source: Provenance = "missing"
    evidence: Optional[str] = None


class AssumptionRec(BaseModel):
    field: str
    statement: str
    origin: Literal["document", "devin", "engine"]


class ReportedMissing(BaseModel):
    field: str
    reason: str = ""
    essential: bool = False


class ColdPlateSpec(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    spec_version: Literal["coldplate-spec/1"] = SPEC_VERSION
    document_title: Optional[str] = None
    coordinate_frame: TextVal = TextVal()
    plate: PlateSpec = PlateSpec()
    fin_region: FinRegionSpec = FinRegionSpec()
    die_region: DieRegionSpec = DieRegionSpec()
    heat_sources: list[HeatSourceSpec] = []
    total_power_W: Optional[float] = None  # derived sum of heat_sources
    stated_total_power_W: Val = Val()
    power_map: PowerMapSpec = PowerMapSpec()
    temperature_limits: list[TempLimitSpec] = []
    critical_component_type: TextVal = TextVal()
    coolant: CoolantSpec = CoolantSpec()
    flow: FlowSpec = FlowSpec()
    manufacturing: ManufacturingSpec = ManufacturingSpec()
    baseline: BaselineSpec = BaselineSpec()
    tim: TimSpec = TimSpec()
    pressure: PressureSpec = PressureSpec()
    acceptance: AcceptanceSpec = AcceptanceSpec()
    objectives: list[ObjectiveSpec] = []
    assumptions: list[AssumptionRec] = []
    missing_essential: list[str] = []
    missing_optional: list[str] = []
    reported_missing: list[ReportedMissing] = []
    warnings: list[str] = []

    _power_map_obj: Any = PrivateAttr(default=None)  # coldplate.power_map.PowerMap

    def attach_power_map(self, power_map: Any) -> None:
        self._power_map_obj = power_map

    def engine_inputs(self) -> "EngineInputs":
        """Distil to plain floats; raises while essential inputs are missing."""
        if self.missing_essential:
            raise ValueError(
                "missing essential inputs: " + ", ".join(self.missing_essential)
            )
        from coldplate.power_map import Footprint, UniformPowerMap

        sources = tuple(
            SourceInput(
                name=s.name,
                type=s.type,
                x0_mm=s.x0_plate_mm or 0.0,
                y0_mm=s.y0_plate_mm or 0.0,
                width_mm=s.width_mm or 0.0,
                height_mm=s.height_mm or 0.0,
                power_W=s.power_W or 0.0,
            )
            for s in self.heat_sources
        )
        pmap = self._power_map_obj or UniformPowerMap(
            tuple(
                Footprint(
                    name=s.name,
                    type=s.type,
                    x0=s.x0_mm,
                    y0=s.y0_mm,
                    x1=s.x0_mm + s.width_mm,
                    y1=s.y0_mm + s.height_mm,
                    power_W=s.power_W,
                )
                for s in sources
            )
        )

        def _v(val: Val, default: Optional[float] = None) -> Optional[float]:
            return val.value if val.value is not None else default

        return EngineInputs(
            plate_lx_mm=_v(self.plate.length_x_mm, 0.0),
            plate_ly_mm=_v(self.plate.width_y_mm, 0.0),
            base_thickness_mm=_v(self.plate.thickness_mm, 0.0),
            k_solid_W_mK=_v(self.plate.k_W_mK, 0.0),
            fin_region_x0_mm=(self.fin_region.origin_plate_mm + [0.0, 0.0])[0],
            fin_region_y0_mm=(self.fin_region.origin_plate_mm + [0.0, 0.0])[1],
            fin_region_lx_mm=_v(self.fin_region.length_x_mm, 0.0),
            fin_region_ly_mm=_v(self.fin_region.width_y_mm, 0.0),
            fin_height_max_mm=_v(self.fin_region.height_mm, 0.0),
            sources=sources,
            power_map=pmap,
            rho_kg_m3=_v(self.coolant.density_kg_m3, 0.0),
            cp_J_kgK=_v(self.coolant.cp_J_kgK, 0.0),
            mu_Pa_s=_v(self.coolant.viscosity_Pa_s, 0.0),
            k_fluid_W_mK=_v(self.coolant.k_W_mK, 0.0),
            inlet_C=_v(self.coolant.inlet_temperature_C, 0.0),
            flow_Lpm=_v(self.coolant.flow_rate_Lpm, 0.0),
            inlet_sweep_C=tuple(self.coolant.inlet_temperature_sweep_C.values),
            flow_sweep_Lpm=tuple(self.coolant.flow_rate_sweep_Lpm.values),
            max_outlet_rise_K=self.coolant.max_outlet_rise_K.value,
            arrangement=self.flow.arrangement,
            flow_axis=self.flow.flow_axis,
            inlet_opening_mm=_v(self.flow.inlet_opening_mm, 0.0),
            outlet_opening_mm=_v(self.flow.outlet_opening_mm, 0.0),
            min_feature_mm=self.manufacturing.min_feature_mm.value,
            max_feature_mm=self.manufacturing.max_feature_mm.value,
            baseline_fin_thickness_mm=self.baseline.fin_thickness_mm.value,
            baseline_channel_width_mm=self.baseline.channel_width_mm.value,
            baseline_fin_height_mm=self.baseline.fin_height_mm.value,
            tim_r_m2K_W=_v(self.tim.r_m2K_W, 0.0),
            limits_C={
                t.component_type: t.hard_C.value
                for t in self.temperature_limits
                if t.hard_C.value is not None
            },
            targets_C={
                t.component_type: t.target_C.value
                for t in self.temperature_limits
                if t.target_C.value is not None
            },
            stretch_C={
                t.component_type: t.stretch_C.value
                for t in self.temperature_limits
                if t.stretch_C.value is not None
            },
            critical_type=self.critical_component_type.value,
            dp_hard_Pa=self.pressure.hard_Pa.value,
            dp_target_Pa=self.pressure.target_Pa.value,
            dp_stretch_Pa=self.pressure.stretch_Pa.value,
            dp_acceptance_Pa=self.pressure.acceptance_Pa.value,
            temperature_margin_K=self.acceptance.temperature_margin_K.value,
        )


@dataclass(frozen=True)
class SourceInput:
    name: str
    type: str
    x0_mm: float
    y0_mm: float
    width_mm: float
    height_mm: float
    power_W: float


@dataclass(frozen=True)
class EngineInputs:
    """Plain-float contract for the physics / CAD layers (plate frame, SI canonical)."""

    plate_lx_mm: float
    plate_ly_mm: float
    base_thickness_mm: float
    k_solid_W_mK: float
    fin_region_x0_mm: float
    fin_region_y0_mm: float
    fin_region_lx_mm: float
    fin_region_ly_mm: float
    fin_height_max_mm: float
    sources: tuple
    power_map: Any  # coldplate.power_map.PowerMap
    rho_kg_m3: float
    cp_J_kgK: float
    mu_Pa_s: float
    k_fluid_W_mK: float
    inlet_C: float
    flow_Lpm: float
    inlet_sweep_C: tuple = ()
    flow_sweep_Lpm: tuple = ()
    max_outlet_rise_K: Optional[float] = None
    arrangement: str = "straight"
    flow_axis: str = "x"
    inlet_opening_mm: float = 0.0
    outlet_opening_mm: float = 0.0
    min_feature_mm: Optional[float] = None
    max_feature_mm: Optional[float] = None
    baseline_fin_thickness_mm: Optional[float] = None
    baseline_channel_width_mm: Optional[float] = None
    baseline_fin_height_mm: Optional[float] = None
    tim_r_m2K_W: float = 0.0
    limits_C: dict = field(default_factory=dict)
    targets_C: dict = field(default_factory=dict)
    stretch_C: dict = field(default_factory=dict)
    critical_type: Optional[str] = None
    dp_hard_Pa: Optional[float] = None
    dp_target_Pa: Optional[float] = None
    dp_stretch_Pa: Optional[float] = None
    dp_acceptance_Pa: Optional[float] = None
    temperature_margin_K: Optional[float] = None
