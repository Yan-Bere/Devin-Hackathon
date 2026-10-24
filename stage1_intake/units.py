"""Unit normalization and conversion helpers for intake values."""

import math
import re


QUANTITIES = {
    "pressure": "kPa",
    "temperature": "°C",
    "temperature_difference": "K",
    "length": "mm",
    "small_length": "µm",
    "flow": "L/min",
    "power": "W",
    "heat_flux": "W/mm²",
    "area_resistance": "cm²·K/W",
    "conductivity": "W/m·K",
    "density": "kg/m³",
    "specific_heat": "J/kg·K",
    "viscosity": "Pa·s",
    "angle": "deg",
    "dimensionless": "",
    "penalty": "FoM/psi",
}


class UnitError(ValueError):
    """Raised when a unit is unknown or incompatible with a quantity."""


_UNIT_LABELS = {
    "pa": "Pa",
    "kpa": "kPa",
    "mpa": "MPa",
    "bar": "bar",
    "psi": "psi",
    "mbar": "mbar",
    "°c": "°C",
    "c": "°C",
    "degc": "°C",
    "celsius": "°C",
    "°f": "°F",
    "f": "°F",
    "degf": "°F",
    "fahrenheit": "°F",
    "k": "K",
    "kelvin": "K",
    "m": "m",
    "cm": "cm",
    "mm": "mm",
    "µm": "µm",
    "um": "µm",
    "micron": "µm",
    "microns": "µm",
    "in": "in",
    "inch": "in",
    "inches": "in",
    "l/min": "L/min",
    "lpm": "L/min",
    "gpm": "gpm",
    "ml/min": "mL/min",
    "m³/s": "m³/s",
    "m3/s": "m³/s",
    "l/s": "L/s",
    "w": "W",
    "kw": "kW",
    "mw": "mW",
    "w/mm2": "W/mm²",
    "w/cm2": "W/cm²",
    "w/m2": "W/m²",
    "cm2k/w": "cm²·K/W",
    "mm2k/w": "mm²·K/W",
    "m2k/w": "m²·K/W",
    "cm2°c/w": "cm²·K/W",
    "mm2°c/w": "mm²·K/W",
    "m2°c/w": "m²·K/W",
    "w/mk": "W/m·K",
    "w/(mk)": "W/m·K",
    "kg/m3": "kg/m³",
    "g/cm3": "g/cm³",
    "j/kgk": "J/kg·K",
    "kj/kgk": "kJ/kg·K",
    "pas": "Pa·s",
    "mpas": "mPa·s",
    "cp": "cP",
    "deg": "deg",
    "°": "deg",
    "rad": "rad",
    "": "",
    "fom/psi": "FoM/psi",
}


def _unit_key(unit):
    value = str(unit).strip().replace("μ", "µ").replace("º", "°")
    value = value.replace("·", "").replace("*", "").replace("-", "").replace(" ", "")
    value = value.replace("²", "2").replace("^2", "2").replace("³", "3")
    return value.casefold()


def normalize_unit(s):
    """Return the standard spelling for a supported unit alias."""
    key = _unit_key(s)
    try:
        return _UNIT_LABELS[key]
    except KeyError as exc:
        raise UnitError(f"unknown unit {s!r}") from exc


_CONVERSIONS = {
    "pressure": {
        "Pa": (1e-3, 0),
        "kPa": (1, 0),
        "MPa": (1e3, 0),
        "bar": (100, 0),
        "psi": (6.894757293168, 0),
        "mbar": (0.1, 0),
    },
    "temperature": {
        "°C": (1, 0),
        "°F": (5 / 9, -32 * 5 / 9),
        "K": (1, -273.15),
    },
    "temperature_difference": {
        "K": (1, 0),
        "°C": (1, 0),
        "°F": (5 / 9, 0),
    },
    "length": {
        "m": (1000, 0),
        "cm": (10, 0),
        "mm": (1, 0),
        "µm": (0.001, 0),
        "in": (25.4, 0),
    },
    "small_length": {
        "m": (1e6, 0),
        "cm": (1e4, 0),
        "mm": (1e3, 0),
        "µm": (1, 0),
        "in": (25400, 0),
    },
    "flow": {
        "L/min": (1, 0),
        "gpm": (3.785411784, 0),
        "mL/min": (0.001, 0),
        "m³/s": (60e3, 0),
        "L/s": (60, 0),
    },
    "power": {"W": (1, 0), "kW": (1000, 0), "mW": (0.001, 0)},
    "heat_flux": {
        "W/mm²": (1, 0),
        "W/cm²": (0.01, 0),
        "W/m²": (1e-6, 0),
    },
    "area_resistance": {
        "cm²·K/W": (1, 0),
        "mm²·K/W": (0.01, 0),
        "m²·K/W": (1e4, 0),
    },
    "conductivity": {"W/m·K": (1, 0)},
    "density": {"kg/m³": (1, 0), "g/cm³": (1000, 0)},
    "specific_heat": {"J/kg·K": (1, 0), "kJ/kg·K": (1000, 0)},
    "viscosity": {"Pa·s": (1, 0), "mPa·s": (0.001, 0), "cP": (0.001, 0)},
    "angle": {"deg": (1, 0), "rad": (180 / math.pi, 0), "°": (1, 0)},
    "dimensionless": {"": (1, 0)},
    "penalty": {"FoM/psi": (1, 0)},
}


def _quantity_unit(unit):
    key = _unit_key(unit)
    try:
        return _UNIT_LABELS[key]
    except KeyError as exc:
        raise UnitError(f"unknown unit {unit!r}") from exc


def to_canonical(value, unit, quantity):
    """Convert a numeric value to the canonical unit for quantity."""
    if quantity not in QUANTITIES:
        raise UnitError(f"unknown quantity {quantity!r}")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise UnitError(f"value {value!r} is not numeric") from exc
    if not math.isfinite(number):
        raise UnitError(f"value {value!r} must be finite")
    if unit is None or str(unit).strip() == "":
        return number
    parsed_unit = _quantity_unit(unit)
    conversions = _CONVERSIONS[quantity]
    if parsed_unit not in conversions:
        raise UnitError(
            f"unit {unit!r} is not compatible with {quantity} "
            f"(expected {QUANTITIES[quantity] or 'no unit'})"
        )
    scale, offset = conversions[parsed_unit]
    return number * scale + offset


_QUANTITY_RE = re.compile(
    r"^\s*([+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)\s*(.*?)\s*$"
)


def parse_quantity(text):
    """Parse a number, optionally followed by a unit."""
    match = _QUANTITY_RE.match(str(text))
    if not match:
        raise ValueError(f"could not parse quantity {text!r}")
    number, unit = match.groups()
    if not unit:
        return float(number), None
    normalize_unit(unit)
    return float(number), unit


def format_value(value, unit):
    """Format a number to six significant figures for display."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    formatted = f"{number:.6g}"
    return f"{formatted} {unit}".rstrip()
