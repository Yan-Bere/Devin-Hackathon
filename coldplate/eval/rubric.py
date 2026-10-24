"""Expected extraction results for the prompt-evaluation fixtures (tests A-F).

Values are in the canonical units of ``coldplate.extraction_schema.CANONICAL_UNITS``
for the given quantity kind; the harness converts Devin's (value, unit) pairs before
comparing. Paths address ``RequirementsExtraction`` fields; ``name[key=value]``
selects the list element whose ``key`` equals ``value`` (case-insensitive).

Scoring semantics (implemented by ``coldplate.eval.harness``):
- extraction error: value outside tolerance, value missing, unit not convertible,
  text/enum mismatch, heat-source mismatch, missing/extra heat source, a required
  missing_fields entry absent, or a forbidden value present.
- provenance error: value correct but ``source`` not in ``sources``.
- unsupported assumption: ``source == "assumed"`` at any rubric path (the document
  states the value, or it is an essential input that must never be assumed).
- evidence miss: ``source`` is input/input_flagged_assumption but ``evidence`` is not
  a verbatim substring of the document (after whitespace/markdown normalisation).
"""

from __future__ import annotations

from dataclasses import dataclass, replace

INPUT = ("input",)
FLAGGED = ("input_flagged_assumption",)
INPUT_OR_FLAGGED = ("input", "input_flagged_assumption")


@dataclass(frozen=True)
class Check:
    path: str
    value: float | str | tuple[float, ...] | tuple[str, ...] | None
    kind: str | None = None  # quantity kind for numeric values; None for text/enum
    sources: tuple[str, ...] = INPUT
    rel_tol: float = 1e-3
    # "equal" (numeric within rel_tol, or exact enum), "one_of" (enum in the tuple), "contains" (case-insensitive
    # substring of a text value), "list" (numeric list: same length, sorted values within rel_tol),
    # "contains_all" (string list: every expected item appears, case-insensitive substring of some element),
    # "covers_type" (string list naming sources or types: each expected type is listed by type name, or every
    # extracted heat source of that type is listed by name -- the schema allows either form)
    match: str = "equal"
    essential: bool = False


@dataclass(frozen=True)
class ExpectedHeatSource:
    name: str
    type: str
    x0: float
    y0: float
    width: float
    height: float
    power: float


@dataclass(frozen=True)
class Rubric:
    fixture: str
    description: str
    checks: tuple[Check, ...]
    heat_sources: tuple[ExpectedHeatSource, ...]
    expect_missing: tuple[str, ...] = ()  # paths that must be value=null, source="missing"
    required_missing_entries: tuple[str, ...] = ()  # substrings that must appear in an essential missing_fields[].field
    forbidden: tuple[Check, ...] = ()  # (path, value) pairs that must NOT be reported, under any source
    allow_essential_missing: bool = False
    heat_source_tol: float = 1e-3


_HS_A = (
    ExpectedHeatSource("GPU1", "GPU", 0.00, 10.15, 26.0, 30.0, 554.4),
    ExpectedHeatSource("GPU2", "GPU", 26.15, 10.15, 26.0, 30.0, 554.4),
    ExpectedHeatSource("H1", "HBM", 0.00, 40.30, 12.0, 10.0, 48.0),
    ExpectedHeatSource("H2", "HBM", 14.00, 40.30, 12.0, 10.0, 48.0),
    ExpectedHeatSource("H3", "HBM", 26.15, 40.30, 12.0, 10.0, 48.0),
    ExpectedHeatSource("H4", "HBM", 40.15, 40.30, 12.0, 10.0, 48.0),
    ExpectedHeatSource("H5", "HBM", 0.00, 0.00, 12.0, 10.0, 48.0),
    ExpectedHeatSource("H6", "HBM", 14.00, 0.00, 12.0, 10.0, 48.0),
    ExpectedHeatSource("H7", "HBM", 26.15, 0.00, 12.0, 10.0, 48.0),
    ExpectedHeatSource("H8", "HBM", 40.15, 0.00, 12.0, 10.0, 48.0),
)

