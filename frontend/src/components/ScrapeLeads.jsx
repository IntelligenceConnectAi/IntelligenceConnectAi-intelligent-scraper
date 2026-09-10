import { useEffect, useRef, useState } from "react";
import { normalizeStateInput } from "../lib/usStates";
import { api } from "../lib/api";
import SecureProcessingGlobe from "./SecureProcessingGlobe";
import StatusIndicator from "./StatusIndicator";

export function JobProgress({ jobId, onNewJob }) {
  const [job, setJob]     = useState(null);
  const [error, setError] = useState("");
  const timer             = useRef(null);

  const fetchJob = async () => {
    try {
      const d = await api.getBusinessRequest(jobId);
      setJob(d);
      if (["Completed", "Cancelled", "Failed"].includes(d.status)) {
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
    <div className="alert-danger">{error}</div>
  );

  if (!job) return (
    <div className="text-sm animate-soft-pulse" style={{ color: "var(--text-3)" }}>Loading job…</div>
  );

  const isComplete   = job.status === "Completed";
  const isFailed     = job.status === "Failed";
  const isCancelled  = job.status === "Cancelled";
  const isProcessing = job.status === "Submitted" || job.status === "Processing";

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
        <StatusIndicator status={job.status} variant="business" />
      </div>

      {/* Secure processing experience — no scraping internals shown */}
      {isProcessing && <SecureProcessingGlobe variant="business" />}

      {/* KPIs only show when the request is complete */}
      {isComplete && (
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
          {[
            { label: "Total leads",  value: job.total_leads  ?? 0 },
            { label: "With website", value: job.with_website ?? 0 },
            { label: "No website",   value: job.no_website   ?? 0 },
            { label: "Emails found", value: job.emails_found ?? 0 },
          ].map(s => (
            <div key={s.label} className="card p-3 text-center">
              <p className="stat-number text-2xl">{s.value}</p>
              <p className="text-xs mt-1" style={{ color: "var(--text-3)" }}>{s.label}</p>
            </div>
          ))}
        </div>
      )}

      {(isFailed || isCancelled) && (
        isFailed ? (
          <div className="alert-danger">{job.message}</div>
        ) : (
          <div className="p-3 rounded-lg text-sm" style={{
            background: "var(--surface-soft)", border: "1px solid var(--border)", color: "var(--text-2)"
          }}>{job.message}</div>
        )
      )}

      {/* Action buttons */}
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
        {isProcessing && (
          <button onClick={cancel} className="btn-danger">Cancel job</button>
        )}
        {(isComplete || isFailed || isCancelled) && (
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
  const [cityText, setCityText]       = useState("");
  const [cities, setCities]           = useState([]);
  const [loading, setLoading]         = useState(false);
  const [error, setError]             = useState("");
  const [activeJobId, setActiveJobId] = useState(null);

  const maxCities = plan?.cities_per_job ?? 10;
  // Admin/staff accounts get an "unlimited" sentinel from /usage/plan — don't
  // render the ugly counter or the cap warning for them.
  const noCityCap = maxCities >= 9999;

  const commitCity = (text) => {
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
    if (e.key === "Backspace" && !cityText && cities.length > 0) {
      setCities(prev => prev.slice(0, -1));
    }
  };

  const removeCity = (city) => {
    setCities(prev => prev.filter(c => c !== city));
  };

  const submit = async (e) => {
    e.preventDefault();
    const allCities = cityText.trim()
      ? [...new Set([...cities, ...cityText.split(",").map(c => c.trim()).filter(Boolean)])].slice(0, maxCities)
      : cities;

    if (!industry.trim())       { setError("Industry is required"); return; }
    if (!state.trim())          { setError("State is required"); return; }
    if (allCities.length === 0) { setError("Add at least one city"); return; }

    setLoading(true); setError("");
    try {
      const job = await api.createJob({
        industry: industry.trim(),
        state: normalizeStateInput(state),
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
                  onChange={e => setState(e.target.value)}
                  placeholder="FL or Florida" maxLength={24} className="input mono" />
              </div>
            </div>

            <div>
              <label className="label">
                Cities
                <span className="ml-2 normal-case" style={{ color: "var(--text-3)", fontWeight: 400 }}>
                  {noCityCap ? cities.length : `${cities.length}/${maxCities}`} · Enter or comma to add
                </span>
              </label>

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

              {!noCityCap && cities.length >= maxCities && (
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
