import pytest

import units


def test_converts_pressure_flow_and_temperature():
    assert units.to_canonical(4, "psi", "pressure") == pytest.approx(27.579, abs=1e-3)
    assert units.to_canonical(0.528, "gpm", "flow") == pytest.approx(1.99869, abs=1e-4)
    assert units.to_canonical(86, "°F", "temperature") == pytest.approx(30)
    assert units.to_canonical(300, "K", "temperature") == pytest.approx(26.85)
    assert units.to_canonical(9, "°F", "temperature_difference") == pytest.approx(5)


def test_small_length_and_alias_normalization():
    assert units.to_canonical(33.33, "um", "small_length") == pytest.approx(33.33)
    assert units.to_canonical(0.03333, "mm", "small_length") == pytest.approx(33.33)
    normalized = {units.normalize_unit(unit) for unit in ("cm2K/W", "cm²·K/W", "cm^2-K/W")}
    assert len(normalized) == 1
    assert units.to_canonical(1, "cm²·°C/W", "area_resistance") == pytest.approx(1)
    assert units.normalize_unit("W/(m·K)") == "W/m·K"
    assert units.to_canonical(1, "mPa·s", "viscosity") == pytest.approx(0.001)


def test_heat_flux_viscosity_and_incompatible_units():
    assert units.to_canonical(8, "W/cm²", "heat_flux") == pytest.approx(0.08)
    assert units.to_canonical(1, "cP", "viscosity") == pytest.approx(0.001)
    with pytest.raises(units.UnitError, match="not compatible"):
        units.to_canonical(1, "psi", "temperature")


def test_parse_quantity():
    assert units.parse_quantity("4 psi") == (4.0, "psi")
    assert units.parse_quantity("27.6") == (27.6, None)
    assert units.format_value(27.579, "kPa") == "27.579 kPa"
    assert units.format_value(1492.8, "W") == "1492.8 W"
    assert units.format_value(12.0, "W") == "12 W"
