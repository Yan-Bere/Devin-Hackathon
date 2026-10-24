"""Static PNG renders for Stage 2 results (no WebGL / Vega dependency)."""

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from mpl_toolkits.mplot3d.art3d import Poly3DCollection  # noqa: E402

BG, PANEL, BORDER, TEXT, MUTED = "#0B1220", "#111A2E", "#1E2A44", "#E6EDF7", "#8FA3BF"
CYAN, ORANGE, GREEN, GRAY = "#22D3EE", "#F97316", "#22C55E", "#55657F"


def _style(ax):
    ax.set_facecolor(PANEL)
    for spine in ax.spines.values():
        spine.set_color(BORDER)
    ax.tick_params(colors=MUTED, labelsize=11)
    ax.grid(color=BORDER, linewidth=0.8)


def pareto_png(result, out_path):
    fig, ax = plt.subplots(figsize=(8, 4.6), dpi=110, facecolor=PANEL)
    _style(ax)
    evals = result.get("evaluations", [])
    for feasible, color, label in ((False, GRAY, "candidate (infeasible)"), (True, CYAN, "candidate (feasible)")):
        pts = [(e["delta_p_nominal_kPa"], e["T_hbm_max_C"]) for e in evals if bool(e["feasible"]) == feasible]
        if pts:
            x, y = zip(*pts)
            ax.scatter(x, y, s=10, c=color, alpha=0.55, linewidths=0, label=label)
    for key, color, marker, label in (("baseline", ORANGE, "s", "baseline"), ("optimized", GREEN, "*", "optimum")):
        rec = result.get(key)
        if rec:
            ax.scatter([rec["delta_p_nominal_kPa"]], [rec["T_hbm_max_C"]], s=220 if marker == "*" else 110,
                       c=color, marker=marker, edgecolors=BG, linewidths=1.2, label=label, zorder=5)
    ax.set_xlabel("ΔP at nominal flow (kPa)", color=TEXT, fontsize=12)
    ax.set_ylabel("Worst HBM max temperature (°C)", color=TEXT, fontsize=12)
    ax.set_title("Pareto candidates", color=TEXT, fontsize=13, fontweight="bold")
    leg = ax.legend(facecolor=PANEL, edgecolor=BORDER, fontsize=10, loc="upper right")
    for t in leg.get_texts():
        t.set_color(TEXT)
    fig.tight_layout()
    fig.savefig(out_path, facecolor=PANEL)
    plt.close(fig)
    return str(out_path)


def plate_png(stl_path, out_path):
    if not stl_path or not Path(stl_path).exists():
        return None
    import trimesh

    mesh = trimesh.load(stl_path, force="mesh")
    elev, azim = np.radians(32), np.radians(-55)
    eye = np.array([np.cos(elev) * np.cos(azim), np.cos(elev) * np.sin(azim), np.sin(elev)])
    visible = mesh.face_normals @ eye > 1e-6
    faces, normals = mesh.faces[visible], mesh.face_normals[visible]
    tris = mesh.vertices[faces]
    light = np.array([0.4, -0.5, 0.75])
    light /= np.linalg.norm(light)
    shade = np.clip(normals @ light, 0, 1) * 0.65 + 0.35
    top = np.array(matplotlib.colors.to_rgb(CYAN))
    metal = np.array(matplotlib.colors.to_rgb("#B8C4D6"))
    is_fin_top = (normals[:, 2] > 0.9) & (tris[:, :, 2].min(axis=1) > mesh.bounds[0][2] + 2.5)
    colors = np.clip(shade[:, None] * np.where(is_fin_top[:, None], top, metal), 0, 1)
    fig = plt.figure(figsize=(7, 5.2), dpi=110, facecolor=PANEL)
    ax = fig.add_subplot(111, projection="3d", facecolor=PANEL)
    ax.add_collection3d(Poly3DCollection(tris, facecolors=colors, edgecolors="none"))
    lo, hi = mesh.bounds
    span = (hi - lo).max()
    mid = (hi + lo) / 2
    ax.set_xlim(mid[0] - span / 2, mid[0] + span / 2)
    ax.set_ylim(mid[1] - span / 2, mid[1] + span / 2)
    ax.set_zlim(lo[2], lo[2] + span / 4)
    ax.set_box_aspect((1, 1, 0.25))
    ax.view_init(elev=32, azim=-55)
    ax.set_axis_off()
    ax.set_title("Optimized cold plate (STL render)", color=TEXT, fontsize=13, fontweight="bold")
    fig.tight_layout()
    fig.savefig(out_path, facecolor=PANEL)
    plt.close(fig)
    return str(out_path)
