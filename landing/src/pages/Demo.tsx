import { useEffect, useMemo, useRef, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { Link } from "react-router-dom";
import {
  Snowflake, Send, Paperclip, Check, Loader2, FileImage, Box, Grid3x3, Waves, Sparkles,
  Download, Gauge, Thermometer, Scale, Activity, Radio,
} from "lucide-react";
import {
  ScatterChart, Scatter, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, ReferenceLine, Line, ComposedChart,
} from "recharts";
import CFDView from "../components/CFDView";

type Stage = "chat" | "upload" | "dashboard" | "pareto";
type Msg = { role: "user" | "assistant"; text: string };
type Design = { id: string; fin_type: string; dp_psi: number; t_gpu_c: number; t_hbm_c: number };
type Pkg = { name: string; limits: { dp_psi: number; t_gpu_c: number; t_hbm_c: number }; components: { id: string; type: string; size_mm: number[]; power_w: number }[] };

const DEFAULT_PROMPT = "Let's build a pin-fin cold plate for a dual-GPU AI server rack. Water at 25 °C inlet, 1.5 LPM.";
const FALLBACK_REPLY =
  "Got it. I've noted your coolant, inlet temperature, and flow rate, and I'll hold the design to 4 psi, 100 °C on the GPUs, and 70 °C on the HBM. That's everything I need. Drop in your package diagram and I'll set up the CAD, meshing, and CFD for you.";
const ASSISTANT_INSTRUCTIONS =
  "You are ColdShock AI, a warm, proactive engineering assistant for liquid-cooled cold plate design. " +
  "Reply in ONE short message (2-3 sentences, no markdown, no code, do not use tools or open any repos). " +
  "Confirm the user's requirements back to them (coolant, inlet temperature, flow rate, limits of 4 psi pressure drop, 100 C GPU, 70 C HBM), " +
  "tell them you have everything you need, and ask them to upload their package diagram so you can take care of the rest. User says: ";

const LIVE_TIMEOUT_MS = 25000;

function useDemoData() {
  const [designs, setDesigns] = useState<Design[]>([]);
  const [pkg, setPkg] = useState<Pkg | null>(null);
  useEffect(() => {
    fetch("/api/demo-data").then((r) => (r.ok ? r.json() : [])).then((d) => setDesigns(Array.isArray(d) ? d : d.rows ?? [])).catch(() => {});
    fetch("/data/package.json").then((r) => r.json()).then(setPkg).catch(() => {});
  }, []);
  return { designs, pkg };
}

const feasible = (d: Design, l: Pkg["limits"]) => d.dp_psi <= l.dp_psi && d.t_gpu_c <= l.t_gpu_c && d.t_hbm_c <= l.t_hbm_c;

function paretoFront(ds: Design[]) {
  const sorted = [...ds].sort((a, b) => a.dp_psi - b.dp_psi);
  const front: Design[] = [];
  let best = Infinity;
  for (const d of sorted) if (d.t_gpu_c < best) { front.push(d); best = d.t_gpu_c; }
  return front;
}

function pickThree(front: Design[]) {
  if (!front.length) return null;
  const minDp = front[0], minT = front[front.length - 1];
  const [dpLo, dpHi] = [minDp.dp_psi, minT.dp_psi], [tLo, tHi] = [minT.t_gpu_c, minDp.t_gpu_c];
  const norm = (d: Design) => Math.hypot((d.dp_psi - dpLo) / (dpHi - dpLo || 1), (d.t_gpu_c - tLo) / (tHi - tLo || 1));
  const inner = front.slice(1, -1);
  const balanced = (inner.length ? inner : front).reduce((a, b) => (norm(b) < norm(a) ? b : a));
  return { minDp, balanced, minT };
}

export default function Demo() {
  const [stage, setStage] = useState<Stage>("chat");
  const { designs, pkg } = useDemoData();
  return (
    <div className="relative min-h-screen overflow-hidden bg-[#05070d] text-slate-100">
      <div className="pointer-events-none fixed inset-0 bg-[radial-gradient(ellipse_70%_50%_at_50%_-10%,rgba(34,211,238,0.15),transparent_60%)]" />
      <header className="relative z-10 flex items-center justify-between border-b border-white/5 px-6 py-4">
        <Link to="/" className="flex items-center gap-2">
          <div className="grid h-7 w-7 place-items-center rounded-lg bg-gradient-to-br from-cyan-300 to-blue-500"><Snowflake className="h-4 w-4 text-slate-950" /></div>
          <span className="font-display font-semibold">ColdShock<span className="text-cyan-300"> AI</span></span>
        </Link>
        <Stepper stage={stage} />
        <div className="w-32" />
      </header>
      <main className="relative z-10 mx-auto max-w-7xl px-6 py-8">
        <AnimatePresence mode="wait">
          {(stage === "chat" || stage === "upload") && (
            <motion.div key="chat" exit={{ opacity: 0, y: -20 }}>
              <ChatStage stage={stage} pkg={pkg} onReady={() => setStage("upload")} onUploaded={() => setStage("dashboard")} />
            </motion.div>
          )}
          {stage === "dashboard" && (
            <motion.div key="dash" initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -20 }}>
              <Dashboard total={designs.length || 40} onDone={() => setStage("pareto")} />
            </motion.div>
          )}
          {stage === "pareto" && (
            <motion.div key="pareto" initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }}>
              <ParetoStage designs={designs} pkg={pkg} />
            </motion.div>
          )}
        </AnimatePresence>
      </main>
    </div>
  );
}

