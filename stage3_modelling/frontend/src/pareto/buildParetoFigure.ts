import type { ResultsDoc, Candidate, SelectedDesign, Constraint } from "../types";

export type YMetric = "critical_temperature_C" | "gpu_max_C" | "hbm_max_C" | string;

export interface ParetoFigureOptions {
  selectedDesignId?: string;
  yMetric?: YMetric;
  showInfeasible?: boolean;
  showLimits?: boolean;
}

const ROLE_COLORS: Record<string, string> = {
  pressure_focused: "#1f77b4",
  pressure_leaning: "#4fa3d1",
  balanced: "#2ca02c",
  cooling_leaning: "#e0a030",
  cooling_focused: "#d62728",
  dominated: "#888888",
  infeasible: "#444444",
};

function yOf(c: Candidate, yMetric: YMetric): number {
  const v = (c.metrics as Record<string, unknown>)[yMetric];
  return typeof v === "number" ? v : NaN;
}

function hover(c: Candidate): string {
  const m = c.metrics;
  const viol = (c.violations || [])
    .map((v) => `${v.constraint}${v.component ? ":" + v.component : ""} ${v.value}>${v.limit}`)
    .join("; ");
  return (
    `<b>${c.candidate_id}</b> (${c.design_id})` +
    `<br>role: ${c.role ?? "-"} | ${c.status_label}` +
    `<br>ΔP: ${m.pressure_drop_kPa?.toFixed(3)} kPa` +
    `<br>hottest HBM: ${m.hbm_max_C?.toFixed(1)} °C (${m.hbm_hottest ?? "-"})` +
    `<br>hottest GPU: ${m.gpu_max_C?.toFixed(1)} °C (${m.gpu_hottest ?? "-"})` +
    `<br>coolant rise: ${m.coolant_rise_K?.toFixed(2)} K` +
    (viol ? `<br>violations: ${viol}` : "")
  );
}

const UNITS: Record<string, string> = {
  pressure_drop_kPa: "kPa",
  critical_temperature_C: "°C",
  gpu_max_C: "°C",
  hbm_max_C: "°C",
  coolant_rise_K: "K",
  worst_margin_K: "K",
};

const METRIC_LABELS: Record<string, string> = {
  gpu_max_C: "Hottest GPU temperature",
  hbm_max_C: "Hottest HBM temperature",
  critical_temperature_C: "Critical component temperature",
  coolant_rise_K: "Coolant outlet rise",
  worst_margin_K: "Worst hard-limit margin",
  pressure_drop_kPa: "Pressure drop",
};

