import { useCallback, useEffect, useRef, useState } from "react";
import { ParetoChart } from "./pareto/ParetoChart";
import type { ResultsDoc, Candidate, SelectedDesign } from "./types";

interface JobState {
  status: string; stage: string; progress: number; message: string;
  events: { at: string; stage: string; message: string }[];
  interpretation?: { provider_label?: string; session_url?: string; cached?: boolean };
  error?: string | null;
}

export default function App() {
  const [results, setResults] = useState<ResultsDoc | null>(null);
  const [job, setJob] = useState<JobState | null>(null);
  const [selected, setSelected] = useState<SelectedDesign | undefined>();
  const [useCache, setUseCache] = useState(true);
  const [jobIdInput, setJobIdInput] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const refRef = useRef<HTMLInputElement>(null);
  const pollRef = useRef<number | undefined>(undefined);

  const pollJob = useCallback((jobId: string) => {
    const tick = async () => {
      const r = await fetch(`/api/jobs/${jobId}`);
      const j = (await r.json()) as JobState;
      setJob(j);
      if (["completed", "needs_input", "unsupported", "failed"].includes(j.status)) {
        window.clearInterval(pollRef.current);
        const rr = await fetch(`/api/results/${jobId}`);
        if (rr.ok) {
          const doc = (await rr.json()) as ResultsDoc;
          setResults(doc);
          setSelected(doc.selected_designs?.[0]);
        }
      }
    };
    pollRef.current = window.setInterval(tick, 1500);
    void tick();
  }, []);

  useEffect(() => () => window.clearInterval(pollRef.current), []);

  async function submit() {
    setErr(null); setResults(null); setSelected(undefined);
    const req = fileRef.current?.files?.[0];
    if (!req) { setErr("choose a requirements .md file"); return; }
    const form = new FormData();
    form.append("requirements", req);
    const refs = refRef.current?.files ?? [];
    for (const f of Array.from(refs)) form.append("reference_files", f);
    form.append("options", JSON.stringify({
      parser: "devin", prompt_version: "v2", use_cache: useCache,
    }));
    const r = await fetch("/api/optimize", { method: "POST", body: form });
    if (r.status !== 202) { setErr(`submit failed: ${r.status}`); return; }
    const j = await r.json();
    pollJob(j.job_id);
  }

  async function loadById() {
    if (!jobIdInput) return;
    const r = await fetch(`/api/results/${jobIdInput}`);
    if (!r.ok) { setErr(`no results for ${jobIdInput}`); return; }
    const doc = (await r.json()) as ResultsDoc;
    setResults(doc); setSelected(doc.selected_designs?.[0]); setErr(null);
  }

  async function loadSample() {
    const r = await fetch("/sample-results.json");
    const doc = (await r.json()) as ResultsDoc;
    setResults(doc); setSelected(doc.selected_designs?.[0]); setErr(null);
  }

  const onSelect = useCallback((did: string, cand?: Candidate) => {
    setSelected(cand as SelectedDesign | undefined);
  }, []);

  const interp = results?.interpretation;

  return (
    <div>
      <h1>Cold-plate optimization — Pareto harness</h1>
      <div className="disclaimer">Low-fidelity estimates — not validated CFD.</div>

      <div className="panel">
        <h2>Run a job</h2>
        <label>Requirements (.md)
          <input type="file" accept=".md,.markdown,.txt" ref={fileRef} /></label>
        <label>Reference files (optional, e.g. power map CSV)
          <input type="file" multiple ref={refRef} /></label>
        <label><input type="checkbox" checked={useCache}
          onChange={(e) => setUseCache(e.target.checked)} /> use Devin parse cache</label>
        <button onClick={submit}>Submit (Devin parse)</button>
      </div>

      <div className="panel">
        <h2>Or load existing</h2>
        <input value={jobIdInput} onChange={(e) => setJobIdInput(e.target.value)}
          placeholder="job id" />
        <button onClick={loadById}>Load by job id</button>{" "}
        <button onClick={loadSample}>Load sample results</button>
        {err && <p className="conflicts">{err}</p>}
      </div>

      {job && !results && (
        <div className="panel">
          <h2>Job {job.status} — {job.stage} ({Math.round(job.progress * 100)}%)</h2>
          <p>{job.message}</p>
          {job.interpretation?.session_url && (
            <p><a href={job.interpretation.session_url} target="_blank" rel="noreferrer">
              Devin session</a></p>)}
          <div className="job-events">
            {(job.events ?? []).slice(-8).map((e, i) => (
              <div key={i}>[{e.stage}] {e.message}</div>
            ))}
          </div>
        </div>
      )}

      {results && (
        <>
          <div className="panel">
            {interp?.provider !== "devin" && (
              <div className="recorded">{interp?.provider_label}</div>)}
            {interp?.provider === "devin" && (
              <div className="recorded">{interp.provider_label}
                {interp.cached ? " (cache hit)" : ""}</div>)}
            <p><small>job {results.job_id} — {results.status} — prompt{" "}
              {interp?.prompt_version}{interp?.api_version ?
                ` — Devin API ${interp.api_version}` : ""}</small></p>
            {(results.requirement_conflicts ?? []).map((c, i) => (
              <p key={i} className="conflicts">{c}</p>
            ))}
            {(results.assumptions ?? []).length > 0 && (
              <details><summary>Assumptions ({results.assumptions.length})</summary>
                <ul>{results.assumptions.map((a, i) => (
                  <li key={i}><b>{a.field}</b> ({a.origin}): {a.statement}</li>))}
                </ul></details>)}
          </div>

          <ParetoChart results={results}
            selectedDesignId={selected?.design_id}
            onSelectDesign={onSelect} />

          {selected && (
            <div className="panel">
              <h2>{selected.role_label ?? selected.role} — {selected.status_label}</h2>
              <table className="metrics"><tbody>
                <tr><td>ΔP</td><td>{selected.metrics.pressure_drop_kPa.toFixed(3)} kPa</td></tr>
                <tr><td>hottest HBM</td><td>{selected.metrics.hbm_max_C?.toFixed(2)} °C ({selected.metrics.hbm_hottest})</td></tr>
                <tr><td>hottest GPU</td><td>{selected.metrics.gpu_max_C?.toFixed(2)} °C ({selected.metrics.gpu_hottest})</td></tr>
                <tr><td>coolant rise</td><td>{selected.metrics.coolant_rise_K.toFixed(2)} K</td></tr>
                <tr><td>fin thickness</td><td>{selected.params.fin_thickness_mm} mm</td></tr>
                <tr><td>channel widths</td><td>{JSON.stringify(selected.params.channel_width_by_zone_mm)}</td></tr>
              </tbody></table>
              {(selected.violations ?? []).length > 0 && (
                <p className="conflicts">violations: {selected.violations.map((v) =>
                  `${v.constraint}${v.component ? ":" + v.component : ""} ${v.value}>${v.limit}`).join("; ")}</p>)}
              {selected.acceptance?.summary && <p>{selected.acceptance.summary}</p>}
              {selected.files && (
                <p>files: {Object.entries(selected.files).map(([k, f]) => (
                  <span key={k}><a href={f.url}>{k}</a>{" "}</span>))}</p>)}
            </div>
          )}
        </>
      )}
    </div>
  );
}
