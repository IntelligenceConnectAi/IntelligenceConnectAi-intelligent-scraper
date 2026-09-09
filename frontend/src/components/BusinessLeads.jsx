import { useEffect, useState } from "react";
import { api } from "../lib/api";
import RequestTabs from "./RequestTabs";
import RequestsTable from "./RequestsTable";
import ScrapeLeads, { JobProgress } from "./ScrapeLeads";

export default function BusinessLeads({ plan }) {
  const [tab, setTab]           = useState("new");
  const [requests, setRequests] = useState([]);
  const [loading, setLoading]   = useState(true);
  const [error, setError]       = useState("");
  const [viewingJobId, setViewingJobId] = useState(null);

  const load = async () => {
    setLoading(true); setError("");
    try { setRequests(await api.listBusinessRequests()); }
    catch (e) { setError(e.message); }
    finally { setLoading(false); }
  };

  useEffect(() => { load(); }, []);
  // Refresh whenever Active/Completed is opened so newly created or
  // just-finished requests show up without a full page reload.
  useEffect(() => {
    if (tab === "active" || tab === "completed") load();
  }, [tab]);

  const activeRequests    = requests.filter(r => r.status === "Submitted" || r.status === "Processing");
  const completedRequests = requests.filter(r => !["Submitted", "Processing"].includes(r.status));

  const tabs = [
    { id: "new",       label: "New Request" },
    { id: "active",    label: "Active Requests",    count: activeRequests.length },
    { id: "completed", label: "Completed Requests", count: completedRequests.length },
  ];

  return (
    <div className="space-y-4 animate-fade-in">
      <RequestTabs tabs={tabs} activeTab={tab} onChange={(id) => { setViewingJobId(null); setTab(id); }} />

      {tab === "new" && <ScrapeLeads plan={plan} />}

      {tab === "active" && (
        viewingJobId ? (
          <div className="card p-6">
            <button onClick={() => setViewingJobId(null)} className="btn-ghost text-xs mb-4">← Back to list</button>
            <JobProgress jobId={viewingJobId} onNewJob={() => setViewingJobId(null)} />
          </div>
        ) : loading ? (
          <div className="card p-10 text-center animate-soft-pulse">
            <p className="text-sm" style={{ color: "var(--text-3)" }}>Loading…</p>
          </div>
        ) : error ? (
          <div className="alert-danger">{error}</div>
        ) : activeRequests.length === 0 ? (
          <div className="card p-12 text-center animate-fade-in">
            <p className="text-3xl mb-3">⚡</p>
            <p className="font-medium" style={{ color: "var(--text-2)" }}>No active requests</p>
            <p className="text-sm mt-1" style={{ color: "var(--text-3)" }}>
              Start a new scrape to see it here while it processes.
            </p>
          </div>
        ) : (
          <div className="card overflow-hidden">
            <div className="divide-y" style={{ borderColor: "var(--border)" }}>
              {activeRequests.map(r => (
                <button key={r.id} onClick={() => setViewingJobId(r.id)}
                  className="w-full flex items-center justify-between px-5 py-3.5 text-left transition"
                  style={{ background: "transparent" }}
                  onMouseEnter={e => e.currentTarget.style.background = "var(--row-hover)"}
                  onMouseLeave={e => e.currentTarget.style.background = "transparent"}>
                  <div>
                    <p className="text-sm font-medium" style={{ color: "var(--text)" }}>{r.industry} — {r.state}</p>
                    <p className="text-xs" style={{ color: "var(--text-3)" }}>{r.cities?.join(", ")}</p>
                  </div>
                  <span className="badge badge-blue animate-soft-pulse">{r.status}</span>
                </button>
              ))}
            </div>
          </div>
        )
      )}

      {tab === "completed" && (
        loading ? (
          <div className="card p-10 text-center animate-soft-pulse">
            <p className="text-sm" style={{ color: "var(--text-3)" }}>Loading…</p>
          </div>
        ) : error ? (
          <div className="alert-danger">{error}</div>
        ) : (
          <RequestsTable
            jobs={completedRequests}
            emptyLabel="No completed requests yet"
            emptyHint="Completed scrapes will appear here."
          />
        )
      )}
    </div>
  );
}