function Stepper({ stage }: { stage: Stage }) {
  const order: Stage[] = ["chat", "upload", "dashboard", "pareto"];
  const labels = ["Describe", "Upload", "Simulate", "Optimize"];
  const idx = order.indexOf(stage);
  return (
    <div className="hidden items-center gap-2 md:flex">
      {labels.map((l, i) => (
        <div key={l} className="flex items-center gap-2">
          <div className={`flex items-center gap-2 rounded-full px-3 py-1 text-xs font-medium transition ${i < idx ? "bg-cyan-300/15 text-cyan-200" : i === idx ? "bg-white text-slate-950" : "text-slate-500"}`}>
            {i < idx ? <Check className="h-3 w-3" /> : <span>{i + 1}</span>} {l}
          </div>
          {i < labels.length - 1 && <div className={`h-px w-6 ${i < idx ? "bg-cyan-300/50" : "bg-white/10"}`} />}
        </div>
      ))}
    </div>
  );
}

/* ---------------- Chat + upload ---------------- */

function ChatStage({ stage, pkg, onReady, onUploaded }: { stage: Stage; pkg: Pkg | null; onReady: () => void; onUploaded: () => void }) {
  const [msgs, setMsgs] = useState<Msg[]>([
    { role: "assistant", text: "Hi, I'm ColdShock AI. Tell me what you're cooling and I'll handle the CAD, CFD, and optimization." },
  ]);
  const [input, setInput] = useState(DEFAULT_PROMPT);
  const [thinking, setThinking] = useState(false);
  const [live, setLive] = useState<boolean | null>(null);
  const [file, setFile] = useState<{ name: string; url: string; at: number } | null>(null);
  const [scanned, setScanned] = useState(0);
  const fileRef = useRef<HTMLInputElement>(null);
  const endRef = useRef<HTMLDivElement>(null);
  useEffect(() => endRef.current?.scrollIntoView({ behavior: "smooth" }), [msgs, thinking, file, scanned]);
  useEffect(() => { fetch("/api/health").then((r) => r.json()).then((h) => setLive(!!h.devinConfigured)).catch(() => setLive(false)); }, []);

  async function askDevin(text: string): Promise<string | null> {
    if (!live) return null;
    try {
      const start = await fetch("/api/chat/start", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ prompt: ASSISTANT_INSTRUCTIONS + text }) });
      if (!start.ok) return null;
      const { sessionId } = await start.json();
      const deadline = Date.now() + LIVE_TIMEOUT_MS;
      while (Date.now() < deadline) {
        await new Promise((r) => setTimeout(r, 1500));
        const r = await fetch(`/api/chat/${sessionId}/messages`);
        if (!r.ok) continue;
        const { messages } = await r.json();
        const reply = [...(messages ?? [])].reverse().find((m: Msg) => m.role === "assistant" && m.text?.trim());
        if (reply) return reply.text;
      }
    } catch { /* fall through */ }
    return null;
  }

  async function send() {
    const text = input.trim();
    if (!text || thinking) return;
    setMsgs((m) => [...m, { role: "user", text }]);
    setInput("");
    setThinking(true);
    const reply = (await askDevin(text)) ?? (await new Promise<string>((r) => setTimeout(() => r(FALLBACK_REPLY), 1600)));
    setThinking(false);
    setMsgs((m) => [...m, { role: "assistant", text: reply }]);
    onReady();
  }

  function handleFile(f: File) {
    setFile({ name: f.name, url: URL.createObjectURL(f), at: msgs.length });
    const n = pkg?.components.length ?? 10;
    let i = 0;
    const t = setInterval(() => {
      i += 1; setScanned(i);
      if (i >= n) {
        clearInterval(t);
        setMsgs((m) => [...m, { role: "assistant", text: `Diagram parsed: ${n} heat sources, ${pkg ? pkg.components.reduce((s, c) => s + c.power_w, 0).toFixed(0) : "1493"} W in total. Generating fin geometry and launching CFD now.` }]);
        setTimeout(onUploaded, 2200);
      }
    }, 180);
  }

  const fileCard = file && (

          <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="grid gap-4 rounded-2xl border border-white/10 bg-slate-900/70 p-4 md:grid-cols-[200px_1fr]">
            <div className="relative overflow-hidden rounded-xl bg-white">
              <img src={file.url} alt={file.name} className="h-full w-full object-contain" />
              {scanned < (pkg?.components.length ?? 10) && <motion.div className="absolute inset-x-0 h-1 bg-cyan-400 shadow-[0_0_20px_#22d3ee]" animate={{ top: ["0%", "100%"] }} transition={{ duration: 1.2, repeat: Infinity }} />}
            </div>
            <div>
              <div className="mb-2 text-xs uppercase tracking-widest text-slate-500">Detected heat sources</div>
              <div className="grid grid-cols-2 gap-1.5 text-sm">
                {(pkg?.components ?? []).slice(0, scanned).map((c) => (
                  <motion.div key={c.id} initial={{ opacity: 0, x: -6 }} animate={{ opacity: 1, x: 0 }} className="flex items-center justify-between rounded-lg bg-white/5 px-2.5 py-1.5">
                    <span className={c.type === "GPU" ? "text-orange-300" : "text-cyan-200"}>{c.id}</span>
                    <span className="text-slate-400">{c.power_w} W</span>
                  </motion.div>
                ))}
              </div>
            </div>
          </motion.div>
        );
  return (
    <div className="mx-auto flex h-[calc(100vh-140px)] max-w-3xl flex-col rounded-3xl border border-white/10 bg-white/[0.03] backdrop-blur-xl">
      <div className="flex items-center justify-between border-b border-white/5 px-6 py-4">
        <div className="flex items-center gap-3">
          <div className="relative grid h-9 w-9 place-items-center rounded-full bg-gradient-to-br from-cyan-300 to-blue-500">
            <Sparkles className="h-4 w-4 text-slate-950" />
            <span className="absolute -bottom-0.5 -right-0.5 h-3 w-3 rounded-full border-2 border-slate-950 bg-emerald-400" />
          </div>
          <div><div className="font-semibold">ColdShock Assistant</div><div className="text-xs text-slate-500">Thermal design copilot</div></div>
        </div>
        {live !== null && (
          <span className={`rounded-full px-2.5 py-1 text-[10px] font-semibold uppercase tracking-wider ${live ? "bg-emerald-400/15 text-emerald-300" : "bg-slate-700/40 text-slate-400"}`}>
            {live ? "Live · Devin API" : "Offline mode"}
          </span>
        )}
      </div>
      <div className="flex-1 space-y-4 overflow-y-auto px-6 py-6">
        {msgs.map((m, i) => (
          <div key={i} className="space-y-4">
          {file && file.at === i && fileCard}
          <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} className={`flex ${m.role === "user" ? "justify-end" : ""}`}>
            <div className={`max-w-[80%] rounded-2xl px-4 py-3 leading-relaxed ${m.role === "user" ? "bg-gradient-to-br from-cyan-300 to-blue-500 text-slate-950" : "border border-white/10 bg-slate-900/70 text-slate-200"}`}>{m.text}</div>
          </motion.div>
          </div>
        ))}
        {file && file.at >= msgs.length && fileCard}
        {thinking && (
          <div className="flex gap-1.5 px-2">{[0, 1, 2].map((i) => <motion.span key={i} className="h-2 w-2 rounded-full bg-cyan-300" animate={{ opacity: [0.2, 1, 0.2] }} transition={{ duration: 1, repeat: Infinity, delay: i * 0.2 }} />)}</div>
        )}
        {stage === "upload" && !file && (
          <motion.button initial={{ opacity: 0, scale: 0.95 }} animate={{ opacity: 1, scale: 1 }} onClick={() => fileRef.current?.click()}
            onDragOver={(e) => e.preventDefault()} onDrop={(e) => { e.preventDefault(); const f = e.dataTransfer.files[0]; if (f) handleFile(f); }}
            className="flex w-full flex-col items-center gap-3 rounded-2xl border-2 border-dashed border-cyan-300/40 bg-cyan-300/5 py-10 text-cyan-200 transition hover:bg-cyan-300/10">
            <FileImage className="h-8 w-8" />
            <span className="font-semibold">Drop package diagram here</span>
            <span className="text-xs text-slate-400">PNG, PDF, STEP · power map, layout, stack-up</span>
          </motion.button>
        )}
        <div ref={endRef} />
      </div>
      <input ref={fileRef} type="file" accept="image/*,.pdf,.step,.stp" hidden onChange={(e) => e.target.files?.[0] && handleFile(e.target.files[0])} />
      <div className="border-t border-white/5 p-4">
        <div className="flex items-center gap-2 rounded-2xl border border-white/10 bg-slate-950/60 px-3 py-2 focus-within:border-cyan-300/50">
          <button onClick={() => fileRef.current?.click()} className="p-2 text-slate-400 hover:text-cyan-300"><Paperclip className="h-4 w-4" /></button>
          <input value={input} onChange={(e) => setInput(e.target.value)} onKeyDown={(e) => e.key === "Enter" && send()} placeholder="Describe what you're cooling…" className="flex-1 bg-transparent py-2 outline-none placeholder:text-slate-600" />
          <button onClick={send} className="grid h-9 w-9 place-items-center rounded-xl bg-gradient-to-br from-cyan-300 to-blue-500 text-slate-950"><Send className="h-4 w-4" /></button>
        </div>
      </div>
    </div>
  );
}

