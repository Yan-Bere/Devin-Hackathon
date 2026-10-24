import { useMemo } from "react";

type Props = { finType: string; dp: number; tGpu: number; image?: string | null };

// Parametric top-down CFD-style visual: temperature field + animated coolant through pins/channels.
// If a real solver render exists (image), show it with the flow overlay on top.
export default function CFDView({ finType, dp, tGpu, image }: Props) {
  const W = 520, H = 360, x0 = 40, y0 = 30, w = W - 80, h = H - 60;
  const speed = Math.max(0.9, 3.2 - dp * 0.55);
  const hot = Math.min(1, Math.max(0, (tGpu - 65) / 30));
  const fins = useMemo(() => {
    if (finType === "straight") {
      return Array.from({ length: 13 }, (_, i) => ({ kind: "ch" as const, y: y0 + 14 + i * ((h - 28) / 12) }));
    }
    const out: { kind: "pin"; x: number; y: number }[] = [];
    const nx = 18, ny = 11;
    for (let i = 0; i < ny; i++)
      for (let j = 0; j < nx; j++) {
        const x = x0 + 18 + j * ((w - 36) / (nx - 1)) + (i % 2 ? (w - 36) / (nx - 1) / 2 : 0);
        if (x < x0 + w - 10) out.push({ kind: "pin", x, y: y0 + 16 + i * ((h - 32) / (ny - 1)) });
      }
    return out;
  }, [finType]);
  const streams = useMemo(
    () =>
      Array.from({ length: 18 }, (_, k) => {
        const y = y0 + 10 + k * ((h - 20) / 17);
        const a = finType === "straight" ? 0 : 5 + (k % 3) * 2;
        return { d: `M 0 ${y} C ${W * 0.3} ${y - a}, ${W * 0.45} ${y + a}, ${W * 0.55} ${y} S ${W * 0.8} ${y - a}, ${W} ${y}`, delay: (k * 0.29) % 1.6 };
      }),
    [finType]
  );
  return (
    <div className="relative overflow-hidden rounded-2xl border border-white/10 bg-slate-950">
      <svg viewBox={`0 0 ${W} ${H}`} className="block h-full w-full">
        <defs>
          <radialGradient id="cfdheat" cx="50%" cy="50%" r="55%">
            <stop offset="0%" stopColor={hot > 0.6 ? "#ef4444" : "#f97316"} stopOpacity={0.35 + hot * 0.45} />
            <stop offset="30%" stopColor="#eab308" stopOpacity={0.2 + hot * 0.25} />
            <stop offset="65%" stopColor="#22d3ee" stopOpacity="0.18" />
            <stop offset="100%" stopColor="#1d4ed8" stopOpacity="0.25" />
          </radialGradient>
          <filter id="glow" x="-10%" y="-10%" width="120%" height="120%">
            <feGaussianBlur stdDeviation="1.6" result="b" />
            <feMerge><feMergeNode in="b" /><feMergeNode in="SourceGraphic" /></feMerge>
          </filter>
          <linearGradient id="cfdflow" x1="0" x2="1">
            <stop offset="0%" stopColor="#a5f3fc" />
            <stop offset="60%" stopColor="#38bdf8" />
            <stop offset="100%" stopColor="#f472b6" />
          </linearGradient>
        </defs>
        {image ? (
          <image href={image} x={x0} y={y0} width={w} height={h} preserveAspectRatio="xMidYMid slice" opacity="0.95" />
        ) : (
          <rect x={x0} y={y0} width={w} height={h} rx="10" fill="url(#cfdheat)" />
        )}
        <rect x={x0} y={y0} width={w} height={h} rx="10" fill="none" stroke="rgba(148,163,184,0.35)" />
        {!image &&
          fins.map((f, i) =>
            f.kind === "ch" ? (
              <rect key={i} x={x0 + 8} y={f.y} width={w - 16} height="3" rx="1.5" fill="#cbd5e1" fillOpacity="0.55" />
            ) : (
              <circle key={i} cx={f.x} cy={f.y} r="4" fill="#cbd5e1" fillOpacity="0.7" />
            )
          )}
        <g filter="url(#glow)">
          {streams.map((s, i) => (
            <g key={i}>
              <path d={s.d} fill="none" stroke="rgba(56,189,248,0.12)" strokeWidth="5" />
              <path d={s.d} fill="none" stroke="url(#cfdflow)" strokeWidth="2.4" strokeLinecap="round" strokeDasharray="10 34">
                <animate attributeName="stroke-dashoffset" from="88" to="0" dur={`${speed / 3}s`} begin={`${s.delay}s`} repeatCount="indefinite" />
              </path>
            </g>
          ))}
        </g>
      </svg>
      <div className="absolute bottom-3 right-3 flex items-center gap-2 rounded-lg bg-slate-900/80 px-2 py-1 text-[10px] text-slate-400 backdrop-blur">
        <span>25 °C</span>
        <span className="h-2 w-24 rounded-full bg-gradient-to-r from-blue-600 via-cyan-400 via-yellow-400 to-red-500" />
        <span>{tGpu.toFixed(0)} °C</span>
      </div>
      <div className="absolute left-3 top-3 rounded-lg bg-slate-900/80 px-2 py-1 text-[10px] uppercase tracking-widest text-cyan-300 backdrop-blur">
        {finType === "straight" ? "Straight channels" : "Pin fins"} · velocity streamlines
      </div>
    </div>
  );
}
