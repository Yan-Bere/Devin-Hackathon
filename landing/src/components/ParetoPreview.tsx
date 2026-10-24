import csv from "../../data/designs.csv?raw";

type Row = { id: string; dp: number; t: number; hbm: number };
const LIMIT = { dp: 4, t: 100, hbm: 70 };
const NAMED: Record<string, string> = { "P-LOWDP": "Min ΔP", "P-BAL": "Balanced", "P-COOL": "Min T" };

const rows: Row[] = csv
  .trim()
  .split(/\r?\n/)
  .slice(1)
  .map((l) => l.split(","))
  .map(([id, , dp, t, hbm]) => ({ id, dp: +dp, t: +t, hbm: +hbm }))
  .filter((r) => Number.isFinite(r.dp) && Number.isFinite(r.t));

const ok = (r: Row) => r.dp <= LIMIT.dp && r.t <= LIMIT.t && r.hbm <= LIMIT.hbm;
const front = (() => {
  let best = Infinity;
  return [...rows.filter(ok)].sort((a, b) => a.dp - b.dp).filter((r) => (r.t < best ? ((best = r.t), true) : false));
})();
const onFront = new Set(front.map((r) => r.id));

const W = 560, H = 380, L = 52, B = 44, T = 16, Rp = 16;
const X0 = 0.5, X1 = 4.75, Y0 = 68, Y1 = 107;
const sx = (v: number) => L + ((v - X0) / (X1 - X0)) * (W - L - Rp);
const sy = (v: number) => T + (1 - (v - Y0) / (Y1 - Y0)) * (H - T - B);

export default function ParetoPreview() {
  const infeasible = rows.filter((r) => !ok(r)).length;
  return (
    <figure className="w-full min-w-0">
      <p className="mb-2 font-mono text-[11px] text-slate-500 md:hidden">Swipe to scroll the chart →</p>
      <div className="overflow-x-auto" tabIndex={0} aria-label="Pareto chart, scrollable on small screens">
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full min-w-[500px]" role="img" aria-label="Pareto chart of pressure drop versus GPU temperature for the sample design set, highlighting the Min ΔP, Balanced and Min T designs">
        {[1, 2, 3, 4].map((v) => (
          <g key={v}>
            <line x1={sx(v)} x2={sx(v)} y1={T} y2={H - B} stroke="#1e293b" />
            <text x={sx(v)} y={H - B + 18} textAnchor="middle" className="fill-slate-500 font-mono text-[11px]">{v}</text>
          </g>
        ))}
        {[70, 80, 90, 100].map((v) => (
          <g key={v}>
            <line x1={L} x2={W - Rp} y1={sy(v)} y2={sy(v)} stroke="#1e293b" />
            <text x={L - 10} y={sy(v) + 4} textAnchor="end" className="fill-slate-500 font-mono text-[11px]">{v}</text>
          </g>
        ))}
        <text x={(L + W - Rp) / 2} y={H - 6} textAnchor="middle" className="fill-slate-400 font-mono text-[11px]">pressure drop ΔP (psi)</text>
        <text transform={`translate(14 ${(T + H - B) / 2}) rotate(-90)`} textAnchor="middle" className="fill-slate-400 font-mono text-[11px]">max GPU temperature (°C)</text>

        <line x1={sx(LIMIT.dp)} x2={sx(LIMIT.dp)} y1={T} y2={H - B} stroke="#f87171" strokeDasharray="4 4" opacity="0.7" />
        <text x={sx(LIMIT.dp) - 6} y={T + 12} textAnchor="end" className="fill-red-300 font-mono text-[10px]">4 psi limit</text>
        <line x1={L} x2={W - Rp} y1={sy(LIMIT.t)} y2={sy(LIMIT.t)} stroke="#f87171" strokeDasharray="4 4" opacity="0.7" />
        <text x={W - Rp - 4} y={sy(LIMIT.t) - 6} textAnchor="end" className="fill-red-300 font-mono text-[10px]">100 °C limit</text>

        <polyline points={front.map((r) => `${sx(r.dp)},${sy(r.t)}`).join(" ")} fill="none" stroke="#67e8f9" strokeWidth="1.5" opacity="0.6" />

        {rows.map((r) =>
          !ok(r) ? (
            <g key={r.id} stroke="#f87171" strokeWidth="1.5" opacity="0.8">
              <line x1={sx(r.dp) - 3.5} y1={sy(r.t) - 3.5} x2={sx(r.dp) + 3.5} y2={sy(r.t) + 3.5} />
              <line x1={sx(r.dp) - 3.5} y1={sy(r.t) + 3.5} x2={sx(r.dp) + 3.5} y2={sy(r.t) - 3.5} />
            </g>
          ) : NAMED[r.id] ? null : (
            <circle key={r.id} cx={sx(r.dp)} cy={sy(r.t)} r={onFront.has(r.id) ? 3.5 : 3} fill={onFront.has(r.id) ? "#67e8f9" : "#475569"} />
          ),
        )}
        {rows.filter((r) => NAMED[r.id]).map((r) => (
          <g key={r.id}>
            <circle cx={sx(r.dp)} cy={sy(r.t)} r="7" fill="#070a10" stroke="#a5f3fc" strokeWidth="2" />
            <circle cx={sx(r.dp)} cy={sy(r.t)} r="3" fill="#a5f3fc" />
            <text x={sx(r.dp) + (r.id === "P-COOL" ? -12 : 12)} y={sy(r.t) + (r.id === "P-LOWDP" ? -12 : 22)} textAnchor={r.id === "P-COOL" ? "end" : "start"} className="fill-slate-100 font-display text-[13px] font-semibold">{NAMED[r.id]}</text>
            <text x={sx(r.dp) + (r.id === "P-COOL" ? -12 : 12)} y={sy(r.t) + (r.id === "P-LOWDP" ? 3 : 36)} textAnchor={r.id === "P-COOL" ? "end" : "start"} className="fill-slate-400 font-mono text-[10px]">{r.dp} psi · {r.t} °C</text>
          </g>
        ))}
      </svg>
      </div>
      <figcaption className="mt-3 flex flex-wrap gap-x-5 gap-y-1 font-mono text-[11px] text-slate-500">
        <span><span className="mr-1.5 inline-block h-2 w-2 rounded-full bg-cyan-300" />Pareto front</span>
        <span><span className="mr-1.5 inline-block h-2 w-2 rounded-full bg-slate-600" />dominated</span>
        <span className="text-red-300/80">× {infeasible} violate limits</span>
        <span>Sample design set ({rows.length} designs), placeholder until CFD results land</span>
      </figcaption>
    </figure>
  );
}
