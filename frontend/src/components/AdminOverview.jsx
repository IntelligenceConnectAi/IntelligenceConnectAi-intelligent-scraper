import { useEffect, useState } from "react";
import { api } from "../lib/api";
import StatCard from "./StatCard";
import DonutChart from "./charts/DonutChart";
import BarListChart from "./charts/BarListChart";

const JOB_STATUS_COLORS = {
  pending: "var(--text-3)", running: "var(--info)", done: "var(--accent)",
  failed: "var(--danger)", canceled: "var(--text-2)",
};
const TICKET_STATUS_COLORS = {
  open: "var(--info)", in_progress: "var(--info)", escalated: "var(--warning)",
  resolved: "var(--accent)", closed: "var(--text-2)",
};
const WORKER_STATUS_LABELS = { healthy: "Healthy", degraded: "Degraded", down: "Down" };

function fmtAge(iso) {
  if (!iso) return "never seen";
  const secs = Math.round((Date.now() - new Date(iso).getTime()) / 1000);
  if (secs < 60) return `${secs}s ago`;
  const mins = Math.round(secs / 60);
  if (mins < 60) return `${mins}m ago`;
  return `${Math.round(mins / 60)}h ago`;
}

export default function AdminOverview({ theme }) {
  const [stats, setStats] = useState(null);
  const [charts, setCharts] = useState(null);
  const [error, setError] = useState("");

  useEffect(() => {
    Promise.all([api.adminDashboard(), api.adminDashboardCharts()])
      .then(([s, c]) => { setStats(s); setCharts(c); })
      .catch(e => setError(e.message));
  }, []);

  if (error) return (
    <div className="alert-danger">{error}</div>
  );

  if (!stats) return (
    <div className="card p-10 text-center animate-soft-pulse">
      <p className="text-sm" style={{ color: "var(--text-3)" }}>Loading overview…</p>
    </div>
  );

  return (
    <div className="space-y-5 animate-fade-in">
      <div className="grid grid-cols-2 xl:grid-cols-4 gap-3">
        <StatCard label="Total Clients" value={stats.total_clients} accent delay={0} />
        <StatCard label="Active Business Jobs" value={stats.active_business_jobs} delay={1} />
        <StatCard label="Failed Business Jobs" value={stats.failed_business_jobs} delay={2} />
        <StatCard label="Pending People Requests" value={stats.pending_people_requests} delay={3} />
        <StatCard label="Open Support Tickets" value={stats.open_support_tickets} delay={0} />
        <StatCard label="Leads Generated (Lifetime)" value={stats.total_leads_generated} delay={1} />
        <StatCard label="Requests Completed Today" value={stats.requests_completed_today} delay={2} />
        <StatCard label="Active Admins" value={stats.active_admins_count} delay={3} />
        <StatCard
          label="Worker Health"
          value={WORKER_STATUS_LABELS[stats.worker_status] || "Down"}
          footnote={`last seen ${fmtAge(stats.worker_last_seen_at)}`}
          delay={0}
        />
      </div>

      {charts && (
        <div className="grid grid-cols-1 lg:grid-cols-4 gap-4">
          <div className="card p-5 flex flex-col items-center">
            <p className="label self-start w-full">Business vs People</p>
            <DonutChart key={theme} segments={charts.business_vs_people.map((s, i) => ({
              label: s.label, value: s.value, color: i === 0 ? "var(--accent)" : "var(--info)",
            }))} />
          </div>
          <div className="card p-5 flex flex-col items-center">
            <p className="label self-start w-full">Business Job Status</p>
            <DonutChart key={theme} segments={charts.business_job_status.map(s => ({
              label: s.label, value: s.value, color: JOB_STATUS_COLORS[s.label] || "var(--text-3)",
            }))} />
          </div>
          <div className="card p-5">
            <p className="label mb-3">Top Clients by Leads</p>
            <BarListChart key={theme} items={charts.top_clients_by_leads} />
          </div>
          <div className="card p-5 flex flex-col items-center">
            <p className="label self-start w-full">Tickets by Status</p>
            <DonutChart key={theme} segments={charts.tickets_by_status.map(s => ({
              label: s.label, value: s.value, color: TICKET_STATUS_COLORS[s.label] || "var(--text-3)",
            }))} />
          </div>
        </div>
      )}
    </div>
  );
}
