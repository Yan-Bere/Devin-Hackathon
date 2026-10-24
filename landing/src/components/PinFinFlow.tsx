import { useEffect, useRef, useState } from "react";

// Logical simulation space (scaled to device pixels at render time).
const W = 1200, H = 560, WALL = 34, R = 10;
const G = 2, GW = W / G, GH = H / G;
const U0 = 2.6;
const FX0 = 170, FX1 = 1030;
const N = 6500;
const T_IN = 25, T_SPAN = 60;

type Pin = { x: number; y: number };
type Source = { x: number; y: number; w: number; h: number; q: number; label: string };

const SOURCES: Source[] = [
  { x: 480, y: 280, w: 130, h: 150, q: 1, label: "GPU1 · 554 W" },
  { x: 720, y: 280, w: 130, h: 150, q: 1, label: "GPU2 · 554 W" },
  ...[430, 530, 670, 770].flatMap((x, i) => [
    { x, y: 132, w: 60, h: 54, q: 0.42, label: `H${i + 1}` },
    { x, y: 428, w: 60, h: 54, q: 0.42, label: `H${i + 5}` },
  ]),
];

const STOPS: [number, [number, number, number]][] = [
  [0, [56, 189, 248]],
  [0.28, [34, 211, 238]],
  [0.5, [167, 243, 208]],
  [0.68, [253, 224, 71]],
  [0.84, [251, 146, 60]],
  [1, [239, 68, 68]],
];
function cmap(t: number): [number, number, number] {
  t = Math.min(1, Math.max(0, t));
  for (let i = 1; i < STOPS.length; i++) {
    const [t1, c1] = STOPS[i];
    const [t0, c0] = STOPS[i - 1];
    if (t <= t1) {
      const f = (t - t0) / (t1 - t0);
      return [c0[0] + (c1[0] - c0[0]) * f, c0[1] + (c1[1] - c0[1]) * f, c0[2] + (c1[2] - c0[2]) * f];
    }
  }
  return STOPS[STOPS.length - 1][1];
}
const smooth = (a: number, b: number, x: number) => {
  const t = Math.min(1, Math.max(0, (x - a) / (b - a)));
  return t * t * (3 - 2 * t);
};

function makePins(): Pin[] {
  const pins: Pin[] = [];
  const sx = 44, sy = 24;
  const y0 = WALL + 22, y1 = H - WALL - 22;
  const rows = Math.floor((y1 - y0) / sy) + 1;
  const oy = (y1 - y0 - (rows - 1) * sy) / 2;
  for (let r = 0; r < rows; r++) {
    const y = y0 + oy + r * sy;
    for (let x = FX0 + (r % 2 ? sx / 2 : 0); x <= FX1; x += sx) pins.push({ x, y });
  }
  return pins;
}

