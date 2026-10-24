"""Derive the regression-test requirement documents (tests B-F) from the canonical ITherm input.

Each variant applies exact text edits to tests/fixtures/A_canonical.md (a verbatim copy of
coldplate_devin_inputs.md); every edit must match exactly once, so a changed canonical file
fails loudly instead of drifting.
"""

from __future__ import annotations

from pathlib import Path

FIXTURES = Path(__file__).resolve().parents[1] / "tests" / "fixtures"

FLOW_SWEEP_SECTION = """### Flow sweep

| Flow (L/min) | Flow (gpm) | Bulk water temp rise (K) |
|---|---|---|
| 1.0 | 0.264 | 21.49 |
| 1.5 | 0.396 | 14.33 |
| 2.0 | 0.528 | 10.75 |
| 2.5 | 0.660 | 8.60 |
| 3.0 | 0.793 | 7.16 |

"""

VARIANTS: dict[str, list[tuple[str, str]]] = {
    # Test B: nominal flow 2.0 -> 3.0 L/min (sweep table unchanged).
    "B_flow_3lpm.md": [
        ("| Flow, nominal (**ASSUMPTION**) | 2.0 L/min |", "| Flow, nominal (**ASSUMPTION**) | 3.0 L/min |"),
    ],
    # Test C: GPU1 power +20 % (554.4 -> 665.28 W); total, flux and sweep rises kept consistent.
    "C_gpu1_power_plus20.md": [
        ("Total power: **1492.8 W**.", "Total power: **1603.68 W**."),
        ("| GPU1 | GPU | 0.00 | 10.15 | 26.0 | 30.0 | 554.4 | 71.1 |", "| GPU1 | GPU | 0.00 | 10.15 | 26.0 | 30.0 | 665.28 | 85.3 |"),
        ("Each GPU still sums to exactly 554.4 W.", "GPU1 sums to exactly 665.28 W and GPU2 to 554.4 W."),
        ("| 1.0 | 0.264 | 21.49 |", "| 1.0 | 0.264 | 23.09 |"),
        ("| 1.5 | 0.396 | 14.33 |", "| 1.5 | 0.396 | 15.39 |"),
        ("| 2.0 | 0.528 | 10.75 |", "| 2.0 | 0.528 | 11.54 |"),
        ("| 2.5 | 0.660 | 8.60 |", "| 2.5 | 0.660 | 9.24 |"),
        ("| 3.0 | 0.793 | 7.16 |", "| 3.0 | 0.793 | 7.70 |"),
    ],
    # Test D: larger plate and fin design space; die region and heat sources unchanged.
    "D_plate_90x84.md": [
        ("| Base plate | 78 × 78 × 2 mm,", "| Base plate | 90 × 84 × 2.5 mm,"),
        ("| Fin design space | 52.15 × 52.15 × 2.0 mm,", "| Fin design space | 56.00 × 54.00 × 2.0 mm,"),
    ],
    # Test E: coolant flow removed entirely (nominal row and flow sweep).
    "E_missing_flow.md": [
        ("| Flow, nominal (**ASSUMPTION**) | 2.0 L/min |\n", ""),
        (FLOW_SWEEP_SECTION, ""),
    ],
    # Test F: temperature limits no design can meet (inlet is 30 °C, bulk rise 10.75 K).
    "F_impossible_limits.md": [
        ("| GPU max temp | 100 °C | ≤ 85 °C | ≤ 80 °C |", "| GPU max temp | 40 °C | ≤ 38 °C | ≤ 36 °C |"),
        ("| HBM max temp | 70 °C | ≤ 63 °C | ≤ 60 °C |", "| HBM max temp | 35 °C | ≤ 34 °C | ≤ 33 °C |"),
        ("With a 70 °C HBM limit,", "With a 35 °C HBM limit,"),
    ],
}


def main() -> None:
    canonical = (FIXTURES / "A_canonical.md").read_text(encoding="utf-8")
    for name, edits in VARIANTS.items():
        text = canonical
        for old, new in edits:
            count = text.count(old)
            if count != 1:
                raise SystemExit(f"{name}: expected exactly one match for {old!r}, found {count}")
            text = text.replace(old, new)
        (FIXTURES / name).write_text(text, encoding="utf-8", newline="\n")
        print(f"wrote {name}")


if __name__ == "__main__":
    main()
