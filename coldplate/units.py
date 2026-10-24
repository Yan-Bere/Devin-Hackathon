"""Deterministic unit conversion to the canonical units of CANONICAL_UNITS.

``convert(value, unit, kind)`` maps a (value, unit-as-written) pair to the
canonical unit for ``kind`` (see ``coldplate.extraction_schema.CANONICAL_UNITS``).
Unknown or missing units raise ``UnitError`` — the engine never guesses.

Unit spelling normalisation: NFKC, whitespace removed, ``· ⋅ ×`` treated as
``*``, ``^`` and superscripts flattened (``m^2``/``m²`` -> ``m2``), ``º``/``°``
-> ``deg``, ``µ``/``μ`` -> ``u``, parentheses removed (all supported units are
linear products/quotients, so grouping carries no information), then matched
case-insensitively against a per-kind table (per-kind tables remove prefix
ambiguity: "MPa" only exists under pressure, "mPa·s" only under viscosity).
"""

from __future__ import annotations

import unicodedata

from coldplate.extraction_schema import CANONICAL_UNITS


class UnitError(ValueError):
    """A unit is missing, unknown, or wrong for the requested kind."""


def _norm_unit(unit: str) -> str:
    s = unit.strip().replace("\u00ba", "\u00b0")  # masculine ordinal -> degree
    s = unicodedata.normalize("NFKC", s)
    for ch in ("°",):  # ° -> deg (µ is already folded to μ by NFKC)
        s = s.replace(ch, "deg")
    s = s.replace("\u00b5", "u").replace("\u03bc", "u")  # micro sign / greek mu
    s = s.replace("\u2212", "-").replace("\u2013", "-").replace("\u2014", "-")
    for ch in ("·", "⋅", "∙", "×"):
        s = s.replace(ch, "*")
    s = s.replace(" ", "").replace("\u00a0", "").replace("\u2009", "")
    s = s.replace("**", "*")  # collapse accidental double stars
    s = s.replace("(", "").replace(")", "")
    s = s.replace("^", "")
    return s.strip("*").lower()


