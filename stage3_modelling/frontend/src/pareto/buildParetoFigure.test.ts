import { describe, expect, it } from "vitest";
import { buildParetoFigure } from "./buildParetoFigure";
import type { ResultsDoc } from "../types";
import sample from "../../public/sample-results.json";

const results = sample as unknown as ResultsDoc;

describe("buildParetoFigure", () => {
  it("renders 5 selected markers with design_id customdata", () => {
    const { data } = buildParetoFigure(results);
    const selTraces = (data as any[]).filter(
      (t) => t.marker?.symbol === "diamond",
    );
    expect(selTraces).toHaveLength(5);
    const ids = selTraces.map((t) => t.customdata[0]);
    expect(new Set(ids)).toEqual(
      new Set(results.selected_designs.map((s) => s.design_id)),
    );
  });

  it("front trace x is ascending and ids equal front_candidate_ids", () => {
    const { data } = buildParetoFigure(results);
    const front = (data as any[]).find((t) => t.name === "Pareto front");
    const xs = front.x as number[];
    expect([...xs].sort((a, b) => a - b)).toEqual(xs);
    const order = new Map(results.candidates.map((c) => [c.design_id, c.candidate_id]));
    expect(front.customdata.map((d: string) => order.get(d))).toEqual(
      results.pareto.front_candidate_ids,
    );
  });

  it("hides infeasible points when showInfeasible is false", () => {
    const withI = buildParetoFigure(results, { showInfeasible: true });
    const without = buildParetoFigure(results, { showInfeasible: false });
    const nInf = (d: any[]) => d.filter((t) => t.name === "infeasible").length;
    expect(nInf(withI.data as any[])).toBeGreaterThan(0);
    expect(nInf(without.data as any[])).toBe(0);
  });

  it("has limit lines at 70 C (HBM hard) and 27.6 kPa", () => {
    const { layout } = buildParetoFigure(results, {
      yMetric: "hbm_max_C",
    });
    const shapes = layout.shapes as any[];
    expect(
      shapes.some((s) => s.yref === "y" && s.y0 === 70),
    ).toBe(true);
    expect(
      shapes.some((s) => s.xref === "x" && Math.abs(s.x0 - 27.6) < 1e-9),
    ).toBe(true);
  });

  it("y-axis title and limit lines follow the chosen yMetric", () => {
    const gpu = buildParetoFigure(results, { yMetric: "gpu_max_C" });
    expect(gpu.layout.yaxis.title.text).toContain("Hottest GPU");
    const gpuShapes = gpu.layout.shapes as any[];
    // GPU hard limit is 100 C
    expect(gpuShapes.some((s) => s.yref === "y" && s.y0 === 100)).toBe(true);
    const marg = buildParetoFigure(results, { yMetric: "worst_margin_K" });
    expect(marg.layout.yaxis.title.text).toContain("margin");
    const mShapes = marg.layout.shapes as any[];
    expect(mShapes.some((s) => s.yref === "y" && s.y0 === 0)).toBe(true);
    // no temperature limit lines on the margin metric
    expect(mShapes.some((s) => s.yref === "y" && s.y0 === 70)).toBe(false);
  });

  it("the selected ring follows selectedDesignId", () => {
    const target = results.selected_designs[2].design_id;
    const { data } = buildParetoFigure(results, {
      selectedDesignId: target,
    });
    const ring = (data as any[]).find(
      (t) => t.marker?.symbol === "circle-open",
    );
    expect(ring.customdata[0]).toBe(target);
  });
});
