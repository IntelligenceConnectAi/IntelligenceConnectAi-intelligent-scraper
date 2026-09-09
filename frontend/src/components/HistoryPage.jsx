import { useEffect, useState } from "react";
import { api } from "../lib/api";
import StatCard from "./StatCard";
import DonutChart from "./charts/DonutChart";
import BarListChart from "./charts/BarListChart";

const STATUS_COLORS = {
  Submitted: "var(--text-3)",
  Processing: "var(--info)",
  "Needs Information": "var(--warning)",
  Completed: "var(--accent)",
  Cancelled: "var(--text-2)",
  Failed: "var(--danger)",
};

function StatusBadge({ status }) {
  const config = {
    Submitted:          { cls: "badge-muted",   label: "Submitted" },
    Processing:         { cls: "badge-blue",    label: "Processing" },
    "Needs Information":{ cls: "badge-warning", label: "Needs Information" },
    Completed:          { cls: "badge-accent",  label: "Completed" },
    Cancelled:          { cls: "badge-muted",   label: "Cancelled" },
    Failed:             { cls: "badge-danger",  label: "Failed" },
  };
  const c = config[status] || config.Submitted;
  return <span className={`badge ${c.cls}`}>{c.label}</span>;
}

function fmt(iso) {
  if (!iso) return "—";
  return new Date(iso).toLocaleString("en-US", { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

export default function HistoryPage({ onNavigate, theme }) {
  const [stats, setStats]     = useState(null);
  const [charts, setCharts]   = useState(null);
  const [entries, setEntries] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError]     = useState("");
  const [dl, setDl]           = useState({});

  useEffect(() => {
    (async () => {
      setLoading(true); setError("");
      try {
        const [s, c, e] = await Promise.all([
          api.historyStats(), api.historyCharts(), api.listHistory(),
        ]);
        setStats(s); setCharts(c); setEntries(e);
      } catch (e) {
        setError(e.message);
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  const download = async (entry) => {
    setDl(p => ({ ...p, [entry.id]: true }));
    try {
      if (entry.source_type === "business") {
        try {
          const r = await api.downloadJob(entry.id, "with_website");
          window.open(r.url, "_blank");
        } catch {
          const r = await api.downloadJob(entry.id, "no_website");
          window.open(r.url, "_blank");
        }
      } else {
        const detail = await api.getPeopleLeadRequest(entry.id);
        if (detail.download_url) window.open(detail.download_url, "_blank");
        else alert("No file available for this request yet.");
      }
    } catch (e) {
      alert(`Download failed: ${e.message}`);
    } finally {
      setDl(p => ({ ...p, [entry.id]: false }));
    }
  };

  if (loading) return (
    <div className="card p-10 text-center animate-soft-pulse">
      <p className="text-sm" style={{ color: "var(--text-3)" }}>Loading history…</p>
    </div>
  );

  if (error) return (
    <div className="alert-danger">{error}</div>
  );

  return (
    <div className="space-y-5 animate-fade-in">
      {stats && (
        <div className="grid grid-cols-2 xl:grid-cols-3 gap-3">
          <StatCard label="Total Requests"     value={stats.total_requests} accent delay={0} />
          <StatCard label="Completed Requests" value={stats.completed_requests} delay={1} />
          <StatCard label="Active Requests"    value={stats.active_requests} delay={2} />
          <StatCard label="Failed Requests"    value={stats.failed_requests} delay={0} />
          <StatCard label="Total Leads Generated" value={stats.total_leads_generated} delay={1} />
          <StatCard label="Total Files Downloaded" value={stats.total_files_downloaded} delay={2} />
        </div>
      )}

      {charts && (
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
          <div className="card p-5 flex flex-col items-center">
            <p className="label self-start w-full">Status Distribution</p>
            <DonutChart key={theme} segments={charts.status_distribution.map(s => ({
              label: s.label, value: s.value, color: STATUS_COLORS[s.label] || "var(--text-3)",
            }))} />
          </div>
          <div className="card p-5 flex flex-col items-center">
            <p className="label self-start w-full">Business vs People</p>
            <DonutChart key={theme} segments={charts.business_vs_people.map((s, i) => ({
              label: s.label, value: s.value, color: i === 0 ? "var(--accent)" : "var(--info)",
            }))} />
          </div>
          <div className="card p-5">
            <p className="label mb-3">Most Requested Locations</p>
            <BarListChart key={theme} items={charts.most_requested_locations} />
          </div>
        </div>
      )}

      {entries.length === 0 ? (
        <div className="card p-12 text-center animate-fade-in">
          <p className="text-3xl mb-3">◫</p>
          <p className="font-medium" style={{ color: "var(--text-2)" }}>No requests yet</p>
          <p className="text-sm mt-1" style={{ color: "var(--text-3)" }}>
            Your Business and People Leads requests will appear here.
          </p>
        </div>
      ) : (
        <div className="card overflow-hidden">
          <div className="flex items-center justify-between px-5 py-3.5" style={{ borderBottom: "1px solid var(--border)" }}>
            <p className="text-sm font-semibold" style={{ color: "var(--text)" }}>All Requests</p>
            <span className="badge badge-muted mono">{entries.length} {entries.length === 1 ? "request" : "requests"}</span>
          </div>

          <div className="hidden md:block overflow-x-auto">
            <table className="w-full">
              <thead>
                <tr style={{ borderBottom: "1px solid var(--border)" }}>
                  {["Request","Type","Location","Requested","Delivered","Status","Created","Completed",""].map(h => (
                    <th key={h} className="px-4 py-3 text-left text-xs font-medium tracking-wider uppercase" style={{ color: "var(--text-3)" }}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {entries.map((e, i) => (
                  <tr key={e.id} style={{ borderTop: i > 0 ? "1px solid var(--border)" : "none" }}>
                    <td className="px-4 py-3 font-medium text-sm" style={{ color: "var(--text)" }}>
                      {e.request_name}
                      <span className="ml-2 badge badge-muted text-[10px]">{e.source_type === "business" ? "Business" : "People"}</span>
                    </td>
                    <td className="px-4 py-3 text-xs" style={{ color: "var(--text-2)" }}>{e.lead_type_or_industry}</td>
                    <td className="px-4 py-3 text-xs" style={{ color: "var(--text-3)" }}>{e.location}</td>
                    <td className="px-4 py-3 mono text-sm text-right" style={{ color: "var(--text-2)" }}>{e.requested_quantity}</td>
                    <td className="px-4 py-3 mono text-sm font-semibold text-right" style={{ color: "var(--text)" }}>{e.delivered_quantity}</td>
                    <td className="px-4 py-3"><StatusBadge status={e.status} /></td>
                    <td className="px-4 py-3 text-xs" style={{ color: "var(--text-3)" }}>{fmt(e.created_at)}</td>
                    <td className="px-4 py-3 text-xs" style={{ color: "var(--text-3)" }}>{fmt(e.completed_at)}</td>
                    <td className="px-4 py-3">
                      <div className="flex gap-1.5">
                        {e.status === "Completed" && (
                          <button onClick={() => download(e)} disabled={dl[e.id]}
                            className="badge badge-accent cursor-pointer hover:opacity-80 transition disabled:opacity-40">
                            {dl[e.id] ? "…" : "⬇"}
                          </button>
                        )}
                        <button onClick={() => onNavigate?.("my-leads")} className="badge badge-muted cursor-pointer hover:opacity-80 transition">
                          My Leads
                        </button>
                        <button onClick={() => onNavigate?.("support")} className="badge badge-muted cursor-pointer hover:opacity-80 transition">
                          Support
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {/* Mobile cards */}
          <div className="md:hidden divide-y" style={{ borderColor: "var(--border)" }}>
            {entries.map(e => (
              <div key={e.id} className="p-4 space-y-2">
                <div className="flex items-start justify-between gap-2">
                  <div>
                    <p className="font-semibold text-sm" style={{ color: "var(--text)" }}>{e.request_name}</p>
                    <p className="text-xs mt-0.5" style={{ color: "var(--text-3)" }}>{e.lead_type_or_industry} · {e.location}</p>
                  </div>
                  <StatusBadge status={e.status} />
                </div>
                <div className="flex gap-4 text-xs mono" style={{ color: "var(--text-2)" }}>
                  <span><span style={{ color: "var(--text)" }}>{e.delivered_quantity}</span> / {e.requested_quantity}</span>
                  <span style={{ color: "var(--text-3)" }}>{fmt(e.created_at)}</span>
                </div>
                {e.status === "Completed" && (
                  <button onClick={() => download(e)} className="badge badge-accent cursor-pointer">⬇ Download</button>
                )}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
