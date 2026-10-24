"""Parallel-channel hydraulic solver (laminar Shah&London / turbulent Petukhov).

Each channel-half follows its path's ramp profile r(u): flow per channel
ramps 0->q over the inlet opening, stays q over the covered part, ramps
q->0 over the outlet opening. All channel-paths are in parallel between
the manifolds; opening losses use K=1 on Q/(total opening through-area).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
from scipy.optimize import brentq

from coldplate.geometry import Layout, path_ramp

K_TURN = 1.0  # lumped manifold-to-channel turn + contraction/expansion loss
_RE1, _RE2 = 2300.0, 4000.0
_GL_X, _GL_W = np.polynomial.legendre.leggauss(8)


def f_darcy_re(alpha: float, re: float) -> float:
    """Darcy friction factor (f*Re for laminar, blended to Petukhov)."""
    a = alpha
    fRe = 96.0 * (
        1 - 1.3553 * a + 1.9467 * a**2 - 1.7012 * a**3 + 0.9564 * a**4 - 0.2537 * a**5
    )
    f_lam = fRe / max(re, 1e-9)
    if re <= _RE1:
        return f_lam
    f_turb = (0.790 * math.log(re) - 1.64) ** -2
    if re >= _RE2:
        return f_turb
    w = (re - _RE1) / (_RE2 - _RE1)
    return f_lam * (1 - w) + f_turb * w


def hagenbach_k(alpha: float) -> float:
    a = alpha
    return (
        0.6796 + 1.2197 * a + 3.3089 * a**2 - 9.5921 * a**3 + 8.9089 * a**4 - 2.9959 * a**5
    )


def _ramp(path: dict, u: float) -> float:
    return path_ramp(path, u)


def _path_dp(
    q: float, path: dict, A: float, Dh: float, alpha: float,
    rho: float, mu: float,
) -> float:
    """Delta-P for one channel on this path at per-channel flow q (m3/s)."""
    total = 0.0
    V_full = q / A
    for kind, a, b in path["segments"]:
        lo, hi = min(a, b), max(a, b)
        L = hi - lo
        if L <= 0:
            continue
        # Gauss-Legendre over the segment
        us = 0.5 * (hi - lo) * _GL_X + 0.5 * (hi + lo)
        seg = 0.0
        for wgt, uu in zip(_GL_W, us):
            r = _ramp({"segments": path["segments"]}, uu)
            V = V_full * r
            re = rho * abs(V) * Dh / mu if V else 0.0
            f = f_darcy_re(alpha, re)
            seg += wgt * f * rho * V * V / (2.0 * Dh)
        total += seg * 0.5 * L * 1e-3  # L is in mm, integrand in Pa/m
    K = hagenbach_k(alpha) + K_TURN + K_TURN  # developing + manifold turns
    total += K * rho * V_full * V_full / 2.0
    return total


@dataclass
class ZoneResult:
    zone: str
    n_channels: int
    n_paths: int
    q_per_channel_m3s: float
    V_m_s: float
    Re: float
    Dh_mm: float
    flow_share: float


@dataclass
class HydraulicResult:
    dP_total_Pa: float
    dP_channels_Pa: float
    dP_openings_Pa: float
    Q_m3s: float
    zones: list[ZoneResult]
    pumping_power_W: float
    q_per_path: dict


def solve_hydraulics(layout: Layout, rho: float, mu: float, Q_m3s: float) -> HydraulicResult:
    des = layout.design
    H = des.fin_height_mm
    # group channels by zone; each channel contributes len(paths) paths
    zone_groups = {}
    for ch in layout.channels:
        zone_groups.setdefault(ch["zone"], []).append(ch)
    zdef = {z.label: z for z in des.zones}
    groups = []
    for label, chs in zone_groups.items():
        w = chs[0]["width_mm"]
        A = w * H * 1e-6  # m^2
        P = 2.0 * (w + H) * 1e-3
        Dh = 2.0 * w * H / (w + H) * 1e-3 if w + H > 0 else 0.0
        alpha = min(w, H) / max(w, H)
        n_paths = len(chs) * len(layout.paths)
        groups.append({
            "zone": label, "A": A, "Dh": Dh, "alpha": alpha,
            "n_paths": n_paths, "n_channels": len(chs), "pitch_mm": chs[0]["width_mm"] + zdef[label].fin_thickness_mm,
        })

    def dp_path_of(q, g):
        return _path_dp(q, _SINGLE_PATH, g["A"], g["Dh"], g["alpha"], rho, mu)

    _SINGLE_PATH = _canonical_path(layout)

    def q_at_dp(dp, g):
        if dp <= 0:
            return 0.0
        return brentq(lambda q: dp_path_of(q, g) - dp, 0.0, 1.0, xtol=1e-15)

    def flow_error(dp):
        return sum(g["n_paths"] * q_at_dp(dp, g) for g in groups) - Q_m3s

    # bracket
    lo, hi = 1e-6, 1.0
    while flow_error(hi) < 0:
        hi *= 2.0
        if hi > 1e12:
            raise RuntimeError("cannot bracket hydraulic solution")
    dp_channels = brentq(flow_error, lo, hi, xtol=1e-9)

    # opening losses: V = Q over total opening through-area
    L_v = (layout.v_range[1] - layout.v_range[0]) * 1e-3
    per_kind = {"inlet": 0, "outlet": 0}
    for kind in ("inlet", "outlet"):
        n_strips = len(layout.openings[kind])
        A_open = n_strips * L_v * H * 1e-3  # through-area = v-span x fin height
        V = Q_m3s / A_open if A_open > 0 else 0.0
        per_kind[kind] = K_TURN * rho * V * V / 2.0
    dp_open = per_kind["inlet"] + per_kind["outlet"]

    zones = []
    q_paths = {}
    for g in groups:
        q = q_at_dp(dp_channels, g)
        V = q / g["A"]
        Re = rho * V * g["Dh"] / mu if V else 0.0
        share = g["n_paths"] * q / Q_m3s
        q_paths[g["zone"]] = q
        zones.append(ZoneResult(
            zone=g["zone"], n_channels=g["n_channels"], n_paths=g["n_paths"],
            q_per_channel_m3s=q, V_m_s=V, Re=Re, Dh_mm=g["Dh"] * 1e3,
            flow_share=share,
        ))
    dpt = dp_channels + dp_open
    return HydraulicResult(
        dP_total_Pa=dpt,
        dP_channels_Pa=dp_channels,
        dP_openings_Pa=dp_open,
        Q_m3s=Q_m3s,
        zones=zones,
        pumping_power_W=dpt * Q_m3s,
        q_per_path=q_paths,
    )


def _canonical_path(layout: Layout) -> dict:
    """One representative path (all paths share shape/losses per zone)."""
    return layout.paths[0]