_CHECKS_A = (
    Check("plate.length_x", 78.0, "length"),
    Check("plate.width_y", 78.0, "length"),
    Check("plate.thickness", 2.0, "length"),
    Check("plate.material", "copper", match="contains", sources=INPUT_OR_FLAGGED),
    Check("plate.thermal_conductivity", 391.0, "thermal_conductivity", sources=INPUT_OR_FLAGGED),
    Check("fin_region.length_x", 52.15, "length"),
    Check("fin_region.width_y", 52.15, "length"),
    Check("fin_region.height", 2.0, "length"),
    Check("die_region.width_x", 52.15, "length"),
    Check("die_region.height_y", 50.30, "length"),
    Check("stated_total_power", 1492.8, "power"),
    Check("power_map.distribution", ("non_uniform_file", "non_uniform_described"), match="one_of"),
    Check("power_map.file_name", "power_map_W_per_mm2.csv", match="contains"),
    Check("power_map.grid_pitch", 0.5, "length", sources=INPUT_OR_FLAGGED),
    Check("power_map.stated_peak_flux", 1.34e6, "heat_flux", sources=INPUT_OR_FLAGGED),
    Check("power_map.uniform_components", ("HBM",), match="covers_type"),
    Check("temperature_limits[component_type=GPU].hard_max", 100.0, "temperature"),
    Check("temperature_limits[component_type=GPU].target_max", 85.0, "temperature"),
    Check("temperature_limits[component_type=GPU].stretch_max", 80.0, "temperature"),
    Check("temperature_limits[component_type=HBM].hard_max", 70.0, "temperature"),
    Check("temperature_limits[component_type=HBM].target_max", 63.0, "temperature"),
    Check("temperature_limits[component_type=HBM].stretch_max", 60.0, "temperature"),
    Check("critical_component", "HBM", match="contains"),
    Check("coolant.fluid", "water", match="contains", sources=FLAGGED),
    Check("coolant.density", 997.0, "density"),
    Check("coolant.specific_heat", 4180.0, "specific_heat"),
    Check("coolant.dynamic_viscosity", 7.97e-4, "viscosity"),
    Check("coolant.thermal_conductivity", 0.615, "thermal_conductivity"),
    Check("coolant.inlet_temperature", 30.0, "temperature", sources=FLAGGED, essential=True),
    Check("coolant.inlet_temperature_sweep", (20.0, 25.0, 30.0, 35.0), "temperature", match="list"),
    Check("coolant.flow_rate", 2.0, "flow_rate", sources=FLAGGED, essential=True),
    Check("coolant.flow_rate_sweep", (1.0, 1.5, 2.0, 2.5, 3.0), "flow_rate", match="list"),
    Check("coolant.max_outlet_temperature_rise", 12.0, "temperature_difference"),
    Check("flow.arrangement", "split_edges_to_center"),
    Check("manufacturing.min_feature", 0.1, "length"),
    Check("manufacturing.max_feature", 0.5, "length"),
    Check("manufacturing.xy_resolution", 0.03333, "length", rel_tol=2e-3),
    Check("manufacturing.z_resolution", 0.03, "length"),
    Check("manufacturing.min_overhang_angle", 20.0, "angle"),
    Check("baseline_design.fin_type", "straight", match="contains"),
    Check("baseline_design.fin_thickness", 0.3, "length"),
    Check("baseline_design.channel_width", 0.3, "length"),
    Check("baseline_design.fin_height", 2.0, "length"),
    Check("tim.area_resistance", 5.0e-6, "area_thermal_resistance", sources=FLAGGED),
    Check("tim.thickness", 0.05, "length", sources=FLAGGED),
    Check("pressure_drop.hard_limit", 27600.0, "pressure", rel_tol=5e-3),
    Check("pressure_drop.design_target", 13800.0, "pressure", rel_tol=5e-3),
    Check("pressure_drop.stretch_goal", 6900.0, "pressure", rel_tol=5e-3),
    Check("pressure_drop.acceptance_limit", 24100.0, "pressure", rel_tol=5e-3),
    Check("acceptance.temperature_margin", 5.0, "temperature_difference"),
)