/* ---------------- Dashboard ---------------- */

const PIPE = [
  { key: "cad", label: "CAD geometry", sub: "Fin plate generated · 52 × 52 × 2 mm", icon: Box, ms: 2200 },
  { key: "mesh", label: "Mesh", sub: "Poly-hex core · 4.8M cells", icon: Grid3x3, ms: 2000 },
  { key: "cfd", label: "CFD solve", sub: "Conjugate heat transfer · k-ω SST", icon: Waves, ms: 4200 },
  { key: "opt", label: "Optimization", sub: "Pareto search over the design space", icon: Sparkles, ms: 3000 },
];
const PINGS = [
  "Parsed package: 2 × GPU, 8 × HBM",
  "Design space locked: 52.15 × 52.15 × 2 mm",
  "Fin plate CAD exported (STEP)",
  "Mesh quality: min orthogonality 0.31",
  "Solver initialized · inlet 25 °C · 1.5 LPM",
  "Continuity residual < 1e-4",
  "Energy residual < 1e-6 · converged",
  "Evaluating candidate designs…",
  "Pareto front identified",
];

function Dashboard({ total, onDone }: { total: number; onDone: () => void }) {
  const [step, setStep] = useState(0);
  const [pings, setPings] = useState<string[]>([]);
  const [evald, setEvald] = useState(0);
  const [resid, setResid] = useState<{ it: number; r: number }[]>([]);
  useEffect(() => {
    let cancelled = false;
    (async () => {
      for (let i = 0; i < PIPE.length; i++) {
        setStep(i);
        await new Promise((r) => setTimeout(r, PIPE[i].ms));
        if (cancelled) return;
      }
      setStep(PIPE.length);
      setTimeout(() => !cancelled && onDone(), 1400);
    })();
    let p = 0;
    const pt = setInterval(() => {
      if (p >= PINGS.length) return;
      const next = PINGS[p++];
      setPings((x) => [next, ...x]);
    }, 1250);
    return () => { cancelled = true; clearInterval(pt); };
  }, []);
  useEffect(() => {
    if (step < 2) return;
    const t = setInterval(() => {
      setResid((r) => (r.length > 60 ? r : [...r, { it: r.length * 20, r: Math.exp(-r.length / 9) * (1 + 0.25 * Math.sin(r.length)) }]));
      if (step >= 3) setEvald((e) => Math.min(total, e + 1));
    }, 60);
    return () => clearInterval(t);
  }, [step, total]);
  const pct = Math.min(100, Math.round((step / PIPE.length) * 100));
  return (
    <div className="grid gap-6 lg:grid-cols-[1.4fr_1fr]">
      <div className="space-y-6">
        <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
          {[
            ["Progress", `${pct}%`, Activity],
            ["Designs evaluated", `${evald}/${total}`, Sparkles],
            ["Mesh cells", step >= 1 ? "4.8M" : "—", Grid3x3],
            ["Iterations", step >= 2 ? `${resid.length * 20}` : "—", Waves],
          ].map(([l, v, I]: any) => (
            <div key={l} className="rounded-2xl border border-white/10 bg-white/[0.03] p-4">
              <I className="mb-3 h-4 w-4 text-cyan-300" />
              <div className="font-display text-2xl font-semibold">{v}</div>
              <div className="text-xs text-slate-500">{l}</div>
            </div>
          ))}
        </div>
        <div className="space-y-3">
          {PIPE.map((p, i) => {
            const state = i < step ? "done" : i === step ? "run" : "wait";
            return (
              <motion.div key={p.key} layout className={`flex items-center gap-4 rounded-2xl border p-4 transition ${state === "done" ? "border-emerald-400/30 bg-emerald-400/5" : state === "run" ? "border-cyan-300/40 bg-cyan-300/5" : "border-white/5 bg-white/[0.02] opacity-50"}`}>
                <div className="grid h-11 w-11 place-items-center rounded-xl bg-slate-900"><p.icon className="h-5 w-5 text-cyan-300" /></div>
                <div className="flex-1">
                  <div className="font-semibold">{p.label}</div>
                  <div className="text-sm text-slate-500">{p.sub}</div>
                  {state === "run" && <div className="mt-2 h-1 overflow-hidden rounded-full bg-white/5"><motion.div className="h-full bg-gradient-to-r from-cyan-300 to-blue-500" initial={{ width: "0%" }} animate={{ width: "100%" }} transition={{ duration: p.ms / 1000, ease: "linear" }} /></div>}
                </div>
                <div className="grid h-8 w-8 place-items-center">
                  {state === "done" ? (
                    <motion.div initial={{ scale: 0 }} animate={{ scale: 1 }} transition={{ type: "spring", stiffness: 400, damping: 15 }} className="grid h-8 w-8 place-items-center rounded-full bg-emerald-400 text-slate-950"><Check className="h-4 w-4" strokeWidth={3} /></motion.div>
                  ) : state === "run" ? <Loader2 className="h-5 w-5 animate-spin text-cyan-300" /> : null}
                </div>
              </motion.div>
            );
          })}
        </div>
      </div>
      <div className="space-y-6">
        <div className="rounded-2xl border border-white/10 bg-white/[0.03] p-5">
          <div className="mb-3 flex items-center justify-between text-sm"><span className="font-semibold">Solver residuals</span><span className="text-xs text-slate-500">log scale</span></div>
          <div className="h-44">
            <ResponsiveContainer>
              <ComposedChart data={resid}>
                <CartesianGrid stroke="rgba(255,255,255,0.05)" />
                <XAxis dataKey="it" hide />
                <YAxis scale="log" domain={[0.001, 2]} hide />
                <Line dataKey="r" stroke="#22d3ee" dot={false} strokeWidth={2} isAnimationActive={false} />
              </ComposedChart>
            </ResponsiveContainer>
          </div>
        </div>
        <div className="rounded-2xl border border-white/10 bg-white/[0.03] p-5">
          <div className="mb-3 flex items-center gap-2 text-sm font-semibold"><Radio className="h-4 w-4 text-emerald-300" /> Live pings</div>
          <div className="h-56 space-y-2 overflow-hidden font-mono text-xs">
            <AnimatePresence initial={false}>
              {pings.map((p) => (
                <motion.div key={p} initial={{ opacity: 0, x: -10 }} animate={{ opacity: 1, x: 0 }} className="flex gap-2 text-slate-400"><span className="text-emerald-400">●</span>{p}</motion.div>
              ))}
            </AnimatePresence>
          </div>
        </div>
      </div>
    </div>
  );
}