export function buildParetoFigure(
  results: ResultsDoc,
  opts: ParetoFigureOptions = {},
) {
  const yMetric = opts.yMetric ?? "critical_temperature_C";
  const showInfeasible = opts.showInfeasible !== false;
  const showLimits = opts.showLimits !== false;
  const cands = results.candidates ?? [];
  const sel = results.selected_designs ?? [];
  const frontIds = results.pareto?.front_candidate_ids ?? [];

  const data: unknown[] = [];
  const byId = new Map(cands.map((c) => [c.candidate_id, c]));

  // infeasible (grey x)
  const infeas = cands.filter((c) => !c.feasible && yOf(c, yMetric) === yOf(c, yMetric));
  if (showInfeasible && infeas.length) {
    data.push({
      type: "scatter", mode: "markers", name: "infeasible",
      x: infeas.map((c) => c.metrics.pressure_drop_kPa),
      y: infeas.map((c) => yOf(c, yMetric)),
      text: infeas.map(hover), hoverinfo: "text",
      customdata: infeas.map((c) => c.design_id),
      marker: { symbol: "x", color: "#999", size: 8 },
    });
  }

  // feasible dominated (muted circles, not on the front)
  const dom = cands.filter((c) => c.feasible && !c.pareto?.nondominated);
  if (dom.length) {
    data.push({
      type: "scatter", mode: "markers", name: "feasible (dominated)",
      x: dom.map((c) => c.metrics.pressure_drop_kPa),
      y: dom.map((c) => yOf(c, yMetric)),
      text: dom.map(hover), hoverinfo: "text",
      customdata: dom.map((c) => c.design_id),
      marker: { symbol: "circle", color: "#7aa7c7", size: 8, opacity: 0.7 },
    });
  }

  // Pareto front (line + markers, sorted by x)
  const front = frontIds.map((id) => byId.get(id)).filter(Boolean) as Candidate[];
  front.sort((a, b) => a.metrics.pressure_drop_kPa - b.metrics.pressure_drop_kPa);
  if (front.length) {
    data.push({
      type: "scatter", mode: "lines+markers", name: "Pareto front",
      x: front.map((c) => c.metrics.pressure_drop_kPa),
      y: front.map((c) => yOf(c, yMetric)),
      text: front.map(hover), hoverinfo: "text",
      customdata: front.map((c) => c.design_id),
      line: { color: "#2ca02c", width: 2 },
      marker: { symbol: "circle", color: "#2ca02c", size: 9 },
    });
  }

  // selected designs (large markers, one colour per role)
  for (const s of sel as SelectedDesign[]) {
    data.push({
      type: "scatter", mode: "markers+text", name: s.role ?? "selected",
      x: [s.metrics.pressure_drop_kPa],
      y: [yOf(s, yMetric)],
      text: [s.role_label ?? s.role ?? ""], textposition: "top center",
      hovertext: [hover(s)], hoverinfo: "text",
      customdata: [s.design_id],
      marker: {
        symbol: "diamond", size: 14,
        color: ROLE_COLORS[s.role ?? ""] ?? "#9467bd",
        line: { color: "#222", width: 1 },
      },
      showlegend: true,
    });
  }

  // ring on the currently selected design
  const cur = sel.find((s) => s.design_id === opts.selectedDesignId)
    ?? cands.find((c) => c.design_id === opts.selectedDesignId);
  if (cur) {
    data.push({
      type: "scatter", mode: "markers", name: "selected",
      x: [cur.metrics.pressure_drop_kPa],
      y: [yOf(cur, yMetric)],
      customdata: [cur.design_id],
      hoverinfo: "skip",
      marker: {
        symbol: "circle-open", size: 26,
        color: "#000", line: { color: "#000", width: 3 },
      },
      showlegend: false,
    });
  }

  // limit lines follow the CHOSEN y metric, not the default objective
  const shapes: unknown[] = [];
  const yComp = results.objectives?.y?.component_type ?? null;
  // which constraint key supplies horizontal lines for this y metric?
  const yConKey =
    yMetric === "worst_margin_K" ? null
    : yMetric.endsWith("_max_C") ? yMetric                       // gpu_max_C/hbm_max_C
    : `${(yComp ?? "").toLowerCase()}_max_C`;                    // default objective
  if (showLimits) {
    if (yMetric === "worst_margin_K") {
      shapes.push({ type: "line", xref: "paper", x0: 0, x1: 1,
        yref: "y", y0: 0, y1: 0,
        line: { color: "#d62728", width: 2, dash: "dash" } });
    }
    for (const con of results.constraints ?? ([] as Constraint[])) {
      if (yConKey && con.key === yConKey) {
        if (con.limit != null) {
          shapes.push({ type: "line", xref: "paper", x0: 0, x1: 1,
            yref: "y", y0: con.limit, y1: con.limit,
            line: { color: "#d62728", width: 2, dash: "dash" } });
        }
        if (con.target != null) {
          shapes.push({ type: "line", xref: "paper", x0: 0, x1: 1,
            yref: "y", y0: con.target, y1: con.target,
            line: { color: "#e0a030", width: 1.5, dash: "dot" } });
        }
      }
      if (con.key === "pressure_drop_kPa") {
        if (con.limit != null) {
          shapes.push({ type: "line", yref: "paper", y0: 0, y1: 1,
            xref: "x", x0: con.limit, x1: con.limit,
            line: { color: "#d62728", width: 2, dash: "dash" } });
        }
        if (con.target != null) {
          shapes.push({ type: "line", yref: "paper", y0: 0, y1: 1,
            xref: "x", x0: con.target, x1: con.target,
            line: { color: "#e0a030", width: 1.5, dash: "dot" } });
        }
      }
    }
  }

  const ox = results.objectives?.x;
  const oy = results.objectives?.y;
  const yUnit = UNITS[yMetric] ?? "";
  // name the CHOSEN metric; the objective label only applies to its own key
  const yLabel =
    yMetric === oy?.key ? (oy?.label ?? yMetric)
    : (METRIC_LABELS[yMetric] ?? yMetric);
  const layout = {
    title: {
      text: `Cold-plate Pareto front — ${results.label ?? ""}`,
      font: { size: 14 },
    },
    xaxis: { title: { text: `${ox?.label ?? ox?.key ?? "x"} (${UNITS[ox?.key ?? ""] ?? ""})` } },
    yaxis: { title: { text: `${yLabel} (${yUnit})` } },
    shapes,
    margin: { t: 60, r: 20, b: 60, l: 70 },
    legend: { orientation: "h" as const, y: -0.2 },
    hovermode: "closest" as const,
  };

  return { data, layout };
}
