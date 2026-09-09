import { useEffect, useState } from "react";
import { api } from "../lib/api";

const STATUS_BADGE = {
  pending: "badge-muted", running: "badge-blue animate-soft-pulse",
  done: "badge-accent", failed: "badge-danger", canceled: "badge-muted",
};

function StatusBadge({ status }) {
  return <span className={`badge ${STATUS_BADGE[status] || "badge-muted"}`}>{status}</span>;
}

function fmt(iso) {
  if (!iso) return "—";
  return new Date(iso).toLocaleString("en-US", { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

function JobDetail({ jobId, onBack, onChanged }) {
  const [job, setJob] = useState(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const load = () => api.adminGetJob(jobId).then(setJob).catch(e => setError(e.message));
  useEffect(() => { load(); }, [jobId]);

  const retry = async () => {
    setBusy(true);
    try { await api.adminRetryJob(jobId); await load(); onChanged(); }
    catch (e) { alert(`Retry failed: ${e.message}`); }
    finally { setBusy(false); }
  };
  const cancel = async () => {
    if (!confirm("Cancel this job?")) return;
    setBusy(true);
    try { await api.adminCancelJob(jobId); await load(); onChanged(); }
    catch (e) { alert(`Cancel failed: ${e.message}`); }
    finally { setBusy(false); }
  };

  if (error) return <p className="text-sm" style={{ color: "var(--danger)" }}>{error}</p>;
  if (!job) return <p className="text-sm animate-soft-pulse" style={{ color: "var(--text-3)" }}>Loading…</p>;

  return (
    <div className="space-y-5 animate-fade-in">
      <button onClick={onBack} className="btn-ghost text-xs">← Back to list</button>
      <div className="card p-5">
        <div className="flex items-start justify-between gap-3 mb-4">
          <div>
            <p className="font-semibold" style={{ color: "var(--text)" }}>{job.industry} — {job.state}</p>
            <p className="text-xs mt-0.5" style={{ color: "var(--text-3)" }}>{job.organization_name || "—"} · {job.requester_email}</p>
          </div>
          <StatusBadge status={job.status} />
        </div>
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-4">
          <div className="text-center"><p className="stat-number text-xl">{job.cities_done}/{job.cities_total}</p><p className="text-[10px] uppercase" style={{ color: "var(--text-3)" }}>Cities</p></div>
          <div className="text-center"><p className="stat-number text-xl">{job.total_clean}</p><p className="text-[10px] uppercase" style={{ color: "var(--text-3)" }}>Leads</p></div>
          <div className="text-center"><p className="stat-number text-xl">{job.with_website}</p><p className="text-[10px] uppercase" style={{ color: "var(--text-3)" }}>With Website</p></div>
          <div className="text-center"><p className="stat-number text-xl">{job.emails_found}</p><p className="text-[10px] uppercase" style={{ color: "var(--text-3)" }}>Emails</p></div>
        </div>
        {job.error_message && (
          <p className="alert-danger mb-3">{job.error_message}</p>
        )}
        <p className="text-xs mb-4" style={{ color: "var(--text-3)" }}>
          Created {fmt(job.created_at)} · Started {fmt(job.started_at)} · Completed {fmt(job.completed_at)}
        </p>
        <div className="flex gap-2">
          {(job.status === "failed" || job.status === "canceled") && (
            <button onClick={retry} disabled={busy} className="btn-primary text-sm">Retry</button>
          )}
          {(job.status === "pending" || job.status === "running") && (
            <button onClick={cancel} disabled={busy} className="btn-danger text-sm">Cancel</button>
          )}
        </div>
      </div>

      {job.city_progress.length > 0 && (
        <div className="card overflow-hidden">
          <div className="px-5 py-3.5" style={{ borderBottom: "1px solid var(--border)" }}>
            <p className="text-sm font-semibold" style={{ color: "var(--text)" }}>City Progress</p>
          </div>
          <div className="divide-y" style={{ borderColor: "var(--border)" }}>
            {job.city_progress.map(c => (
              <div key={c.city} className="flex items-center justify-between px-5 py-2.5">
                <span className="text-sm" style={{ color: "var(--text)" }}>{c.city}</span>
                <span className="text-xs mono" style={{ color: "var(--text-2)" }}>{c.maps_status} · {c.maps_leads} leads</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

export default function AdminBusinessRequests() {
  const [jobs, setJobs] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [viewingId, setViewingId] = useState(null);

  const load = async () => {
    setLoading(true); setError("");
    try { setJobs(await api.adminListJobs()); }
    catch (e) { setError(e.message); }
    finally { setLoading(false); }
  };

  useEffect(() => { load(); }, []);

  if (viewingId) return <JobDetail jobId={viewingId} onBack={() => setViewingId(null)} onChanged={load} />;

  if (loading) return (
    <div className="card p-10 text-center animate-soft-pulse">
      <p className="text-sm" style={{ color: "var(--text-3)" }}>Loading business requests…</p>
    </div>
  );
  if (error) return <p className="text-sm" style={{ color: "var(--danger)" }}>{error}</p>;

  return (
    <div className="card overflow-hidden animate-fade-in">
      <div className="px-5 py-3.5 flex items-center justify-between" style={{ borderBottom: "1px solid var(--border)" }}>
        <p className="text-sm font-semibold" style={{ color: "var(--text)" }}>Business Requests</p>
        <span className="badge badge-muted mono">{jobs.length}</span>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full">
          <thead>
            <tr style={{ borderBottom: "1px solid var(--border)" }}>
              {["Industry / State", "Client", "Status", "Leads", "Created", ""].map(h => (
                <th key={h} className="px-4 py-3 text-left text-xs font-medium tracking-wider uppercase" style={{ color: "var(--text-3)" }}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {jobs.map((j, i) => (
              <tr key={j.id} style={{ borderTop: i > 0 ? "1px solid var(--border)" : "none" }}>
                <td className="px-4 py-3 text-sm font-medium" style={{ color: "var(--text)" }}>{j.industry} — {j.state}</td>
                <td className="px-4 py-3 text-xs" style={{ color: "var(--text-2)" }}>{j.organization_name || j.requester_email}</td>
                <td className="px-4 py-3"><StatusBadge status={j.status} /></td>
                <td className="px-4 py-3 text-sm mono text-right" style={{ color: "var(--text)" }}>{j.total_clean}</td>
                <td className="px-4 py-3 text-xs" style={{ color: "var(--text-3)" }}>{fmt(j.created_at)}</td>
                <td className="px-4 py-3">
                  <button onClick={() => setViewingId(j.id)} className="badge badge-muted cursor-pointer hover:opacity-80 transition">View →</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