# factor from the written unit to CANONICAL_UNITS[kind]; linear units only.
_FACTOR_TABLE: dict[str, dict[str, float]] = {
    "length": {
        "mm": 1.0,
        "millimeter": 1.0,
        "millimeters": 1.0,
        "millimetre": 1.0,
        "millimetres": 1.0,
        "cm": 10.0,
        "centimeter": 10.0,
        "centimeters": 10.0,
        "centimetre": 10.0,
        "centimetres": 10.0,
        "m": 1000.0,
        "meter": 1000.0,
        "meters": 1000.0,
        "metre": 1000.0,
        "metres": 1000.0,
        "km": 1.0e6,
        "um": 1.0e-3,
        "micron": 1.0e-3,
        "microns": 1.0e-3,
        "micrometer": 1.0e-3,
        "micrometers": 1.0e-3,
        "micrometre": 1.0e-3,
        "micrometres": 1.0e-3,
        "in": 25.4,
        "inch": 25.4,
        "inches": 25.4,
        '"': 25.4,
    },
    "power": {
        "w": 1.0,
        "watt": 1.0,
        "watts": 1.0,
        "kw": 1.0e3,
        "kilowatt": 1.0e3,
        "kilowatts": 1.0e3,
        "mw": 1.0e-3,
        "milliwatt": 1.0e-3,
        "milliwatts": 1.0e-3,
    },
    "temperature": {
        # to degC
        "degc": 1.0,
        "c": 1.0,
        "celsius": 1.0,
    },
    "temperature_difference": {
        # to K (interval, no offset)
        "k": 1.0,
        "kelvin": 1.0,
        "degc": 1.0,
        "c": 1.0,
        "delta_degc": 1.0,
        "degf": 5.0 / 9.0,
        "f": 5.0 / 9.0,
        "r": 5.0 / 9.0,
        "rankine": 5.0 / 9.0,
    },
    "flow_rate": {
        # to L/min
        "l/min": 1.0,
        "lpm": 1.0,
        "l/m": 1.0,
        "liter/min": 1.0,
        "liters/min": 1.0,
        "litre/min": 1.0,
        "litres/min": 1.0,
        "ml/min": 1.0e-3,
        "l/s": 60.0,
        "l/h": 1.0 / 60.0,
        "gpm": 3.785411784,
        "m3/s": 60000.0,
        "m3/h": 1000.0 / 60.0,
        "m3/min": 1000.0,
    },
    "pressure": {
        # to Pa
        "pa": 1.0,
        "pascal": 1.0,
        "pascals": 1.0,
        "kpa": 1.0e3,
        "kilopascal": 1.0e3,
        "mpa": 1.0e6,
        "megapascal": 1.0e6,
        "bar": 1.0e5,
        "mbar": 100.0,
        "millibar": 100.0,
        "psi": 6894.757293168,
        "psid": 6894.757293168,
        "psia": 6894.757293168,
        "psig": 6894.757293168,
        "mmh2o": 9.80665,
        "mmh20": 9.80665,
        "inh2o": 249.08891,
        "inh20": 249.08891,
    },
    "density": {
        # to kg/m^3
        "kg/m3": 1.0,
        "g/cm3": 1000.0,
        "g/cc": 1000.0,
        "g/ml": 1000.0,
        "kg/l": 1000.0,
        "g/l": 1.0,
        "mg/m3": 1.0e-6,
        "lb/ft3": 16.01846337,
    },
    "specific_heat": {
        # to J/(kg*K)
        "j/kg*k": 1.0,
        "j/kgk": 1.0,
        "j/kg/k": 1.0,
        "j/kg*degc": 1.0,
        "j/kg/degc": 1.0,
        "kj/kg*k": 1000.0,
        "kj/kgk": 1000.0,
        "kj/kg/k": 1000.0,
        "j/g*k": 1000.0,
        "j/gk": 1000.0,
    },
    "viscosity": {
        # to Pa*s
        "pa*s": 1.0,
        "pas": 1.0,
        "kg/m*s": 1.0,
        "kg/ms": 1.0,
        "mpa*s": 1.0e-3,
        "cp": 1.0e-3,
        "centipoise": 1.0e-3,
        "poise": 0.1,
        "p": 0.1,
    },
    "thermal_conductivity": {
        # to W/(m*K)
        "w/m*k": 1.0,
        "w/mk": 1.0,
        "w/m/k": 1.0,
        "w/m*degc": 1.0,
        "w/m/degc": 1.0,
        "kw/m*k": 1000.0,
        "mw/m*k": 1.0e-3,
        "w/cm*k": 100.0,
        "w/cmk": 100.0,
        "w/cm/k": 100.0,
        "w/mm*k": 1000.0,
        "w/mmk": 1000.0,
    },
    "heat_flux": {
        # to W/m^2
        "w/m2": 1.0,
        "w/m*m": 1.0,
        "w/mm2": 1.0e6,
        "w/mm*mm": 1.0e6,
        "w/cm2": 1.0e4,
        "w/cm*cm": 1.0e4,
        "kw/m2": 1.0e3,
        "mw/m2": 1.0e-3,
    },
    "area_thermal_resistance": {
        # to m^2*K/W
        "m2*k/w": 1.0,
        "m2k/w": 1.0,
        "m*m*k/w": 1.0,
        "k*m2/w": 1.0,
        "m2*degc/w": 1.0,
        "degc*m2/w": 1.0,
        "cm2*k/w": 1.0e-4,
        "cm2k/w": 1.0e-4,
        "k*cm2/w": 1.0e-4,
        "cm2*degc/w": 1.0e-4,
        "degc*cm2/w": 1.0e-4,
        "c*cm2/w": 1.0e-4,
        "mm2*k/w": 1.0e-6,
        "mm2k/w": 1.0e-6,
        "k*mm2/w": 1.0e-6,
    },
    "angle": {
        # to deg
        "deg": 1.0,
        "degree": 1.0,
        "degrees": 1.0,
        "degs": 1.0,
        "rad": 57.29577951308232,
        "radian": 57.29577951308232,
        "radians": 57.29577951308232,
    },
}


def convert(value: float, unit: "str | None", kind: str) -> float:
    """Convert ``value`` written in ``unit`` to ``CANONICAL_UNITS[kind]``.

    Raises UnitError when kind is unknown, unit is None/empty, or the unit is
    not recognised for the kind.
    """
    if kind not in CANONICAL_UNITS:
        raise UnitError(f"unknown quantity kind {kind!r}")
    if unit is None or not str(unit).strip():
        raise UnitError(f"missing unit for {kind} quantity")
    v = float(value)
    if kind == "temperature":
        key = _norm_unit(unit)
        if key in ("degc", "c", "celsius"):
            return v
        if key in ("k", "kelvin"):
            return v - 273.15
        if key in ("degf", "f", "fahrenheit"):
            return (v - 32.0) * 5.0 / 9.0
        raise UnitError(f"unit {unit!r} not convertible as temperature")
    table = _FACTOR_TABLE.get(kind)
    if table is None:
        raise UnitError(f"no conversion table for kind {kind!r}")
    key = _norm_unit(unit)
    factor = table.get(key)
    if factor is None:
        raise UnitError(f"unit {unit!r} not convertible as {kind}")
    return v * factor


def convertible(unit: "str | None", kind: str) -> bool:
    """True if the unit spelling is recognised for ``kind``."""
    try:
        convert(1.0, unit, kind)
        return True
    except (UnitError, TypeError, ValueError):
        return False
