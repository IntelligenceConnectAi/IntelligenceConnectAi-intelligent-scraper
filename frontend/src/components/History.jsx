import { useEffect, useState } from "react";
import { api } from "../lib/api";

function StatusBadge({ status }) {
  const config = {
    pending:       { cls: "badge-muted",   label: "Queued" },
    running:       { cls: "badge-blue",    label: "Running" },
    preprocessing: { cls: "badge-purple",  label: "Processing" },
    email_scraping:{ cls: "badge-accent",  label: "Emails" },
    done:          { cls: "badge-accent",  label: "Done" },
    failed:        { cls: "badge-danger",  label: "Failed" },
    canceled:      { cls: "badge-muted",   label: "Canceled" },
  };
  const c = config[status] || config.pending;
  return <span className={`badge ${c.cls}`}>{c.label}</span>;
}

function fmt(iso) {
  if (!iso) return "—";
  return new Date(iso).toLocaleString("en-US", {
    month: "short", day: "numeric",
    hour: "2-digit", minute: "2-digit",
  });
}

export default function History() {
  const [jobs, setJobs]         = useState([]);
  const [loading, setLoading]   = useState(true);
  const [error, setError]       = useState("");
  const [dl, setDl]             = useState({});

  useEffect(() => {
    (async () => {
      try { setJobs(await api.listJobs()); }
      catch (e) { setError(e.message); }
      finally { setLoading(false); }
    })();
  }, []);

  const download = async (jobId, type) => {
    const key = `${jobId}-${type}`;
    setDl(p => ({ ...p, [key]: true }));
    try { const r = await api.downloadJob(jobId, type); window.open(r.url, "_blank"); }
    catch (e) { alert(`Download failed: ${e.message}`); }
    finally { setDl(p => ({ ...p, [key]: false })); }
  };

  if (loading) return (
    <div className="card p-10 text-center animate-soft-pulse">
      <p className="text-sm" style={{ color: "var(--text-3)" }}>Loading history…</p>
    </div>
  );

  if (error) return (
    <div className="p-4 rounded-lg text-sm" style={{
      background: "rgba(255,77,106,0.08)",
      border: "1px solid rgba(255,77,106,0.2)",
      color: "var(--danger)"
    }}>{error}</div>
  );

  if (jobs.length === 0) return (
    <div className="card p-12 text-center animate-fade-in">
      <p className="text-3xl mb-3">◫</p>
      <p className="font-medium" style={{ color: "var(--text-2)" }}>No jobs yet</p>
      <p className="text-sm mt-1" style={{ color: "var(--text-3)" }}>Run your first scrape to see history here.</p>
    </div>
  );

  return (
    <div className="card overflow-hidden animate-fade-in">
      {/* Header */}
      <div className="flex items-center justify-between px-5 py-3.5"
        style={{ borderBottom: "1px solid var(--border)" }}>
        <p className="text-sm font-semibold" style={{ color: "var(--text)" }}>Job History</p>
        <span className="badge badge-muted mono">{jobs.length} jobs</span>
      </div>

      {/* Desktop table */}
      <div className="hidden md:block overflow-x-auto">
        <table className="w-full">
          <thead>
            <tr style={{ borderBottom: "1px solid var(--border)" }}>
              {["Industry","State","Cities","Status","Leads","Emails","Created",""].map(h => (
                <th key={h} className="px-4 py-3 text-left text-xs font-medium tracking-wider uppercase" style={{ color: "var(--text-3)" }}>
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {jobs.map((job, i) => (
              <tr key={job.id} style={{ borderTop: i > 0 ? "1px solid var(--border)" : "none" }}
                className="transition-colors" onMouseEnter={e => e.currentTarget.style.background = "rgba(255,255,255,0.02)"}
                onMouseLeave={e => e.currentTarget.style.background = ""}>
                <td className="px-4 py-3 font-medium text-sm" style={{ color: "var(--text)" }}>{job.industry}</td>
                <td className="px-4 py-3 mono text-xs" style={{ color: "var(--text-2)" }}>{job.state}</td>
                <td className="px-4 py-3 text-xs max-w-[140px] truncate" style={{ color: "var(--text-3)" }}
                  title={job.cities.join(", ")}>
                  {job.cities.slice(0,3).join(", ")}{job.cities.length > 3 ? ` +${job.cities.length - 3}` : ""}
                </td>
                <td className="px-4 py-3"><StatusBadge status={job.status} /></td>
                <td className="px-4 py-3 mono text-sm font-semibold text-right" style={{ color: "var(--text)" }}>
                  {(job.total_clean ?? 0).toLocaleString()}
                </td>
                <td className="px-4 py-3 mono text-sm text-right" style={{ color: "var(--text-2)" }}>
                  {(job.emails_found ?? 0).toLocaleString()}
                </td>
                <td className="px-4 py-3 text-xs" style={{ color: "var(--text-3)" }}>{fmt(job.created_at)}</td>
                <td className="px-4 py-3">
                  {job.status === "done" ? (
                    <div className="flex gap-1.5">
                      <button onClick={() => download(job.id, "with_website")}
                        disabled={dl[`${job.id}-with_website`]}
                        className="badge badge-accent cursor-pointer hover:opacity-80 transition disabled:opacity-40">
                        {dl[`${job.id}-with_website`] ? "…" : "⬇ Web"}
                      </button>
                      <button onClick={() => download(job.id, "no_website")}
                        disabled={dl[`${job.id}-no_website`]}
                        className="badge badge-muted cursor-pointer hover:opacity-80 transition disabled:opacity-40">
                        {dl[`${job.id}-no_website`] ? "…" : "⬇ No web"}
                      </button>
                    </div>
                  ) : <span className="text-xs" style={{ color: "var(--text-3)" }}>—</span>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Mobile cards */}
      <div className="md:hidden divide-y" style={{ borderColor: "var(--border)" }}>
        {jobs.map(job => (
          <div key={job.id} className="p-4 space-y-3">
            <div className="flex items-start justify-between gap-2">
              <div>
                <p className="font-semibold text-sm" style={{ color: "var(--text)" }}>{job.industry} — {job.state}</p>
                <p className="text-xs mt-0.5" style={{ color: "var(--text-3)" }}>{job.cities.join(", ")}</p>
              </div>
              <StatusBadge status={job.status} />
            </div>
            <div className="flex gap-4 text-xs mono" style={{ color: "var(--text-2)" }}>
              <span><span style={{ color: "var(--text)" }}>{job.total_clean ?? 0}</span> leads</span>
              <span><span style={{ color: "var(--text)" }}>{job.emails_found ?? 0}</span> emails</span>
              <span style={{ color: "var(--text-3)" }}>{fmt(job.created_at)}</span>
            </div>
            {job.status === "done" && (
              <div className="flex gap-2">
                <button onClick={() => download(job.id, "with_website")} className="badge badge-accent cursor-pointer">⬇ With website</button>
                <button onClick={() => download(job.id, "no_website")}   className="badge badge-muted cursor-pointer">⬇ No website</button>
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