function buildFields(pins: Pin[]) {
  const n = GW * GH;
  // Stream functions keep the field divergence-free, so particles never bunch into lanes.
  const psi = new Float64Array(n);
  const wa = new Float64Array(n), wb = new Float64Array(n);
  const mask = new Int16Array(n);
  const heat = new Float32Array(n);
  const RW = 4.2 * R, WL = 7 * R, K = (2 * Math.PI) / (4.5 * R);

  for (let gy = 0; gy < GH; gy++)
    for (let gx = 0; gx < GW; gx++) {
      const x = gx * G, y = gy * G, k = gy * GW + gx;
      psi[k] = y;
      let q = 0;
      for (const s of SOURCES) {
        const bx = 1 / (1 + Math.exp(-(s.w / 2 - Math.abs(x - s.x)) / 16));
        const by = 1 / (1 + Math.exp(-(s.h / 2 - Math.abs(y - s.y)) / 16));
        q += s.q * bx * by;
      }
      heat[k] = q;
    }
  let hmax = 0;
  for (let k = 0; k < n; k++) hmax = Math.max(hmax, heat[k]);
  for (let k = 0; k < n; k++) heat[k] /= hmax;

  pins.forEach((p, idx) => {
    const phase = idx * 2.399;
    const gx0 = Math.max(0, Math.floor((p.x - RW) / G)), gx1 = Math.min(GW - 1, Math.ceil((p.x + WL) / G));
    const gy0 = Math.max(0, Math.floor((p.y - RW) / G)), gy1 = Math.min(GH - 1, Math.ceil((p.y + RW) / G));
    for (let gy = gy0; gy <= gy1; gy++)
      for (let gx = gx0; gx <= gx1; gx++) {
        const k = gy * GW + gx;
        const dx = gx * G - p.x, dy = gy * G - p.y, r2 = dx * dx + dy * dy;
        if (r2 < R * R) mask[k] = idx + 1;
        const r = Math.sqrt(r2);
        if (r < RW && r > 1e-3) {
          const w = 1 - smooth(2.4 * R, RW, r);
          psi[k] -= (w * R * R * dy) / Math.max(r2, R * R * 0.6);
        }
        if (dx > 0) {
          const a = smooth(R + 1, 1.8 * R, r) * 0.45 * R * smooth(0.6 * R, 1.6 * R, dx) * Math.exp(-(dx - R) / (2.6 * R)) * Math.exp(-(dy * dy) / (R * R * 1.1)) * (1 - smooth(5 * R, WL, dx));
          wa[k] += a * Math.cos(phase - K * dx);
          wb[k] += a * Math.sin(phase - K * dx);
        }
      }
  });

  // Relax psi to the true potential flow: walls and pins are streamlines (SOR on the Laplace equation).
  const fixed = new Uint8Array(n);
  for (let gy = 0; gy < GH; gy++)
    for (let gx = 0; gx < GW; gx++) {
      const k = gy * GW + gx, y = gy * G;
      if (y <= WALL || y >= H - WALL || gx === 0 || gx === GW - 1) {
        fixed[k] = 1;
        psi[k] = Math.min(H - WALL, Math.max(WALL, y));
      } else if (mask[k]) {
        fixed[k] = 1;
        psi[k] = pins[mask[k] - 1].y;
      }
    }
  for (let it = 0; it < 450; it++)
    for (let gy = 1; gy < GH - 1; gy++)
      for (let gx = 1, k = gy * GW + 1; gx < GW - 1; gx++, k++) {
        if (fixed[k]) continue;
        psi[k] += 1.9 * (0.25 * (psi[k - 1] + psi[k + 1] + psi[k - GW] + psi[k + GW]) - psi[k]);
      }

  const curl = (f: Float64Array) => {
    const u = new Float32Array(n), v = new Float32Array(n);
    for (let gy = 1; gy < GH - 1; gy++)
      for (let gx = 1; gx < GW - 1; gx++) {
        const k = gy * GW + gx;
        u[k] = (f[k + GW] - f[k - GW]) / (2 * G);
        v[k] = -(f[k + 1] - f[k - 1]) / (2 * G);
      }
    return [u, v];
  };
  const [u, v] = curl(psi);
  const [au, av] = curl(wa);
  const [bu, bv] = curl(wb);

  for (let gy = 0; gy < GH; gy++)
    for (let gx = 0; gx < GW; gx++) {
      const k = gy * GW + gx, y = gy * G;
      if (gy === 0 || gx === 0 || gy === GH - 1 || gx === GW - 1) { u[k] = 1; v[k] = 0; }
      if (mask[k]) { u[k] = v[k] = au[k] = av[k] = bu[k] = bv[k] = 0; continue; }
      const d = Math.min(y - WALL, H - WALL - y);
      const wf = 0.35 + 0.65 * Math.sqrt(Math.min(1, Math.max(0, d / 14)));
      u[k] *= wf; v[k] *= wf; au[k] *= wf; av[k] *= wf; bu[k] *= wf; bv[k] *= wf;
    }
  return { u, v, au, av, bu, bv, mask, heat };
}

