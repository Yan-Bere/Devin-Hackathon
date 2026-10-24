# ITherm 2027 Cold Plate: Simulation Inputs

Package: 2 GPUs + 8 HBM stacks. Geometry and power come from the competition figures. Anything marked **ASSUMPTION** is a placeholder until checked against the official rules.

Units: mm, W, °C, kPa (psi also given), L/min (gpm also given).

Files that go with this:
- `power_map_W_per_mm2.csv`: 0.5 mm heat-flux grid
- `itherm_layout.png`: power map and flow path diagram

![Power map and flow path](itherm_layout.png)

---

## 1. Hard limits (disqualification)

| Quantity | Hard limit | Design target | Stretch goal |
|---|---|---|---|
| Pressure drop | 4.0 psi (27.6 kPa) | ≤ 2.0 psi (13.8 kPa) | ≤ 1.0 psi (6.9 kPa) |
| GPU max temp | 100 °C | ≤ 85 °C | ≤ 80 °C |
| HBM max temp | 70 °C | ≤ 63 °C | ≤ 60 °C |

Rules for accepting a design:
- Reject any design within **5 K** of a temperature hard limit at the worst sweep point (highest inlet temp, lowest flow).
- Reject any design above **3.5 psi (24.1 kPa)** at the highest test flow. CFD and machined prototypes usually disagree by 10 to 15%.
- Coolant outlet should stay within **12 K** of inlet.
- Lower pressure drop scores better, so report ΔP at every flow point.
- HBM is the binding limit. Check every stack and report the hottest one.

---

## 2. Heat sources

Origin is the lower-left corner of the 52.15 × 50.30 mm die region. Total power: **1492.8 W**.

| Name | Type | x0 | y0 | Width (x) | Height (y) | Power (W) | Avg flux (W/cm²) |
|---|---|---|---|---|---|---|---|
| GPU1 | GPU | 0.00 | 10.15 | 26.0 | 30.0 | 554.4 | 71.1 |
| GPU2 | GPU | 26.15 | 10.15 | 26.0 | 30.0 | 554.4 | 71.1 |
| H1 | HBM | 0.00 | 40.30 | 12.0 | 10.0 | 48.0 | 40.0 |
| H2 | HBM | 14.00 | 40.30 | 12.0 | 10.0 | 48.0 | 40.0 |
| H3 | HBM | 26.15 | 40.30 | 12.0 | 10.0 | 48.0 | 40.0 |
| H4 | HBM | 40.15 | 40.30 | 12.0 | 10.0 | 48.0 | 40.0 |
| H5 | HBM | 0.00 | 0.00 | 12.0 | 10.0 | 48.0 | 40.0 |
| H6 | HBM | 14.00 | 0.00 | 12.0 | 10.0 | 48.0 | 40.0 |
| H7 | HBM | 26.15 | 0.00 | 12.0 | 10.0 | 48.0 | 40.0 |
| H8 | HBM | 40.15 | 0.00 | 12.0 | 10.0 | 48.0 | 40.0 |

### GPU power map (non-uniform)
- **ASSUMPTION:** estimated from the color bands in the competition figure. Relative levels are 2.0 / 2.4 / 4.0 / 6.0 / 7.0, with the hottest spot at the package centerline. Each GPU still sums to exactly 554.4 W.
- Peak flux: about **134 W/cm²**.
- HBM heat is spread evenly over each stack.
- Grid file: `power_map_W_per_mm2.csv`, 0.5 mm pitch. Row 0 is y = 0.25 mm (bottom), column 0 is x = 0.25 mm (left).
- Replace this with the organizers' exact map if they provide one.

---

## 3. Cold plate

| Item | Value |
|---|---|
| Base plate | 78 × 78 × 2 mm, rolled copper (C110 assumed, k = 391 W/m·K), centered on package |
| Fin design space | 52.15 × 52.15 × 2.0 mm, centered on package |
| Min feature | 0.1 mm |
| Max feature | 0.5 mm |
| Resolution | 33.33 µm (XY), 30 µm (Z) |
| Min overhang angle | 20° |
| Gasket | Silicone, 3 mm thick, seals the top of the fin plate so flow can't bypass |
| TIM (**ASSUMPTION**) | R″ = 0.05 cm²·K/W, 0.05 mm thick |

**Flow path:** split flow. Coolant enters along the two outer edges, flows through the fins toward the centerline, and exits through the center outlet over the GPU hotspots.

---

## 4. Coolant

| Property | Value |
|---|---|
| Fluid (**ASSUMPTION**) | Water |
| Density | 997 kg/m³ |
| cp | 4180 J/kg·K |
| Viscosity at 30 °C | 7.97 × 10⁻⁴ Pa·s |
| Thermal conductivity | 0.615 W/m·K |
| Inlet temp, nominal (**ASSUMPTION**) | 30 °C |
| Inlet temp sweep | 20, 25, 30, 35 °C |

With a 70 °C HBM limit, an inlet above about 35 °C leaves almost no room. Confirm the inlet temperature in the official rules.

---

## 5. Required outputs

- Max and mean temperature for each component
- Thermal resistance for each component: R_th = (T_max − T_inlet) / P
- Pressure drop at every flow point
- Pumping power = ΔP × Q
- Temperature contour on the chip plane
- Velocity field in the fin layer

---

## 6. First test case

Run a plain straight-fin plate first to check the solver before optimizing:
- 0.3 mm fins, 0.3 mm gaps, 2 mm tall
- Flow from both edges to the center