def _with(checks: tuple[Check, ...], **overrides: object) -> tuple[Check, ...]:
    """Replace the expected value of the checks whose path is a key (dots written as '__')."""
    wanted = {k.replace("__", "."): v for k, v in overrides.items()}
    out = tuple(replace(c, value=wanted[c.path]) if c.path in wanted else c for c in checks)
    unknown = set(wanted) - {c.path for c in checks}
    if unknown:
        raise KeyError(f"unknown rubric paths: {sorted(unknown)}")
    return out


def _without(checks: tuple[Check, ...], *paths: str) -> tuple[Check, ...]:
    return tuple(c for c in checks if c.path not in paths)


RUBRICS: dict[str, Rubric] = {
    "A_canonical.md": Rubric(
        fixture="A_canonical.md",
        description="Canonical ITherm 2027 input (verbatim coldplate_devin_inputs.md).",
        checks=_CHECKS_A,
        heat_sources=_HS_A,
    ),
    "B_flow_3lpm.md": Rubric(
        fixture="B_flow_3lpm.md",
        description="Nominal flow changed 2.0 -> 3.0 L/min.",
        checks=_with(_CHECKS_A, coolant__flow_rate=3.0),
        heat_sources=_HS_A,
        forbidden=(Check("coolant.flow_rate", 2.0, "flow_rate"),),
    ),
    "C_gpu1_power_plus20.md": Rubric(
        fixture="C_gpu1_power_plus20.md",
        description="GPU1 power +20 % (665.28 W); stated total 1603.68 W.",
        checks=_with(_CHECKS_A, stated_total_power=1603.68),
        heat_sources=tuple(replace(h, power=665.28) if h.name == "GPU1" else h for h in _HS_A),
    ),
    "D_plate_90x84.md": Rubric(
        fixture="D_plate_90x84.md",
        description="Base plate 90 x 84 x 2.5 mm; fin design space 56 x 54 x 2.0 mm.",
        checks=_with(
            _CHECKS_A,
            plate__length_x=90.0,
            plate__width_y=84.0,
            plate__thickness=2.5,
            fin_region__length_x=56.0,
            fin_region__width_y=54.0,
        ),
        heat_sources=_HS_A,
    ),
    "E_missing_flow.md": Rubric(
        fixture="E_missing_flow.md",
        description="Nominal flow row and flow sweep removed; flow must be reported missing, never 2.0 L/min.",
        checks=_without(_CHECKS_A, "coolant.flow_rate", "coolant.flow_rate_sweep"),
        heat_sources=_HS_A,
        expect_missing=("coolant.flow_rate",),
        required_missing_entries=("flow",),
        forbidden=(Check("coolant.flow_rate", 2.0, "flow_rate"),),
        allow_essential_missing=True,
    ),
    "F_impossible_limits.md": Rubric(
        fixture="F_impossible_limits.md",
        description="Temperature limits no design can satisfy (GPU 40/38/36 C, HBM 35/34/33 C).",
        checks=_with(
            _CHECKS_A,
            **{
                "temperature_limits[component_type=GPU]__hard_max": 40.0,
                "temperature_limits[component_type=GPU]__target_max": 38.0,
                "temperature_limits[component_type=GPU]__stretch_max": 36.0,
                "temperature_limits[component_type=HBM]__hard_max": 35.0,
                "temperature_limits[component_type=HBM]__target_max": 34.0,
                "temperature_limits[component_type=HBM]__stretch_max": 33.0,
            },
        ),
        heat_sources=_HS_A,
    ),
}

__all__ = ["Check", "ExpectedHeatSource", "Rubric", "RUBRICS", "INPUT", "FLAGGED", "INPUT_OR_FLAGGED"]
