import { useEffect, useRef, useState } from "react";
import { api } from "../lib/api";

function StatusBadge({ status }) {
  const config = {
    pending:       { cls: "badge-muted",   label: "Queued" },
    running:       { cls: "badge-blue",    label: "Running" },
    preprocessing: { cls: "badge-purple",  label: "Processing" },
    email_scraping:{ cls: "badge-accent",  label: "Finding emails" },
    done:          { cls: "badge-accent",  label: "Complete" },
    failed:        { cls: "badge-danger",  label: "Failed" },
    canceled:      { cls: "badge-muted",   label: "Canceled" },
  };
  const c = config[status] || config.pending;
  return <span className={`badge ${c.cls}`}>{c.label}</span>;
}

function StepBar({ step }) {
  const steps = [
    { key: "step1_maps",       label: "Maps" },
    { key: "step2_preprocess", label: "Process" },
    { key: "step3_emails",     label: "Emails" },
    { key: "complete",         label: "Done" },
  ];
  const cur = steps.findIndex(s => s.key === step);
  return (
    <div className="flex items-center gap-1">
      {steps.map((s, i) => (
        <div key={s.key} className="flex items-center gap-1">
          <span className={`badge text-[10px] ${
            i < cur  ? "badge-accent" :
            i === cur? "badge-accent animate-soft-pulse" :
                       "badge-muted"
          }`}>{s.label}</span>
          {i < steps.length - 1 && (
            <span className="text-xs" style={{ color: "var(--text-3)" }}>›</span>
          )}
        </div>
      ))}
    </div>
  );
}

