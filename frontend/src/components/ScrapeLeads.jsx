import { useEffect, useRef, useState } from "react";
import { api } from "../lib/api";

function StatusBadge({ status }) {
  const config = {
    pending:        { cls: "badge-muted",                      label: "Queued"         },
    running:        { cls: "badge-blue animate-soft-pulse",    label: "Running"        },
    preprocessing:  { cls: "badge-purple animate-soft-pulse",  label: "Processing"     },
    email_scraping: { cls: "badge-blue animate-soft-pulse",    label: "Finding emails" },
    done:           { cls: "badge-accent",                     label: "Done"           },
    failed:         { cls: "badge-danger",                     label: "Failed"         },
    canceled:       { cls: "badge-muted",                      label: "Canceled"       },
  };
  const c = config[status] || config.pending;
  return <span className={`badge ${c.cls}`}>{c.label}</span>;
}

function StepBar({ step }) {
  const steps = [
    { key: "step1_maps",       label: "Maps"    },
    { key: "step2_preprocess", label: "Process" },
    { key: "step3_emails",     label: "Emails"  },
    { key: "complete",         label: "Done"    },
  ];
  const cur = steps.findIndex(s => s.key === step);
  return (
    <div className="flex items-center gap-1 flex-wrap">
      {steps.map((s, i) => (
        <div key={s.key} className="flex items-center gap-1">
          <span className={`badge text-[10px] ${
            i < cur   ? "badge-accent" :
            i === cur ? "badge-accent animate-soft-pulse" :
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

function JobProgress({ jobId, onNewJob }) {
  const [job, setJob]     = useState(null);
  const [error, setError] = useState("");
  const timer             = useRef(null);

  const fetchJob = async () => {
    try {
      const d = await api.getJob(jobId);
      setJob(d);
      if (["done", "failed", "canceled"].includes(d.status)) {
        clearInterval(timer.current);
      }
    } catch (e) {
      setError(e.message);
      clearInterval(timer.current);
    }
  };

  useEffect(() => {
    fetchJob();
    timer.current = setInterval(fetchJob, 3000);
    return () => clearInterval(timer.current);
  }, [jobId]);

  const cancel = async () => {
    try { await api.cancelJob(jobId); clearInterval(timer.current); fetchJob(); }
    catch (e) { setError(e.message); }
  };

  const download = async (type) => {
    try { const r = await api.downloadJob(jobId, type); window.open(r.url, "_blank"); }
    catch (e) { setError(e.message); }
  };

  if (error) return (
    <div className="p-3 rounded-lg text-sm" style={{
      background: "rgba(255,77,106,0.08)",
      border: "1px solid rgba(255,77,106,0.2)",
      color: "var(--danger)"
    }}>{error}</div>
  );

  if (!job) return (
    <div className="text-sm animate-soft-pulse" style={{ color: "var(--text-3)" }}>Loading job…</div>
  );

  const isComplete  = job.status === "done";
  const isFailed    = job.status === "failed";
  const isCanceled  = job.status === "canceled";
  const isRunning   = !isComplete && !isFailed && !isCanceled;

  const pct = job.cities_total > 0
    ? Math.round((job.cities_done / job.cities_total) * 100)
    : 0;

  // ── FIX 1: Email progress — use emails_attempted & with_website ──
  const emailsTotal    = job.with_website   ?? 0;
  const emailsAttempted = job.emails_attempted ?? 0;
  const emailsFound    = job.emails_found   ?? 0;
  const emailsPct      = emailsTotal > 0
    ? Math.round((emailsAttempted / emailsTotal) * 100)
    : 0;
  const emailsRunning  = isRunning && job.current_step === "step3_emails";

  // ── Displayed status ──
  const displayStatus = emailsRunning ? "email_scraping" : job.status;

  return (
    <div className="space-y-5 animate-fade-in">

      {/* Header */}
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="font-semibold" style={{ color: "var(--text)" }}>
            {job.industry} — {job.state}
          </p>
          <p className="text-xs mt-0.5" style={{ color: "var(--text-3)" }}>
            {job.cities?.join(", ")}
          </p>
        </div>
        <StatusBadge status={displayStatus} />
      </div>

      {/* Step bar — show until complete */}
      {isRunning && <StepBar step={job.current_step} />}

      {/* Maps progress */}
      {job.cities_total > 0 && (
        <div>
          <div className="flex justify-between text-xs mb-2" style={{ color: "var(--text-2)" }}>
            <span>
              {job.current_step === "step1_maps" && job.current_city
                ? `Scraping: ${job.current_city}`
                : `${job.cities_done} / ${job.cities_total} cities`}
            </span>
            <span className="mono">{pct}%</span>
          </div>
          <div className="progress-bar">
            <div className="progress-fill" style={{ width: `${pct}%` }} />
          </div>
        </div>
      )}

      {/* ── FIX 1: Email progress bar updates correctly ── */}
      {(emailsRunning || (isComplete && emailsTotal > 0)) && (
        <div>
          <div className="flex justify-between text-xs mb-2" style={{ color: "var(--text-2)" }}>
            <span>Finding emails…</span>
            <span className="mono">{emailsAttempted} / {emailsTotal} sites · {emailsFound} found</span>
          </div>
          <div className="progress-bar">
            <div className="progress-fill" style={{ width: `${emailsPct}%` }} />
          </div>
        </div>
      )}

      {/* Stats */}
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
        {[
          { label: "Total leads",  value: job.total_clean  ?? 0 },
          { label: "With website", value: emailsTotal },
          { label: "No website",   value: job.no_website   ?? 0 },
          { label: "Emails found", value: emailsFound },
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
                <th className="px-4 py-2.5 text-left text-xs font-medium tracking-wider uppercase"
                  style={{ color: "var(--text-3)" }}>City</th>
                <th className="px-4 py-2.5 text-right label" style={{ marginBottom: 0 }}>Raw Leads</th>
                <th className="px-4 py-2.5 text-left text-xs font-medium tracking-wider uppercase"
                  style={{ color: "var(--text-3)" }}>Status</th>
              </tr>
            </thead>
            <tbody>
              {job.city_progress.map((c, i) => (
                <tr key={c.city} style={{ borderTop: i > 0 ? "1px solid var(--border)" : "none" }}>
                  <td className="px-4 py-2.5 font-medium" style={{ color: "var(--text)" }}>{c.city}</td>
                  <td className="px-4 py-2.5 text-right mono text-xs" style={{ color: "var(--text-2)" }}>
                    {c.maps_leads ?? 0}
                  </td>
                  <td className="px-4 py-2.5">
                    <span className={`badge ${
                      c.maps_status === "done"    ? "badge-accent" :
                      c.maps_status === "running" ? "badge-blue animate-soft-pulse" :
                      c.maps_status === "failed"  ? "badge-danger" : "badge-muted"
                    }`}>
                      {c.maps_status === "done"    ? "Done"    :
                       c.maps_status === "running" ? "Running" :
                       c.maps_status === "failed"  ? "Failed"  : "Queued"}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {job.error_message && (
        <div className="p-3 rounded-lg text-sm" style={{
          background: "rgba(255,77,106,0.08)",
          border: "1px solid rgba(255,77,106,0.2)",
          color: "var(--danger)"
        }}>{job.error_message}</div>
      )}

      {/* ── FIX 2: Download buttons stay on same page after completion ── */}
      <div className="flex flex-wrap gap-2">
        {isComplete && (
          <>
            <button onClick={() => download("with_website")} className="btn-primary">
              ⬇ With Website
            </button>
            <button onClick={() => download("no_website")} className="btn-ghost">
              ⬇ No Website
            </button>
          </>
        )}
        {isRunning && (
          <button onClick={cancel} className="btn-danger">Cancel job</button>
        )}
        {/* New Job button — only shows after done/failed/canceled */}
        {(isComplete || isFailed || isCanceled) && (
          <button onClick={onNewJob} className="btn-ghost">
            ← New Job
          </button>
        )}
      </div>
    </div>
  );
}

export default function ScrapeLeads({ plan }) {
  const [industry, setIndustry]       = useState("");
  const [state, setState]             = useState("");
  const [cityText, setCityText]       = useState("");   // textarea raw text
  const [cities, setCities]           = useState([]);   // confirmed city tags
  const [loading, setLoading]         = useState(false);
  const [error, setError]             = useState("");
  const [activeJobId, setActiveJobId] = useState(null);

  const maxCities = plan?.cities_per_job ?? 10;

  // ── FIX 3: City input logic ──
  // cityText = what user is typing right now (single city)
  // cities   = list of confirmed cities (shown as tags)

  const commitCity = (text) => {
    // Split by comma in case user pastes "Miami, Tampa"
    const parts = text.split(",").map(c => c.trim()).filter(Boolean);
    if (!parts.length) return;
    setCities(prev => {
      const merged = [...new Set([...prev, ...parts])].slice(0, maxCities);
      return merged;
    });
    setCityText("");
    setError("");
  };

  const handleCityChange = (e) => {
    const val = e.target.value;
    // If user typed a comma, treat everything before comma as a committed city
    if (val.includes(",")) {
      const parts = val.split(",");
      const toCommit = parts.slice(0, -1).join(",");
      const remaining = parts[parts.length - 1];
      commitCity(toCommit);
      setCityText(remaining);
    } else {
      setCityText(val);
    }
  };

  const handleCityKeyDown = (e) => {
    if (e.key === "Enter") {
      e.preventDefault();
      if (cityText.trim()) commitCity(cityText);
    }
    // Backspace on empty input removes last tag
    if (e.key === "Backspace" && !cityText && cities.length > 0) {
      setCities(prev => prev.slice(0, -1));
    }
  };

  const removeCity = (city) => {
    setCities(prev => prev.filter(c => c !== city));
  };

  const submit = async (e) => {
    e.preventDefault();
    // Commit any remaining text before submitting
    const allCities = cityText.trim()
      ? [...new Set([...cities, ...cityText.split(",").map(c => c.trim()).filter(Boolean)])].slice(0, maxCities)
      : cities;

    if (!industry.trim())      { setError("Industry is required"); return; }
    if (!state.trim())         { setError("State abbreviation is required"); return; }
    if (allCities.length === 0){ setError("Add at least one city"); return; }

    setLoading(true); setError("");
    try {
      const job = await api.createJob({
        industry: industry.trim(),
        state: state.trim(),
        cities: allCities,
      });
      setActiveJobId(job.id);
      setIndustry(""); setState(""); setCities([]); setCityText("");
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
                <input value={state}
                  onChange={e => setState(e.target.value.toUpperCase().slice(0, 2))}
                  placeholder="FL" maxLength={2} className="input mono" />
              </div>
            </div>

            <div>
              <label className="label">
                Cities
                <span className="ml-2 normal-case" style={{ color: "var(--text-3)", fontWeight: 400 }}>
                  {cities.length}/{maxCities} · Enter or comma to add
                </span>
              </label>

              {/* Tags + input in one box */}
              <div className="input min-h-[80px] flex flex-wrap gap-1.5 items-start content-start cursor-text"
                style={{ padding: "8px 12px" }}
                onClick={() => document.getElementById("city-input").focus()}>
                {cities.map(c => (
                  <span key={c} className="badge badge-accent flex items-center gap-1 shrink-0">
                    {c}
                    <button
                      type="button"
                      onClick={(e) => { e.stopPropagation(); removeCity(c); }}
                      className="hover:opacity-70 transition leading-none"
                    >×</button>
                  </span>
                ))}
                <input
                  id="city-input"
                  value={cityText}
                  onChange={handleCityChange}
                  onKeyDown={handleCityKeyDown}
                  placeholder={cities.length === 0 ? "Type a city, press Enter or comma…" : ""}
                  className="flex-1 min-w-[120px] bg-transparent outline-none text-sm"
                  style={{ color: "var(--text)", border: "none", padding: 0 }}
                  disabled={cities.length >= maxCities}
                />
              </div>

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
          <JobProgress
            jobId={activeJobId}
            onNewJob={() => setActiveJobId(null)}
          />
        </div>
      )}
    </div>
  );
}
