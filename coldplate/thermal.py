"""2-D conjugate reduced-order thermal model (monolithic sparse linear solve).

Plate mid-plane conduction + per-(row, path, u-cell) well-mixed fluid nodes,
coupled by a plate-to-fluid conductance U derived from fin/channel geometry.
Unknowns: T_s per plate cell + T_f per fluid cell.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field

import numpy as np
from scipy.sparse import lil_matrix
from scipy.sparse.linalg import spsolve

from coldplate.geometry import Layout, path_ramp, path_length_mm


def _nu_rect(alpha: float) -> float:
    a = alpha
    return 8.235 * (
        1 - 2.0421 * a + 3.0853 * a**2 - 2.4765 * a**3 + 1.0578 * a**4 - 0.1861 * a**5
    )


def _path_r(path: dict, u: float) -> float:
    return path_ramp(path, u)


@dataclass
class ThermalResult:
    components: list
    gpu_max_C: float
    hbm_max_C: float
    critical_name: str
    critical_max_C: float
    outlet_C: float
    rise_K: float
    heat_to_fluid_W: float
    energy_residual: float
    runtime_s: float
    T_s: np.ndarray = None
    T_die: np.ndarray = None
    T_f: np.ndarray = None
    velocity_u: np.ndarray = None
    grid: dict = field(default_factory=dict)
    zones: list = field(default_factory=list)
    mdot_total_kg_s: float = 0.0


def solve_thermal(
    layout: Layout,
    inputs,
    hydro,
    power_map,
    rho: float,
    mu: float,
    cp: float,
    k_f: float,
    inlet_C: float,
    grid_mm: float = 0.5,
    want_fields: bool = False,
) -> ThermalResult:
    t0 = time.perf_counter()
    axis = layout.design.flow_axis
    H_mm = layout.design.fin_height_mm
    k_s = inputs.k_solid_W_mK
    t_b = inputs.base_thickness_mm * 1e-3

    # --- grid in the flow-aligned frame over the WHOLE plate -----------------
    if axis == "x":
        Eu, Ev = inputs.plate_lx_mm, inputs.plate_ly_mm
    else:
        Eu, Ev = inputs.plate_ly_mm, inputs.plate_lx_mm
    nu = max(2, int(round(Eu / grid_mm)))
    nv = max(2, int(round(Ev / grid_mm)))
    du, dv = Eu / nu, Ev / nv
    ue = np.linspace(0.0, Eu, nu + 1)
    ve = np.linspace(0.0, Ev, nv + 1)

    # heat flux per plate cell (W/m2); build in plate coords then map
    if axis == "x":
        qpp = power_map.flux_on_grid(ue, ve)
    else:
        qpp = power_map.flux_on_grid(ve, ue).T  # [i_u, i_v] -> transpose to [v, u]
    # qpp indexed [v_row, u_col]

    # --- per-zone channel data ------------------------------------------------
    # Keyed by zone INSTANCE (zone_index): labels may repeat (e.g. two "HBM"
    # bands), and widths are shared per label while v-range/counts differ.
    zch = {}
    for ch in layout.channels:
        zch.setdefault(ch["zone_index"], []).append(ch)
    q_per = hydro.q_per_path  # zone label -> per-channel-per-path flow (m3/s)
    zones_v = []
    for zi, z in enumerate(layout.design.zones):
        chs = zch.get(zi, [])
        if not chs:
            continue
        label = z.label
        w = chs[0]["width_mm"]
        A = w * H_mm * 1e-6
        Dh = 2.0 * w * H_mm / (w + H_mm) * 1e-3
        alpha = min(w, H_mm) / max(w, H_mm)
        pitch = (w + z.fin_thickness_mm) * 1e-3
        zones_v.append({
            "label": label, "v0": z.v_start_mm, "v1": z.v_end_mm,
            "A": A, "Dh": Dh, "alpha": alpha, "pitch": pitch,
            "n_ch": len(chs),
            "q": q_per.get(label, 0.0), "w": w, "t": z.fin_thickness_mm,
        })

    # convection per zone -> U (plate->fluid footprint conductance)
    u0r, u1r = layout.u_range
    v0r, v1r = layout.v_range
    L_path = path_length_mm(layout.paths[0]) * 1e-3
    for z in zones_v:
        Re = rho * (z["q"] / z["A"]) * z["Dh"] / mu if z["A"] > 0 else 0.0
        Pr = cp * mu / k_f
        Nu_fd = _nu_rect(z["alpha"])
        Gz = Re * Pr * z["Dh"] / L_path if L_path > 0 else 0.0
        Nu_lam = Nu_fd + 0.0668 * Gz / (1 + 0.04 * Gz ** (2.0 / 3.0))
        if Re >= 4000:
            f = (0.790 * math.log(Re) - 1.64) ** -2
            Nu_t = (f / 8) * (Re - 1000) * Pr / (1 + 12.7 * (f / 8) ** 0.5 * (Pr ** (2.0 / 3.0) - 1))
            Nu = Nu_t
        elif Re > 2300:
            f = (0.790 * math.log(Re) - 1.64) ** -2
            Nu_t = (f / 8) * (Re - 1000) * Pr / (1 + 12.7 * (f / 8) ** 0.5 * (Pr ** (2.0 / 3.0) - 1))
            wgt = (Re - 2300) / 1700.0
            Nu = Nu_lam * (1 - wgt) + Nu_t * wgt
        else:
            Nu = Nu_lam
        h = Nu * k_f / z["Dh"] if z["Dh"] > 0 else 0.0
        m_fin = math.sqrt(2 * h / (k_s * z["t"] * 1e-3)) if z["t"] > 0 else 0.0
        eta = math.tanh(m_fin * H_mm * 1e-3) / (m_fin * H_mm * 1e-3) if m_fin > 0 else 1.0
        w_m, t_m = z["w"] * 1e-3, z["t"] * 1e-3
        h_eff = h * (w_m + 2 * H_mm * 1e-3 * eta) / (w_m + t_m)
        z["U"] = 1.0 / (t_b / (2 * k_s) + 1.0 / h_eff) if h_eff > 0 else 0.0
        z["h"], z["eta"], z["h_eff"], z["Re"], z["Nu"] = h, eta, h_eff, Re, Nu

    # per-row mass flow and conductance (per path)
    def row_overlap(yl, yh, a, b):
        return max(0.0, min(yh, b) - max(yl, a))

    # --- assemble -----------------------------------------------------------
    np_ = nu * nv
    # fluid nodes: (path_idx, j, i) -> node
    fnodes = {}
    coeffs = []
    mdot_by_path_row = {}
    for pi, path in enumerate(layout.paths):
        pmin = min(a for _, a, b in path["segments"])
        pmax = max(b for _, a, b in path["segments"])
        d = path.get("direction", 1)
        for j in range(nv):
            yl, yh = ve[j], ve[j + 1]
            mdot_row = 0.0
            ua_row = 0.0
            for z in zones_v:
                ov = row_overlap(yl, yh, z["v0"], z["v1"]) * 1e-3
                # smear per-channel flow as q * n_ch / L_v so the row sum
                # reproduces exactly n_ch * q (pitch * n_ch < L_v due to the
                # closing fin)
                mdot_row += rho * z["q"] * z["n_ch"] / ((z["v1"] - z["v0"]) * 1e-3) * ov
                ua_row += z["U"] * ov
            mdot_by_path_row[(pi, j)] = mdot_row
            if mdot_row <= 0 and ua_row <= 0:
                continue
            cells = [i for i in range(nu) if min(ue[i + 1], pmax) - max(ue[i], pmin) > 1e-12]
            order = cells if d > 0 else list(reversed(cells))
            prev_node = None
            for i in order:
                c0, c1 = ue[i], ue[i + 1]
                o_lo, o_hi = max(c0, pmin), min(c1, pmax)
                L = (o_hi - o_lo) * 1e-3
                if L <= 0:
                    continue
                up_edge = o_lo if d > 0 else o_hi
                dn_edge = o_hi if d > 0 else o_lo
                m_in = mdot_row * _path_r(path, up_edge)
                m_out = mdot_row * _path_r(path, dn_edge)
                UA = ua_row * L
                node = len(coeffs)
                fnodes[(pi, j, i)] = np_ + node
                coeffs.append({
                    "m_in": m_in, "m_out": m_out,
                    "add": max(0.0, m_out - m_in),
                    "leave": max(0.0, m_in - m_out),
                    "UA": UA, "i": i, "j": j, "prev": prev_node,
                })
                prev_node = np_ + node
    nf = len(coeffs)
    n = np_ + nf
    A_ = lil_matrix((n, n))
    b = np.zeros(n)

    # plate conduction + heat input
    for j in range(nv):
        for i in range(nu):
            k = j * nu + i
            diag = 0.0
            Gx = k_s * t_b * dv / du
            Gy = k_s * t_b * du / dv
            if i > 0:
                A_[k, k - 1] = -Gx
                diag += Gx
            if i < nu - 1:
                A_[k, k + 1] = -Gx
                diag += Gx
            if j > 0:
                A_[k, k - nu] = -Gy
                diag += Gy
            if j < nv - 1:
                A_[k, k + nu] = -Gy
                diag += Gy
            A_[k, k] += diag
            b[k] = qpp[j, i] * (du * 1e-3) * (dv * 1e-3)

    # fluid cells
    for (pi, j, i), idx in fnodes.items():
        c = coeffs[idx - np_]
        k = idx
        out = c["m_out"] + c["leave"]
        A_[k, k] += cp * out + c["UA"]
        A_[k, j * nu + i] = -c["UA"]
        if c["prev"] is not None and c["m_in"] > 0:
            A_[k, c["prev"]] = -cp * c["m_in"]
        b[k] = cp * c["add"] * inlet_C
        # plate coupling term on the plate row
        kp = j * nu + i
        A_[kp, kp] += c["UA"]
        A_[kp, k] = -c["UA"]

    T = spsolve(A_.tocsr(), b)
    T_s = T[:np_].reshape(nv, nu)
    T_f = T[np_:]

    # --- post ---------------------------------------------------------------
    r_tim = inputs.tim_r_m2K_W
    T_die = T_s + qpp * (t_b / (2 * k_s) + r_tim)
    uc = 0.5 * (ue[:-1] + ue[1:])
    vc = 0.5 * (ve[:-1] + ve[1:])

    def v_of(s):
        if axis == "x":
            return s.y0_mm, s.y0_mm + s.height_mm
        return s.x0_mm, s.x0_mm + s.width_mm

    def u_of(s):
        if axis == "x":
            return s.x0_mm, s.x0_mm + s.width_mm
        return s.y0_mm, s.y0_mm + s.height_mm

    comps = []
    for s in inputs.sources:
        u_lo, u_hi = u_of(s)
        v_lo, v_hi = v_of(s)
        mask = (uc[None, :] >= u_lo) & (uc[None, :] <= u_hi) & (
            vc[:, None] >= v_lo
        ) & (vc[:, None] <= v_hi)
        tmax = float(T_die[mask].max()) if mask.any() else float("nan")
        tmean = float(T_die[mask].mean()) if mask.any() else float("nan")
        comps.append({
            "name": s.name, "type": s.type, "power_W": s.power_W,
            "max_C": tmax, "mean_C": tmean,
            "R_th_K_per_W": (tmax - inlet_C) / s.power_W if s.power_W else None,
        })

    leave_sum = sum(c["leave"] for c in coeffs)
    T_out = (
        sum(c["leave"] * T_f[k] for k, c in enumerate(coeffs)) / leave_sum
        if leave_sum > 0 else inlet_C
    )
    heat_fluid = sum(c["UA"] * (T_s[c["j"], c["i"]] - T_f[k]) for k, c in enumerate(coeffs))
    P_in = sum(s.power_W for s in inputs.sources)

    # fields for the dashboard (optional)
    T_f_grid = np.full((nv, nu), np.nan)
    vel = np.full((nv, nu), np.nan)
    for (pi, j, i), idx in fnodes.items():
        k = idx - np_
        c = coeffs[k]
        T_f_grid[c["j"], c["i"]] = T_f[k] if np.isnan(T_f_grid[c["j"], c["i"]]) else T_f_grid[c["j"], c["i"]]
        path = layout.paths[pi]
        r = _path_r(path, 0.5 * (ue[c["i"]] + ue[c["i"] + 1]))
        zi = min(zones_v, key=lambda z: abs((z["v0"] + z["v1"]) / 2 - vc[c["j"]]) if z["v0"] <= vc[c["j"]] <= z["v1"] else 1e9) if zones_v else None
        if zi is not None and zi["A"] > 0:
            vel[c["j"], c["i"]] = path.get("direction", 1) * zi["q"] / zi["A"] * r

    def _type_max(tp):
        vals = [c["max_C"] for c in comps if c["type"] == tp and not math.isnan(c["max_C"])]
        return max(vals) if vals else float("nan")

    crit = max(comps, key=lambda c: c["max_C"] if not math.isnan(c["max_C"]) else -1) if comps else None
    return ThermalResult(
        components=comps,
        gpu_max_C=_type_max("GPU"),
        hbm_max_C=_type_max("HBM"),
        critical_name=crit["name"] if crit else "",
        critical_max_C=crit["max_C"] if crit else float("nan"),
        outlet_C=T_out,
        rise_K=T_out - inlet_C,
        heat_to_fluid_W=heat_fluid,
        energy_residual=(heat_fluid - P_in) / P_in if P_in else 0.0,
        runtime_s=time.perf_counter() - t0,
        T_s=T_s if want_fields else None,
        T_die=T_die if want_fields else None,
        T_f=T_f_grid if want_fields else None,
        velocity_u=vel if want_fields else None,
        grid={"du_mm": du, "dv_mm": dv, "nu": nu, "nv": nv, "u_edges": ue, "v_edges": ve} if want_fields else {},
        zones=[{k: z[k] for k in ("label", "v0", "v1", "U", "h", "eta", "h_eff", "Re", "Nu", "n_ch")} for z in zones_v],
        mdot_total_kg_s=sum(mdot_by_path_row.values()),
    )