/* ---------------- Pareto + CFD + export ---------------- */

const KINDS = [
  { key: "minDp", label: "Min ΔP", icon: Gauge, color: "#38bdf8" },
  { key: "balanced", label: "Balanced", icon: Scale, color: "#2dd4bf" },
  { key: "minT", label: "Min T", icon: Thermometer, color: "#a78bfa" },
] as const;

function ParetoStage({ designs, pkg }: { designs: Design[]; pkg: Pkg | null }) {
  const limits = pkg?.limits ?? { dp_psi: 4, t_gpu_c: 100, t_hbm_c: 70 };
  const front = useMemo(() => paretoFront(designs.filter((x) => feasible(x, limits))), [designs, limits]);
  const picks = useMemo(() => pickThree(front), [front]);
  const [sel, setSel] = useState<(typeof KINDS)[number]["key"]>("balanced");
  const [cfdImg, setCfdImg] = useState<string | null>(null);
  const d = picks?.[sel];
  useEffect(() => {
    if (!d) return;
    const url = `/data/cfd/${d.id}.png`;
    fetch(url, { method: "HEAD" }).then((r) => setCfdImg(r.ok && r.headers.get("content-type")?.startsWith("image") ? url : null)).catch(() => setCfdImg(null));
  }, [d?.id]);
  if (!picks || !d) return <div className="py-20 text-center text-slate-500">Waiting for results (data/designs.csv)…</div>;
  const pickIds = new Set(KINDS.map((k) => picks[k.key].id));
  const others = designs.filter((x) => !pickIds.has(x.id) && feasible(x, limits));
  const rejected = designs.filter((x) => !feasible(x, limits));

  async function exportDesign() {
    if (!d) return;
    const cad = `/data/cad/${d.id}.step`;
    const head = await fetch(cad, { method: "HEAD" }).catch(() => null);
    if (head?.ok && !head.headers.get("content-type")?.includes("html")) {
      const a = document.createElement("a"); a.href = cad; a.download = `coldshock-${d.id}.step`; a.click();
    }
    const report = [
      `ColdShock AI · Design report`, `Design: ${d.id} (${KINDS.find((k) => k.key === sel)!.label})`, `Fin type: ${d.fin_type}`,
      `Pressure drop: ${d.dp_psi} psi (limit ${limits.dp_psi})`, `GPU max temp: ${d.t_gpu_c} °C (limit ${limits.t_gpu_c})`, `HBM max temp: ${d.t_hbm_c} °C (limit ${limits.t_hbm_c})`,
    ].join("\n");
    const a = document.createElement("a"); a.href = URL.createObjectURL(new Blob([report], { type: "text/plain" })); a.download = `coldshock-${d.id}-report.txt`; a.click();
  }

  return (
    <div className="grid gap-6 lg:grid-cols-[1.1fr_1fr]">
      <div className="rounded-3xl border border-white/10 bg-white/[0.03] p-6">
        <div className="mb-1 text-xs uppercase tracking-[0.25em] text-cyan-300/80">Pareto front</div>
        <h2 className="font-display text-2xl font-semibold">{designs.length} designs simulated · 3 Pareto-optimal points</h2>
        <div className="mt-2 flex gap-4 text-xs text-slate-500">
          <span className="flex items-center gap-1.5"><span className="h-2 w-2 rounded-full bg-slate-500" />Feasible</span>
          <span className="flex items-center gap-1.5"><span className="h-2 w-2 rounded-full bg-red-400/60" />Violates a limit ({rejected.length})</span>
          <span className="flex items-center gap-1.5"><span className="h-0.5 w-4 bg-cyan-300" />Pareto front</span>
        </div>
        <div className="mt-2 h-[400px]">
          <ResponsiveContainer>
            <ScatterChart margin={{ top: 24, right: 24, bottom: 30, left: 24 }}>
              <CartesianGrid stroke="rgba(255,255,255,0.06)" />
              <XAxis type="number" dataKey="dp_psi" name="ΔP" unit=" psi" domain={[0.5, 4.5]} stroke="#64748b" label={{ value: "Pressure drop (psi)", position: "bottom", fill: "#94a3b8", offset: 10 }} />
              <YAxis type="number" dataKey="t_gpu_c" name="T GPU" unit=" °C" domain={[65, 105]} stroke="#64748b" label={{ value: "Max GPU temp (°C)", angle: -90, position: "left", fill: "#94a3b8", offset: 10, style: { textAnchor: "middle" } }} />
              <Tooltip cursor={{ stroke: "rgba(255,255,255,0.1)" }} contentStyle={{ background: "#0f172a", border: "1px solid rgba(255,255,255,0.1)", borderRadius: 12 }} />
              <ReferenceLine x={limits.dp_psi} stroke="#f87171" strokeDasharray="4 4" label={{ value: "4 psi limit", fill: "#f87171", fontSize: 11, position: "insideTopLeft" }} />
              <ReferenceLine y={limits.t_gpu_c} stroke="#f87171" strokeDasharray="4 4" label={{ value: "100 °C limit", fill: "#f87171", fontSize: 11, position: "insideBottomLeft" }} />
              <Scatter data={others} fill="#475569" fillOpacity={0.7} />
              <Scatter data={rejected} fill="#f87171" fillOpacity={0.45} shape="cross" />
              <Scatter data={front} line={{ stroke: "#22d3ee", strokeWidth: 2 }} fill="transparent" />
              {KINDS.map((k) => (
                <Scatter key={k.key} data={[picks[k.key]]} fill={k.color} onClick={() => setSel(k.key)} cursor="pointer"
                  shape={(p: any) => (
                    <g>
                      <circle cx={p.cx} cy={p.cy} r={sel === k.key ? 16 : 11} fill={k.color} opacity={0.2}><animate attributeName="r" values="10;18;10" dur="2s" repeatCount="indefinite" /></circle>
                      <circle cx={p.cx} cy={p.cy} r={7} fill={k.color} stroke="#0f172a" strokeWidth={2} />
                    </g>
                  )} />
              ))}
            </ScatterChart>
          </ResponsiveContainer>
        </div>
        <div className="mt-2 grid grid-cols-3 gap-3">
          {KINDS.map((k) => {
            const p = picks[k.key];
            return (
              <button key={k.key} onClick={() => setSel(k.key)} className={`rounded-2xl border p-4 text-left transition ${sel === k.key ? "border-cyan-300/60 bg-cyan-300/10" : "border-white/10 hover:border-white/30"}`}>
                <div className="mb-2 flex items-center gap-2 text-sm font-semibold" style={{ color: k.color }}><k.icon className="h-4 w-4" />{k.label}</div>
                <div className="text-xs text-slate-400">{p.dp_psi} psi · {p.t_gpu_c} °C</div>
              </button>
            );
          })}
        </div>
      </div>
      <div className="flex flex-col gap-6">
        <AnimatePresence mode="wait">
          <motion.div key={d.id} initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }} className="rounded-3xl border border-white/10 bg-white/[0.03] p-6">
            <div className="mb-4 flex items-center justify-between">
              <div>
                <div className="text-xs uppercase tracking-[0.25em] text-cyan-300/80">CFD result</div>
                <div className="font-display text-xl font-semibold">{KINDS.find((k) => k.key === sel)!.label} · {d.id}</div>
              </div>
              <span className="rounded-full bg-emerald-400/15 px-3 py-1 text-xs font-semibold text-emerald-300">All limits met</span>
            </div>
            <CFDView finType={d.fin_type} dp={d.dp_psi} tGpu={d.t_gpu_c} image={cfdImg} />
            <div className="mt-5 grid grid-cols-3 gap-3">
              {[
                ["ΔP", d.dp_psi, limits.dp_psi, "psi"],
                ["GPU max", d.t_gpu_c, limits.t_gpu_c, "°C"],
                ["HBM max", d.t_hbm_c, limits.t_hbm_c, "°C"],
              ].map(([l, v, lim, u]: any) => (
                <div key={l} className="rounded-xl bg-slate-900/70 p-3">
                  <div className="text-xs text-slate-500">{l}</div>
                  <div className="font-display text-xl font-semibold">{v}<span className="text-sm text-slate-500"> {u}</span></div>
                  <div className="mt-2 h-1 rounded-full bg-white/5"><div className="h-full rounded-full bg-gradient-to-r from-cyan-300 to-emerald-300" style={{ width: `${Math.min(100, (v / lim) * 100)}%` }} /></div>
                  <div className="mt-1 text-[10px] text-slate-500">{Math.round((1 - v / lim) * 100)}% margin to {lim} {u}</div>
                </div>
              ))}
            </div>
          </motion.div>
        </AnimatePresence>
        <motion.button whileHover={{ scale: 1.02 }} whileTap={{ scale: 0.98 }} onClick={exportDesign}
          className="group flex items-center justify-between rounded-3xl bg-gradient-to-r from-cyan-300 to-blue-500 px-8 py-6 text-slate-950 shadow-[0_0_60px_rgba(34,211,238,0.35)]">
          <div className="text-left">
            <div className="font-display text-2xl font-semibold">Export design</div>
            <div className="text-sm opacity-70">STEP geometry + CFD report</div>
          </div>
          <Download className="h-7 w-7 transition group-hover:translate-y-1" />
        </motion.button>
      </div>
    </div>
  );
}