type Fields = ReturnType<typeof buildFields>;

function sample(a: Float32Array, x: number, y: number) {
  const fx = Math.min(GW - 1.001, Math.max(0, x / G));
  const fy = Math.min(GH - 1.001, Math.max(0, y / G));
  const ix = fx | 0, iy = fy | 0, tx = fx - ix, ty = fy - iy, k = iy * GW + ix;
  return (a[k] * (1 - tx) + a[k + 1] * tx) * (1 - ty) + (a[k + GW] * (1 - tx) + a[k + GW + 1] * tx) * ty;
}

function wallTemp(f: Fields, x: number, y: number) {
  const h = sample(f.heat, x, y);
  return T_IN + 8 + h * 50 + 6 * smooth(FX0, FX1, x);
}

function drawBackground(ctx: CanvasRenderingContext2D, f: Fields) {
  ctx.clearRect(0, 0, W, H);
  const hull = ctx.createLinearGradient(0, 0, 0, H);
  hull.addColorStop(0, "#1e293b");
  hull.addColorStop(0.5, "#0f172a");
  hull.addColorStop(1, "#1e293b");
  ctx.fillStyle = hull;
  ctx.beginPath();
  ctx.roundRect(0, 0, W, H, 28);
  ctx.fill();

  ctx.fillStyle = "#050a16";
  ctx.fillRect(0, WALL, W, H - 2 * WALL);

  const img = new ImageData(GW, GH);
  for (let k = 0; k < GW * GH; k++) {
    const x = (k % GW) * G, y = ((k / GW) | 0) * G;
    if (y < WALL || y > H - WALL) continue;
    const t = (wallTemp(f, x, y) - T_IN) / T_SPAN;
    const [r, g, b] = cmap(t);
    img.data[k * 4] = r; img.data[k * 4 + 1] = g; img.data[k * 4 + 2] = b;
    img.data[k * 4 + 3] = 14 + 170 * Math.pow(t, 1.6);
  }
  const off = document.createElement("canvas");
  off.width = GW; off.height = GH;
  off.getContext("2d")!.putImageData(img, 0, 0);
  ctx.save();
  ctx.imageSmoothingEnabled = true;
  ctx.imageSmoothingQuality = "high";
  ctx.drawImage(off, 0, 0, W, H);
  ctx.restore();

  // fin-plate design space + manifolds
  ctx.strokeStyle = "rgba(148,163,184,0.18)";
  ctx.setLineDash([6, 6]);
  ctx.lineWidth = 1;
  ctx.strokeRect(FX0 - 26, WALL + 6, FX1 - FX0 + 52, H - 2 * WALL - 12);
  ctx.setLineDash([]);

  // die footprints
  ctx.lineWidth = 1.2;
  for (const s of SOURCES) {
    ctx.strokeStyle = s.q === 1 ? "rgba(254,215,170,0.35)" : "rgba(254,215,170,0.22)";
    ctx.beginPath();
    ctx.roundRect(s.x - s.w / 2, s.y - s.h / 2, s.w, s.h, 6);
    ctx.stroke();
  }

  // channel walls
  for (const y of [WALL, H - WALL]) {
    ctx.strokeStyle = "rgba(148,163,184,0.35)";
    ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(W, y); ctx.stroke();
  }
}

