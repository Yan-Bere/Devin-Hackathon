"""Table-driven tests for coldplate.units.convert."""

import math

import pytest

from coldplate.units import UnitError, convert

CASES = [
    # (value, unit, kind, expected canonical value)
    (78.0, "mm", "length", 78.0),
    (5.0, "cm", "length", 50.0),
    (0.078, "m", "length", 78.0),
    (33.33, "µm", "length", 0.03333),
    (30.0, "um", "length", 0.030),
    (30.0, "μm", "length", 0.030),
    (50.0, "micron", "length", 0.050),
    (1.0, "in", "length", 25.4),
    (2.0, "inch", "length", 50.8),
    (554.4, "W", "power", 554.4),
    (1.0, "kW", "power", 1000.0),
    (500.0, "mW", "power", 0.5),
    (30.0, "°C", "temperature", 30.0),
    (30.0, "ºC", "temperature", 30.0),
    (30.0, "C", "temperature", 30.0),
    (30.0, "degC", "temperature", 30.0),
    (30.0, "deg C", "temperature", 30.0),
    (30.0, "celsius", "temperature", 30.0),
    (303.15, "K", "temperature", 30.0),
    (303.15, "kelvin", "temperature", 30.0),
    (86.0, "°F", "temperature", 30.0),
    (86.0, "F", "temperature", 30.0),
    (12.0, "K", "temperature_difference", 12.0),
    (12.0, "°C", "temperature_difference", 12.0),
    (12.0, "C", "temperature_difference", 12.0),
    (18.0, "°F", "temperature_difference", 10.0),
    (2.0, "L/min", "flow_rate", 2.0),
    (2.0, "l/min", "flow_rate", 2.0),
    (2.0, "LPM", "flow_rate", 2.0),
    (2.0, "lpm", "flow_rate", 2.0),
    (500.0, "mL/min", "flow_rate", 0.5),
    (0.528, "gpm", "flow_rate", 0.528 * 3.785411784),
    (1.0, "GPM", "flow_rate", 3.785411784),
    (1.0e-5, "m^3/s", "flow_rate", 0.6),
    (3.6, "m³/h", "flow_rate", 60.0),
    (27600.0, "Pa", "pressure", 27600.0),
    (27.6, "kPa", "pressure", 27600.0),
    (0.0276, "MPa", "pressure", 27600.0),
    (0.276, "bar", "pressure", 27600.0),
    (276.0, "mbar", "pressure", 27600.0),
    (4.0, "psi", "pressure", 4.0 * 6894.757293168),
    (4.0, "psid", "pressure", 4.0 * 6894.757293168),
    (997.0, "kg/m^3", "density", 997.0),
    (997.0, "kg/m³", "density", 997.0),
    (0.997, "g/cm^3", "density", 997.0),
    (0.997, "g/mL", "density", 997.0),
    (4180.0, "J/kg·K", "specific_heat", 4180.0),
    (4180.0, "J/(kg·K)", "specific_heat", 4180.0),
    (4180.0, "J/kgK", "specific_heat", 4180.0),
    (4.18, "kJ/kg·K", "specific_heat", 4180.0),
    (4180.0, "J/kg/K", "specific_heat", 4180.0),
    (0.000797, "Pa·s", "viscosity", 0.000797),
    (0.000797, "Pa s", "viscosity", 0.000797),
    (0.797, "mPa·s", "viscosity", 0.000797),
    (0.797, "cP", "viscosity", 0.000797),
    (0.797, "cp", "viscosity", 0.000797),
    (0.000797, "kg/m·s", "viscosity", 0.000797),
    (0.615, "W/m·K", "thermal_conductivity", 0.615),
    (0.615, "W/(m·K)", "thermal_conductivity", 0.615),
    (0.615, "W/mK", "thermal_conductivity", 0.615),
    (0.615, "W/m/K", "thermal_conductivity", 0.615),
    (1.0, "W/m²", "heat_flux", 1.0),
    (1.0, "W/cm²", "heat_flux", 1.0e4),
    (1.0, "W/mm²", "heat_flux", 1.0e6),
    (134.0, "W/cm^2", "heat_flux", 134.0e4),
    (1.0, "m²·K/W", "area_thermal_resistance", 1.0),
    (1.0, "cm²·K/W", "area_thermal_resistance", 1.0e-4),
    (0.05, "cm²·K/W", "area_thermal_resistance", 0.05e-4),
    (1.0, "mm²·K/W", "area_thermal_resistance", 1.0e-6),
    (1.0, "K·cm²/W", "area_thermal_resistance", 1.0e-4),
    (1.0, "°C·cm²/W", "area_thermal_resistance", 1.0e-4),
    (0.05, "cm^2*K/W", "area_thermal_resistance", 0.05e-4),
    (20.0, "°", "angle", 20.0),
    (20.0, "deg", "angle", 20.0),
    (20.0, "degree", "angle", 20.0),
    (20.0, "degrees", "angle", 20.0),
]


@pytest.mark.parametrize("value,unit,kind,expected", CASES)
def test_convert(value, unit, kind, expected):
    got = convert(value, unit, kind)
    assert math.isclose(got, expected, rel_tol=1e-9, abs_tol=1e-12), (
        f"{value} {unit} as {kind}: got {got}, want {expected}"
    )


def test_none_and_unknown_units_raise():
    with pytest.raises(UnitError):
        convert(1.0, None, "length")
    with pytest.raises(UnitError):
        convert(1.0, "", "length")
    with pytest.raises(UnitError):
        convert(1.0, "furlong", "length")
    with pytest.raises(UnitError):
        convert(1.0, "W", "length")
    with pytest.raises(UnitError):
        convert(1.0, "mm", "bogus_kind")
    with pytest.raises(UnitError):
        convert(1.0, "blargs", "flow_rate")


def test_no_silent_defaults():
    # a present-but-unparseable unit must never fall through to a default
    for kind in ("length", "power", "pressure", "flow_rate"):
        with pytest.raises(UnitError):
            convert(3.0, "???", kind)
