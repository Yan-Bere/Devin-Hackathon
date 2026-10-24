import { useEffect, useRef } from "react";
import Plotly from "plotly.js-dist-min";
import { buildParetoFigure, type YMetric } from "./buildParetoFigure";
import type { ResultsDoc, Candidate } from "../types";

export interface ParetoChartProps {
  results: ResultsDoc;
  selectedDesignId?: string;
  onSelectDesign?: (designId: string, candidate?: Candidate) => void;
  yMetric?: YMetric;
  height?: number;
  showInfeasible?: boolean;
  showLimits?: boolean;
}

export function ParetoChart({
  results,
  selectedDesignId,
  onSelectDesign,
  yMetric,
  height = 520,
  showInfeasible = true,
  showLimits = true,
}: ParetoChartProps) {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!ref.current) return;
    const { data, layout } = buildParetoFigure(results, {
      selectedDesignId, yMetric, showInfeasible, showLimits,
    });
    const gd = ref.current as unknown as { on?: (ev: string, fn: (e: any) => void) => void };
    void Plotly.react(ref.current!, data as Plotly.Data[], layout as Partial<Plotly.Layout>, {
      displayModeBar: false, responsive: true,
    });
    const handler = (e: any) => {
      const pt = e?.points?.[0];
      const did = pt?.customdata;
      if (did && onSelectDesign) {
        const cand =
          results.candidates.find((c) => c.design_id === did) ??
          results.selected_designs.find((s) => s.design_id === did);
        onSelectDesign(did, cand as Candidate | undefined);
      }
    };
    (ref.current as any).on?.("plotly_click", handler);
    return () => {
      void Plotly.purge(ref.current!);
    };
  }, [results, selectedDesignId, yMetric, showInfeasible, showLimits, onSelectDesign]);

  const sel = results.selected_designs ?? [];
  return (
    <div className="pareto-chart">
      <div ref={ref} style={{ height }} role="img"
           aria-label="Pareto chart of pressure drop vs temperature" />
      <div className="design-buttons" role="group" aria-label="Selected designs">
        {sel.map((s) => (
          <button
            key={s.design_id}
            type="button"
            className="design-button"
            aria-pressed={s.design_id === selectedDesignId}
            onClick={() => onSelectDesign?.(s.design_id, s)}
          >
            <b>{s.role_label ?? s.role}</b> — {s.metrics.pressure_drop_kPa.toFixed(2)} kPa,
            HBM {s.metrics.hbm_max_C?.toFixed(1)} °C
          </button>
        ))}
      </div>
    </div>
  );
}