function drawPins(ctx: CanvasRenderingContext2D, pins: Pin[], f: Fields) {
  ctx.clearRect(0, 0, W, H);
  for (const p of pins) {
    ctx.fillStyle = "rgba(0,0,0,0.45)";
    ctx.beginPath(); ctx.arc(p.x + 2.2, p.y + 3, R, 0, Math.PI * 2); ctx.fill();
  }
  for (const p of pins) {
    const hot = sample(f.heat, p.x, p.y);
    const g = ctx.createRadialGradient(p.x - R * 0.4, p.y - R * 0.45, R * 0.1, p.x, p.y, R);
    g.addColorStop(0, "#fff1dc");
    g.addColorStop(0.3, hot > 0.5 ? "#f2b27e" : "#e3a57a");
    g.addColorStop(0.75, "#a7603a");
    g.addColorStop(1, "#4a2414");
    ctx.fillStyle = g;
    ctx.beginPath(); ctx.arc(p.x, p.y, R, 0, Math.PI * 2); ctx.fill();
    ctx.strokeStyle = "rgba(255,255,255,0.16)";
    ctx.lineWidth = 0.8;
    ctx.stroke();
  }
  ctx.font = "600 11px Inter, system-ui, sans-serif";
  ctx.textBaseline = "middle";
  for (const s of SOURCES.filter((s) => s.q === 1)) {
    const tw = ctx.measureText(s.label).width + 14;
    const x = s.x - tw / 2, y = s.y - s.h / 2 - 2;
    ctx.fillStyle = "rgba(2,6,23,0.82)";
    ctx.beginPath(); ctx.roundRect(x, y - 9, tw, 18, 9); ctx.fill();
    ctx.strokeStyle = "rgba(254,215,170,0.4)"; ctx.lineWidth = 1; ctx.stroke();
    ctx.fillStyle = "#fed7aa";
    ctx.fillText(s.label, x + 7, y + 0.5);
  }
}

const BUCKETS = 40;
const LUT = Array.from({ length: BUCKETS }, (_, i) => {
  const [r, g, b] = cmap(i / (BUCKETS - 1));
  return `rgba(${r | 0},${g | 0},${b | 0},0.9)`;
});