function JobProgress({ jobId, onComplete }) {
  const [job, setJob] = useState(null);
  const [error, setError] = useState("");
  const timer = useRef(null);

  const fetch = async () => {
    try {
      const d = await api.getJob(jobId);
      setJob(d);
      if (["done","failed","canceled"].includes(d.status)) {
        clearInterval(timer.current);
        if (d.status === "done") onComplete?.();
      }
    } catch (e) { setError(e.message); clearInterval(timer.current); }
  };

  useEffect(() => {
    fetch();
    timer.current = setInterval(fetch, 3000);
    return () => clearInterval(timer.current);
  }, [jobId]);

  const cancel = async () => {
    try { await api.cancelJob(jobId); clearInterval(timer.current); fetch(); }
    catch (e) { setError(e.message); }
  };

  const download = async (type) => {
    try { const r = await api.downloadJob(jobId, type); window.open(r.url, "_blank"); }
    catch (e) { setError(e.message); }
  };

  if (error) return (
    <div className="p-3 rounded-lg text-sm" style={{ background: "rgba(255,77,106,0.08)", border: "1px solid rgba(255,77,106,0.2)", color: "var(--danger)" }}>{error}</div>
  );
  if (!job) return (
    <div className="text-sm animate-soft-pulse" style={{ color: "var(--text-3)" }}>Loading job…</div>
  );

  const pct = job.cities_total > 0 ? Math.round((job.cities_done / job.cities_total) * 100) : 0;

  return (
    <div className="space-y-5 animate-fade-in">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="font-semibold" style={{ color: "var(--text)" }}>{job.industry} — {job.state}</p>
          <p className="text-xs mt-0.5" style={{ color: "var(--text-3)" }}>{job.cities.join(", ")}</p>
        </div>
        <StatusBadge status={job.status} />
      </div>

      {["pending","running","preprocessing","email_scraping"].includes(job.status) && (
        <StepBar step={job.current_step} />
      )}

      {job.cities_total > 0 && (
        <div>
          <div className="flex justify-between text-xs mb-2" style={{ color: "var(--text-2)" }}>
            <span>{job.current_city ? `Scraping: ${job.current_city}` : `${job.cities_done} / ${job.cities_total} cities`}</span>
            <span className="mono">{pct}%</span>
          </div>
          <div className="progress-bar">
            <div className="progress-fill" style={{ width: `${pct}%` }} />
          </div>
        </div>
      )}

      {/* Stats */}
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
        {[
          { label: "Total leads",  value: job.total_clean },
          { label: "With website", value: job.with_website },
          { label: "No website",   value: job.no_website },
          { label: "Emails found", value: job.emails_found },
        ].map(s => (
          <div key={s.label} className="card p-3 text-center">
            <p className="stat-number text-2xl">{s.value}</p>
            <p className="text-xs mt-1" style={{ color: "var(--text-3)" }}>{s.label}</p>
          </div>
        ))}
      </div>

      {/* City table */}
      {job.city_progress?.length > 0 && (
        <div className="card overflow-hidden">
          <table className="w-full text-sm">
            <thead style={{ borderBottom: "1px solid var(--border)" }}>
              <tr>
                <th className="px-4 py-2.5 text-left text-xs font-medium tracking-wider uppercase" style={{ color: "var(--text-3)" }}>City</th>
                <th className="px-4 py-2.5 text-right label" style={{ marginBottom: 0 }}>Leads</th>
                <th className="px-4 py-2.5 text-left text-xs font-medium tracking-wider uppercase" style={{ color: "var(--text-3)" }}>Status</th>
              </tr>
            </thead>
            <tbody>
              {job.city_progress.map((c, i) => (
                <tr key={c.city} style={{ borderTop: i > 0 ? "1px solid var(--border)" : "none" }}>
                  <td className="px-4 py-2.5 font-medium" style={{ color: "var(--text)" }}>{c.city}</td>
                  <td className="px-4 py-2.5 text-right mono text-xs" style={{ color: "var(--text-2)" }}>{c.maps_leads ?? 0}</td>
                  <td className="px-4 py-2.5">
                    <span className={`badge ${
                      c.maps_status === "done"    ? "badge-accent" :
                      c.maps_status === "running" ? "badge-blue animate-soft-pulse" :
                      c.maps_status === "failed"  ? "badge-danger" : "badge-muted"
                    }`}>
                      {c.maps_status === "done" ? "Done" : c.maps_status === "running" ? "Running" : c.maps_status === "failed" ? "Failed" : "Queued"}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {job.error_message && (
        <div className="p-3 rounded-lg text-sm" style={{ background: "rgba(255,77,106,0.08)", border: "1px solid rgba(255,77,106,0.2)", color: "var(--danger)" }}>
          {job.error_message}
        </div>
      )}

      <div className="flex flex-wrap gap-2">
        {job.status === "done" && (
          <>
            <button onClick={() => download("with_website")} className="btn-primary">⬇ With website</button>
            <button onClick={() => download("no_website")}   className="btn-ghost">⬇ No website</button>
          </>
        )}
        {["pending","running"].includes(job.status) && (
          <button onClick={cancel} className="btn-danger">Cancel job</button>
        )}
      </div>
    </div>
  );
}

export default function ScrapeLeads({ plan }) {
  const [industry, setIndustry]     = useState("");
  const [state, setState]           = useState("");
  const [cityInput, setCityInput]   = useState("");
  const [cities, setCities]         = useState([]);
  const [loading, setLoading]       = useState(false);
  const [error, setError]           = useState("");
  const [activeJobId, setActiveJobId] = useState(null);

  const maxCities = plan?.cities_per_job ?? 10;

  const submit = async (e) => {
    e.preventDefault();
    if (!industry.trim()) { setError("Industry is required"); return; }
    if (!state.trim())    { setError("State abbreviation is required"); return; }
    if (cities.length === 0) { setError("Add at least one city"); return; }
    setLoading(true); setError("");
    try {
      const job = await api.createJob({ industry: industry.trim(), state: state.trim(), cities });
      setActiveJobId(job.id);
      setIndustry(""); setState(""); setCities([]);
    } catch (e) { setError(e.message); }
    finally { setLoading(false); }
  };

  return (
    <div className="space-y-4 animate-fade-in">
      {!activeJobId ? (
        <div className="card p-6">
          <p className="font-semibold mb-5" style={{ color: "var(--text)" }}>New Scrape Job</p>
          <form onSubmit={submit} className="space-y-4">
            <div className="grid gap-4 sm:grid-cols-2">
              <div>
                <label className="label">Industry</label>
                <input value={industry} onChange={e => setIndustry(e.target.value)}
                  placeholder="Plumbing, HVAC, Roofing…" className="input" />
              </div>
              <div>
                <label className="label">State</label>
                <input value={state} onChange={e => setState(e.target.value.toUpperCase().slice(0,2))}
                  placeholder="FL" maxLength={2} className="input mono" />
              </div>
            </div>

            <div>
              <label className="label">
                Cities
                <span className="ml-2 normal-case" style={{ color: "var(--text-3)", fontWeight: 400 }}>
                  {cities.length}/{maxCities} · comma separated
                </span>
              </label>
              <textarea
                value={cityInput}
                onChange={e => {
                  setCityInput(e.target.value);
                  const parsed = e.target.value
                    .split(",")
                    .map(c => c.trim())
                    .filter(Boolean);
                  const unique = [...new Set(parsed)].slice(0, maxCities);
                  setCities(unique);
                  setError("");
                }}
                placeholder="Miami, Tampa, Orlando, Jacksonville…"
                rows={3}
                className="input"
                style={{ resize: "vertical", lineHeight: "1.6" }}
              />
              {cities.length > 0 && (
                <div className="flex flex-wrap gap-1.5 mt-2">
                  {cities.map(c => (
                    <span key={c} className="badge badge-accent gap-1.5">{c}</span>
                  ))}
                </div>
              )}
              {cities.length >= maxCities && (
                <p className="text-xs mt-1" style={{ color: "var(--warning)" }}>
                  Max {maxCities} cities reached
                </p>
              )}
            </div>

            {error && <p className="text-xs" style={{ color: "var(--danger)" }}>{error}</p>}

            <button type="submit" disabled={loading} className="btn-primary w-full">
              {loading
                ? <span className="flex items-center justify-center gap-2">
                    <span className="h-3.5 w-3.5 rounded-full border-2 border-black/30 border-t-black animate-spin" />
                    Starting…
                  </span>
                : "⚡ Start Scraping"}
            </button>
          </form>
        </div>
      ) : (
        <div className="card p-6">
          <p className="font-semibold mb-5" style={{ color: "var(--text)" }}>Job Progress</p>
          <JobProgress jobId={activeJobId} onComplete={() => setActiveJobId(null)} />
        </div>
      )}
    </div>
  );
}
