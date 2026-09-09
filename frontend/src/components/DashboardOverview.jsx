import { useEffect, useMemo, useState } from "react";
import {
  Gauge, TrendingUp, Layers, LoaderCircle, Activity, CircleCheckBig,
  Link as LinkIcon, Unlink, Mail, Building2, CalendarClock, CalendarDays,
} from "lucide-react";
import { api } from "../lib/api";
import StatCard from "./StatCard";
import UsageRadialChart from "./charts/UsageRadialChart";
import DonutChart from "./charts/DonutChart";
import LeadsTrendChart from "./charts/LeadsTrendChart";
import EmailDiscoveryFluidGauge from "./charts/EmailDiscoveryFluidGauge";
import SecureProcessingGlobe from "./SecureProcessingGlobe";
import SecureActivityTicker from "./SecureActivityTicker";
import StatusIndicator from "./StatusIndicator";
import DashboardGreeting from "./DashboardGreeting";

// KPI cards are hidden for now (kept, not deleted, so they can come back with a one-line flip).
const SHOW_KPI_ROW = false;

function fmtDate(iso) {
  if (!iso) return "—";
  return new Date(iso).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
}

function fmtShort(iso) {
  return new Date(iso).toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

// Real, already-fetched history entries bucketed by day client-side — no
// fabricated data, no new backend endpoint (§11.6).
function bucketLeadsByDay(entries, days = 14) {
  const buckets = [];
  const now = new Date();
  for (let i = days - 1; i >= 0; i--) {
    const d = new Date(now);
    d.setDate(d.getDate() - i);
    buckets.push({ key: d.toISOString().slice(0, 10), label: fmtShort(d), business: 0, people: 0 });
  }
  const byKey = Object.fromEntries(buckets.map(b => [b.key, b]));
  for (const e of entries) {
    if (!e.completed_at) continue;
    const bucket = byKey[e.completed_at.slice(0, 10)];
    if (!bucket) continue;
    const qty = e.delivered_quantity || 0;
    if (e.source_type === "business") bucket.business += qty;
    else bucket.people += qty;
  }
  return buckets;
}

export default function DashboardOverview({ onNavigate, profile, theme }) {
  const [data, setData]                   = useState(null);
  const [businessRequests, setBusiness]    = useState([]);
  const [peopleRequests, setPeople]        = useState([]);
  const [historyEntries, setHistoryEntries] = useState([]);
  const [recentFiles, setRecentFiles]      = useState([]);
  const [loading, setLoading]              = useState(true);
  const [error, setError]                  = useState("");

  useEffect(() => {
    (async () => {
      setLoading(true); setError("");
      try {
        const [dash, biz, people, history, files] = await Promise.all([
          api.clientDashboard(),
          api.listBusinessRequests().catch(() => []),
          api.listPeopleLeadRequests().catch(() => []),
          api.listHistory().catch(() => []),
          api.listLeadFiles().catch(() => []),
        ]);
        setData(dash);
        setBusiness(biz);
        setPeople(people);
        setHistoryEntries(history);
        setRecentFiles(
          [...files]
            .sort((a, b) => new Date(b.created_at) - new Date(a.created_at))
            .slice(0, 3)
        );
      } catch (e) {
        setError(e.message);
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  const trendPoints = useMemo(() => bucketLeadsByDay(historyEntries), [historyEntries]);

  if (loading) return (
    <div className="dashboard-panel text-center animate-soft-pulse">
      <p className="text-sm" style={{ color: "var(--text-muted)" }}>Loading dashboard…</p>
    </div>
  );

  if (error) return (
    <div className="alert-danger">{error}</div>
  );

  const activeBusiness = businessRequests
    .filter(r => r.status === "Submitted" || r.status === "Processing")
    .map(r => ({ ...r, _kind: "business" }));
  const activePeople = peopleRequests
    .filter(r => r.status === "Submitted" || r.status === "Processing")
    .map(r => ({ ...r, _kind: "people" }));
  const allActive = [...activeBusiness, ...activePeople]
    .sort((a, b) => new Date(b.created_at) - new Date(a.created_at));
  const current = allActive[0];
  const moreActiveCount = allActive.length - 1;

  const activeList = allActive.slice(0, 5);
  const businessGenerated = (data.total_with_website ?? 0) + (data.total_no_website ?? 0);

  return (
    <div className="space-y-5 animate-fade-in">
      {/* 1 — Greeting + quote of the day */}
      <DashboardGreeting profile={profile} />

      {SHOW_KPI_ROW && (
        <div className="dashboard-grid">
          <div className="span-3 span-xl-3"><StatCard icon={Gauge} label="Monthly Lead Limit" value={data.monthly_limit ?? 0} delay={0} /></div>
          <div className="span-3 span-xl-3"><StatCard icon={TrendingUp} label="Leads Used" value={data.leads_used_period} accent delay={1} /></div>
          <div className="span-3 span-xl-3"><StatCard icon={Layers} label="Leads Remaining" value={data.leads_remaining_period} delay={2} /></div>
          <div className="span-3 span-xl-3"><StatCard icon={LoaderCircle} label="Leads Processing" value={data.leads_processing} delay={3} /></div>
          <div className="span-3 span-xl-3"><StatCard icon={Activity} label="Active Requests" value={data.active_requests_count} delay={0} /></div>
          <div className="span-3 span-xl-3"><StatCard icon={CircleCheckBig} label="Completed Requests" value={data.completed_requests_count} delay={1} /></div>
          <div className="span-3 span-xl-3"><StatCard icon={LinkIcon} label="Businesses With Website" value={data.total_with_website} delay={2} /></div>
          <div className="span-3 span-xl-3"><StatCard icon={Unlink} label="Businesses Without Website" value={data.total_no_website} delay={3} /></div>
          <div className="span-3 span-xl-3"><StatCard icon={Mail} label="Emails Found" value={data.total_emails_found} delay={0} /></div>
          <div className="span-3 span-xl-3"><StatCard icon={Building2} label="Business Leads Generated" value={businessGenerated} delay={1} /></div>
          <div className="span-3 span-xl-3"><StatCard icon={CalendarClock} label="Package Renewal" value={fmtDate(data.package_renewal_date)} delay={2} /></div>
          <div className="span-3 span-xl-3"><StatCard icon={CalendarDays} label="Days Until Reset" value={data.days_until_reset ?? 0} delay={3} /></div>
        </div>
      )}

      {/* 2 — Secure processing panel */}
      {current && (
        <div className="dashboard-grid">
          <div className="span-12">
            <div className="flex items-center justify-between mb-2 flex-wrap gap-2">
              <p className="section-title">
                {current._kind === "business"
                  ? `${current.industry} — ${current.state}`
                  : current.request_name}
              </p>
              <div className="flex items-center gap-3">
                <StatusIndicator status={current.status} variant={current._kind} />
                {moreActiveCount > 0 && (
                  <button
                    className="text-xs"
                    style={{ color: "var(--brand-purple-bright)" }}
                    onClick={() => onNavigate?.("get-leads", current._kind === "business" ? "business" : "people")}
                  >
                    +{moreActiveCount} more processing →
                  </button>
                )}
              </div>
            </div>
            <SecureProcessingGlobe variant={current._kind === "business" ? "business" : "people"} />
          </div>
        </div>
      )}

      {/* 3 — Activity ticker */}
      <div className="dashboard-grid">
        <div className="span-12">
          <SecureActivityTicker />
        </div>
      </div>

      {/* 4 — Usage + Trend */}
      <div className="dashboard-grid">
        <div className="span-4 span-xl-4">
          <UsageRadialChart
            key={theme}
            used={data.leads_used_period}
            remaining={data.leads_remaining_period}
            limit={data.monthly_limit ?? 0}
            renewalDate={data.package_renewal_date}
            daysUntilReset={data.days_until_reset}
            processingCount={data.leads_processing}
          />
        </div>
        <div className="span-8 span-xl-8">
          <LeadsTrendChart key={theme} points={trendPoints} />
        </div>
      </div>

      {/* 5 — Lead composition */}
      <div className="dashboard-grid">
        <div className="span-4 span-xl-4">
          <div className="dashboard-panel flex flex-col items-center">
            <p className="dashboard-panel-title self-start w-full">Business vs People</p>
            <DonutChart
              key={theme}
              segments={[
                { label: "Business Leads", value: businessGenerated, color: "var(--business-secondary)" },
                { label: "People Leads", value: data.people_leads_delivered ?? 0, color: "var(--people-secondary)" },
              ]}
              centerValue={(businessGenerated + (data.people_leads_delivered ?? 0)) || null}
              centerLabel="leads"
            />
          </div>
        </div>
        <div className="span-4 span-xl-4">
          <div className="dashboard-panel flex flex-col items-center">
            <p className="dashboard-panel-title self-start w-full">Website Coverage</p>
            <DonutChart
              key={theme}
              segments={[
                { label: "With Website", value: data.total_with_website, color: "var(--business-secondary)" },
                { label: "Without Website", value: data.total_no_website, color: "var(--text-muted)" },
              ]}
              centerValue={businessGenerated || null}
              centerLabel="businesses"
            />
          </div>
        </div>
        <div className="span-4 span-xl-4">
          <EmailDiscoveryFluidGauge found={data.total_emails_found ?? 0} attempted={data.total_with_website ?? 0} />
        </div>
      </div>

      {/* 6 — Operational data */}
      <div className="dashboard-grid">
        <div className="span-7 span-xl-7">
          <div className="dashboard-panel" style={{ padding: 0, overflow: "hidden" }}>
            <div className="flex items-center justify-between px-5 py-3.5" style={{ borderBottom: "1px solid var(--border-soft)" }}>
              <p className="section-title" style={{ margin: 0 }}>Active Requests</p>
              <button onClick={() => onNavigate?.("get-leads", "business")} className="text-xs" style={{ color: "var(--brand-purple-bright)" }}>
                View all →
              </button>
            </div>
            {activeList.length === 0 ? (
              <p className="text-sm p-5" style={{ color: "var(--text-muted)" }}>No active requests right now.</p>
            ) : (
              <div className="divide-y" style={{ borderColor: "var(--border-soft)" }}>
                {activeList.map(r => (
                  <div key={r.id} className="flex items-center justify-between px-5 py-3">
                    <div>
                      <p className="text-sm font-medium" style={{ color: "var(--text-primary)" }}>
                        {r._kind === "business" ? `${r.industry} — ${r.state}` : r.request_name}
                      </p>
                      <p className="text-xs" style={{ color: "var(--text-muted)" }}>
                        {r._kind === "business" ? r.cities?.join(", ") : [r.city, r.state].filter(Boolean).join(", ")}
                      </p>
                    </div>
                    <StatusIndicator status={r.status} variant={r._kind} />
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>

        <div className="span-5 span-xl-5">
          <div className="dashboard-panel" style={{ padding: 0, overflow: "hidden" }}>
            <div className="flex items-center justify-between px-5 py-3.5" style={{ borderBottom: "1px solid var(--border-soft)" }}>
              <p className="section-title" style={{ margin: 0 }}>Recent Files</p>
              <button onClick={() => onNavigate?.("my-leads")} className="text-xs" style={{ color: "var(--brand-purple-bright)" }}>
                View all →
              </button>
            </div>
            {recentFiles.length === 0 ? (
              <p className="text-sm p-5" style={{ color: "var(--text-muted)" }}>
                Completed requests will appear here as downloadable files.
              </p>
            ) : (
              <div className="divide-y" style={{ borderColor: "var(--border-soft)" }}>
                {recentFiles.map(f => (
                  <button
                    key={f.id}
                    onClick={() => onNavigate?.("my-leads")}
                    className="w-full flex items-center justify-between px-5 py-3 text-left"
                  >
                    <div className="min-w-0">
                      <p className="text-sm font-medium truncate" style={{ color: "var(--text-primary)" }}>{f.display_name}</p>
                      <p className="text-xs" style={{ color: "var(--text-muted)" }}>
                        {(f.record_count ?? 0).toLocaleString()} records · {fmtShort(f.created_at)}
                      </p>
                    </div>
                    <span className={`lead-dot lead-dot--${f.source_type === "business" ? "business" : "people"}`} aria-hidden="true" />
                  </button>
                ))}
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