export default function PinFinFlow() {
  const wrapRef = useRef<HTMLDivElement>(null);
  const bgRef = useRef<HTMLCanvasElement>(null);
  const flowRef = useRef<HTMLCanvasElement>(null);
  const pinRef = useRef<HTMLCanvasElement>(null);
  const fieldsRef = useRef<Fields | null>(null);
  const [probe, setProbe] = useState<{ x: number; y: number; t: number; v: number } | null>(null);

  useEffect(() => {
    const wrap = wrapRef.current!, bg = bgRef.current!, flow = flowRef.current!, pinC = pinRef.current!;
    const pins = makePins();
    const f = buildFields(pins);
    fieldsRef.current = f;
    const bctx = bg.getContext("2d")!, fctx = flow.getContext("2d")!, pctx = pinC.getContext("2d")!;
    let scale = 1;

    const resize = () => {
      const dpr = Math.min(3, Math.max(1, window.devicePixelRatio || 1));
      const cssW = wrap.clientWidth;
      const pxW = Math.round(cssW * dpr), pxH = Math.round((cssW * H / W) * dpr);
      for (const c of [bg, flow, pinC]) { c.width = pxW; c.height = pxH; }
      scale = pxW / W;
      for (const c of [bctx, fctx, pctx]) c.setTransform(scale, 0, 0, scale, 0, 0);
      drawBackground(bctx, f);
      drawPins(pctx, pins, f);
    };
    resize();
    const ro = new ResizeObserver(resize);
    ro.observe(wrap);

    const px = new Float32Array(N), py = new Float32Array(N), ox = new Float32Array(N), oy = new Float32Array(N);
    const temp = new Float32Array(N), age = new Uint16Array(N);
    const spawn = (i: number, x: number) => {
      px[i] = ox[i] = x;
      py[i] = oy[i] = WALL + 3 + Math.random() * (H - 2 * WALL - 6);
      temp[i] = 0;
      age[i] = 0;
    };
    for (let i = 0; i < N; i++) spawn(i, -Math.random() * W);

    let t = 0;
    let sw = 0, cw = 1, vx = 0, vy = 0;
    const vel = (x: number, y: number) => {
      if (x < 0 || x >= W - G) { vx = 1; vy = 0; return; }
      vx = sample(f.u, x, y) + sw * sample(f.au, x, y) + cw * sample(f.bu, x, y);
      vy = sample(f.v, x, y) + sw * sample(f.av, x, y) + cw * sample(f.bv, x, y);
    };
    const SUB = 3;
    const step = (dt: number) => {
      t += dt / 60;
      sw = Math.sin(t * 5); cw = Math.cos(t * 5);
      const h = (dt * U0) / SUB;
      for (let i = 0; i < N; i++) {
        let x = px[i], y = py[i];
        ox[i] = x; oy[i] = y;
        for (let s = 0; s < SUB; s++) {
          vel(x, y);
          const mx = x + vx * h * 0.5, my = y + vy * h * 0.5;
          vel(mx, my);
          x += vx * h;
          y += vy * h;
        }
        y += (Math.random() - 0.5) * 0.06 * dt;
        if (y < WALL + 1.5) y = WALL + 1.5;
        if (y > H - WALL - 1.5) y = H - WALL - 1.5;
        if (x >= 0 && x < W) {
          temp[i] = Math.min(1, temp[i] + 0.019 * sample(f.heat, x, y) * dt);
          const m = f.mask[((y / G) | 0) * GW + ((x / G) | 0)];
          if (m) {
            const p = pins[m - 1];
            const dx = x - p.x, dy = y - p.y, d = Math.hypot(dx, dy) || 1;
            x = p.x + (dx / d) * (R + 0.8);
            y = p.y + (dy / d) * (R + 0.8) + (dy === 0 ? 1 : 0);
          }
        }
        px[i] = x; py[i] = y;
        age[i]++;
        if (x > W + 4 || age[i] > 3000) spawn(i, -Math.random() * 30);
      }
    };
    for (let s = 0; s < 420; s++) step(1);

    const bucketIdx = new Int32Array(N);
    const counts = new Int32Array(BUCKETS);
    const starts = new Int32Array(BUCKETS);
    const draw = () => {
      fctx.save();
      fctx.setTransform(1, 0, 0, 1, 0, 0);
      fctx.globalCompositeOperation = "destination-out";
      fctx.fillStyle = "rgba(0,0,0,0.075)";
      fctx.fillRect(0, 0, flow.width, flow.height);
      fctx.restore();
      fctx.globalCompositeOperation = "source-over";
      fctx.lineCap = "round";
      fctx.lineWidth = 1.1;

      counts.fill(0);
      const b = new Uint8Array(N);
      for (let i = 0; i < N; i++) {
        b[i] = Math.min(BUCKETS - 1, (temp[i] * (BUCKETS - 1)) | 0);
        counts[b[i]]++;
      }
      let acc = 0;
      for (let k = 0; k < BUCKETS; k++) { starts[k] = acc; acc += counts[k]; }
      const fill = starts.slice();
      for (let i = 0; i < N; i++) bucketIdx[fill[b[i]]++] = i;

      for (let k = 0; k < BUCKETS; k++) {
        if (!counts[k]) continue;
        fctx.strokeStyle = LUT[k];
        fctx.beginPath();
        for (let j = starts[k]; j < starts[k] + counts[k]; j++) {
          const i = bucketIdx[j];
          if (px[i] < 0 || age[i] === 0) continue;
          fctx.moveTo(ox[i], oy[i]);
          fctx.lineTo(px[i], py[i]);
        }
        fctx.stroke();
      }
      fctx.globalCompositeOperation = "source-over";
    };

    let raf = 0, last = performance.now(), visible = true;
    const loop = (now: number) => {
      const dt = Math.min(2.5, (now - last) / (1000 / 60));
      last = now;
      step(dt);
      draw();
      raf = requestAnimationFrame(loop);
    };
    const start = () => { if (!raf) { last = performance.now(); raf = requestAnimationFrame(loop); } };
    const stop = () => { cancelAnimationFrame(raf); raf = 0; };
    const io = new IntersectionObserver(([e]) => { visible = e.isIntersecting; visible ? start() : stop(); });
    io.observe(wrap);
    const onVis = () => (document.hidden ? stop() : visible && start());
    document.addEventListener("visibilitychange", onVis);
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
      io.disconnect();
      document.removeEventListener("visibilitychange", onVis);
      for (let s = 0; s < 40; s++) { step(1); draw(); }
    } else start();
    return () => { stop(); ro.disconnect(); io.disconnect(); document.removeEventListener("visibilitychange", onVis); };
  }, []);

  const onMove = (e: React.MouseEvent) => {
    const f = fieldsRef.current;
    const rect = wrapRef.current!.getBoundingClientRect();
    const x = ((e.clientX - rect.left) / rect.width) * W;
    const y = ((e.clientY - rect.top) / rect.height) * H;
    if (!f || y < WALL || y > H - WALL) return setProbe(null);
    const sp = Math.hypot(sample(f.u, x, y), sample(f.v, x, y));
    setProbe({ x: e.clientX - rect.left, y: e.clientY - rect.top, t: wallTemp(f, x, y), v: sp * 0.62 });
  };

  return (
    <div className="relative">
      <div className="relative overflow-hidden rounded-2xl border border-slate-800 bg-slate-950">
        <div
          ref={wrapRef}
          className="relative w-full cursor-crosshair"
          role="img"
          aria-label="Animated top-down view of coolant flowing left to right through a staggered copper pin-fin array, warming as it passes over two GPU dies"
          style={{ aspectRatio: `${W} / ${H}` }}
          onMouseMove={onMove}
          onMouseLeave={() => setProbe(null)}
        >
          <canvas ref={bgRef} className="absolute inset-0 h-full w-full" />
          <canvas ref={flowRef} className="absolute inset-0 h-full w-full" />
          <canvas ref={pinRef} className="absolute inset-0 h-full w-full" />

          <div className="pointer-events-none absolute left-4 top-1/2 -translate-y-1/2 text-[10px] font-semibold uppercase tracking-[0.25em] text-cyan-200/80 md:left-6 md:text-xs">
            Inlet<div className="mt-1 font-display text-sm normal-case tracking-normal text-cyan-100 md:text-base">25 °C</div>
          </div>
          <div className="pointer-events-none absolute right-4 top-1/2 -translate-y-1/2 text-right text-[10px] font-semibold uppercase tracking-[0.25em] text-orange-200/80 md:right-6 md:text-xs">
            Outlet<div className="mt-1 font-display text-sm normal-case tracking-normal text-orange-100 md:text-base">→</div>
          </div>

          {probe && (
            <div
              className="pointer-events-none absolute z-10 -translate-x-1/2 -translate-y-[calc(100%+14px)] whitespace-nowrap rounded-md border border-slate-700 bg-slate-900 px-3 py-1.5 font-mono text-xs"
              style={{ left: probe.x, top: probe.y }}
            >
              <span className="text-orange-200">{probe.t.toFixed(1)} °C</span>
              <span className="mx-2 text-slate-600">|</span>
              <span className="text-cyan-200">{probe.v.toFixed(2)} m/s</span>
              <span className="ml-2 text-slate-500">model est.</span>
            </div>
          )}
        </div>

        <div className="flex flex-wrap items-center justify-between gap-x-6 gap-y-3 border-t border-slate-800 px-5 py-3 font-mono text-[11px] text-slate-400">
          <div>
            <span className="text-slate-200">Illustrative flow model</span>
            <span className="text-slate-500"> · staggered copper pin fins · water · not solver output</span>
          </div>
          <div className="flex items-center gap-3">
            <span>25 °C</span>
            <div className="h-1.5 w-32 rounded-full" style={{ background: `linear-gradient(90deg, ${STOPS.map(([s, c]) => `rgb(${c.join(",")}) ${s * 100}%`).join(",")})` }} />
            <span>85 °C</span>
          </div>
          <div>
            Balanced sample: <span className="text-cyan-200">2.1 psi</span> · <span className="text-orange-200">77.4 °C GPU</span>
          </div>
        </div>
      </div>
    </div>
  );
}
