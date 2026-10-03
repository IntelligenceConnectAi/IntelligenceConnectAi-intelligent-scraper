import { useEffect, useState } from "react";
import { api } from "../lib/api";
import StatCard from "./StatCard";
import DonutChart from "./charts/DonutChart";
import BarListChart from "./charts/BarListChart";

const CATEGORY_LABELS = {
  business_with_website: "With Website",
  business_no_website: "Without Website",
  business_with_website_email: "With Email",
  business_with_website_no_email: "Without Email",
  people_leads: "People Leads",
};

function fmt(iso) {
  if (!iso) return "—";
  return new Date(iso).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
}

function FileCard({ file, onNavigate, onRenamed }) {
  const [expanded, setExpanded]   = useState(false);
  const [renaming, setRenaming]   = useState(false);
  const [nameInput, setNameInput] = useState(file.display_name);
  const [saving, setSaving]       = useState(false);
  const [downloading, setDownloading] = useState(false);

  const saveRename = async () => {
    if (!nameInput.trim() || nameInput === file.display_name) { setRenaming(false); return; }
    setSaving(true);
    try { await api.renameLeadFile(file.id, nameInput.trim()); onRenamed(); }
    catch (e) { alert(`Rename failed: ${e.message}`); }
    finally { setSaving(false); setRenaming(false); }
  };

  const download = async () => {
    setDownloading(true);
    try { const r = await api.downloadLeadFile(file.id); window.open(r.url, "_blank"); onRenamed(); }
    catch (e) { alert(`Download failed: ${e.message}`); }
    finally { setDownloading(false); }
  };

  return (
    <div className="card p-4">
      <div className="flex items-start justify-between gap-2 mb-2">
        {renaming ? (
          <div className="flex gap-1 flex-1">
            <input value={nameInput} onChange={e => setNameInput(e.target.value)}
              onKeyDown={e => e.key === "Enter" && saveRename()}
              className="input text-sm flex-1" style={{ padding: "4px 8px" }} autoFocus />
            <button onClick={saveRename} disabled={saving} className="btn-ghost text-xs">✓</button>
          </div>
        ) : (
          <button onClick={() => { setNameInput(file.display_name); setRenaming(true); }}
            className="text-sm font-medium text-left hover:opacity-70 transition" style={{ color: "var(--text)" }}>
            {file.display_name}
          </button>
        )}
        <span className={`badge ${file.download_count > 0 ? "badge-accent" : "badge-muted"} shrink-0`}>
          {file.download_count > 0 ? "Downloaded" : "Not downloaded"}
        </span>
      </div>

      <div className="flex flex-wrap gap-1.5 mb-3">
        <span className="badge badge-muted">{file.source_type === "business" ? "Business" : "People"}</span>
        <span className="badge badge-muted">{CATEGORY_LABELS[file.file_category] || file.file_category}</span>
        {file.industry_or_category && <span className="badge badge-muted">{file.industry_or_category}</span>}
      </div>

      <p className="text-xs mb-3" style={{ color: "var(--text-3)" }}>
        {[file.city, file.state].filter(Boolean).join(", ") || "—"}
      </p>

      <div className="grid grid-cols-3 gap-2 mb-3 text-center">
        <div>
          <p className="stat-number text-lg">{file.record_count}</p>
          <p className="text-[10px] uppercase" style={{ color: "var(--text-3)" }}>Records</p>
        </div>
        <div>
          <p className="stat-number text-lg">{file.website_count}</p>
          <p className="text-[10px] uppercase" style={{ color: "var(--text-3)" }}>Websites</p>
        </div>
        <div>
          <p className="stat-number text-lg">{file.email_count}</p>
          <p className="text-[10px] uppercase" style={{ color: "var(--text-3)" }}>Emails</p>
        </div>
      </div>

      <p className="text-xs mb-3" style={{ color: "var(--text-3)" }}>
        {file.file_type.toUpperCase()} · {file.file_size ? `${(file.file_size / 1024).toFixed(1)} KB` : "—"} · {fmt(file.created_at)}
      </p>

      {expanded && (
        <div className="text-xs mb-3 pt-3 space-y-1" style={{ borderTop: "1px solid var(--border)", color: "var(--text-2)" }}>
          <p>Original file: <span className="mono">{file.original_filename}</span></p>
          {file.request_name && <p>Request: {file.request_name}</p>}
          {file.expires_at && <p>Expires: {fmt(file.expires_at)}</p>}
          {file.last_downloaded_at && <p>Last downloaded: {fmt(file.last_downloaded_at)}</p>}
        </div>
      )}

      <div className="flex flex-wrap gap-1.5">
        <button onClick={download} disabled={downloading} className="btn-primary text-xs" style={{ padding: "6px 10px" }}>
          {downloading ? "…" : "⬇ Download"}
        </button>
        <button onClick={() => setExpanded(e => !e)} className="btn-ghost text-xs" style={{ padding: "6px 10px" }}>
          {expanded ? "Hide details" : "View details"}
        </button>
        <button onClick={() => onNavigate?.("get-leads", file.source_type === "business" ? "business" : "people")}
          className="btn-ghost text-xs" style={{ padding: "6px 10px" }}>
          Open request
        </button>
        <button onClick={() => onNavigate?.("support")} className="btn-ghost text-xs" style={{ padding: "6px 10px" }}>
          Contact support
        </button>
      </div>
    </div>
  );
}

export default function MyLeads({ onNavigate, theme }) {
  const [stats, setStats]   = useState(null);
  const [charts, setCharts] = useState(null);
  const [files, setFiles]   = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError]     = useState("");
  const [filters, setFilters] = useState({
    source_type: "", file_category: "", state: "", file_type: "", downloaded: "", date_from: "", date_to: "",
  });

  useEffect(() => {
    Promise.all([api.leadFileStats(), api.leadFileCharts()])
      .then(([s, c]) => { setStats(s); setCharts(c); })
      .catch(() => {});
  }, []);

  const loadFiles = async () => {
    setLoading(true); setError("");
    try { setFiles(await api.listLeadFiles(filters)); }
    catch (e) { setError(e.message); }
    finally { setLoading(false); }
  };

  useEffect(() => { loadFiles(); }, [filters]);

  const setFilter = (key, value) => setFilters(f => ({ ...f, [key]: value }));

  return (
    <div className="space-y-5 animate-fade-in">
      {stats && (
        <div className="grid grid-cols-2 xl:grid-cols-4 gap-3">
          <StatCard label="Total Leads" value={stats.total_leads} accent delay={0} />
          <StatCard label="Total Files" value={stats.total_files} delay={1} />
          <StatCard label="Business Leads" value={stats.business_leads} delay={2} />
          <StatCard label="People Leads" value={stats.people_leads} delay={3} />
          <StatCard label="Businesses With Website" value={stats.businesses_with_website} delay={0} />
          <StatCard label="Businesses Without Website" value={stats.businesses_without_website} delay={1} />
          <StatCard label="Emails Found" value={stats.emails_found} delay={2} />
          <StatCard label="Files This Month" value={stats.files_generated_this_month} delay={3} />
        </div>
      )}

      {charts && (
        <div className="grid grid-cols-1 lg:grid-cols-4 gap-4">
          <div className="card p-5 flex flex-col items-center">
            <p className="label self-start w-full">Business vs People</p>
            <DonutChart key={theme} segments={charts.business_vs_people.map((s, i) => ({
              label: s.label, value: s.value, color: i === 0 ? "var(--accent)" : "var(--info)",
            }))} />
          </div>
          <div className="card p-5 flex flex-col items-center">
            <p className="label self-start w-full">Website Coverage</p>
            <DonutChart key={theme} segments={charts.with_vs_without_website.map((s, i) => ({
              label: s.label, value: s.value, color: i === 0 ? "var(--accent)" : "var(--text-3)",
            }))} />
          </div>
          <div className="card p-5">
            <p className="label mb-3">Leads by State</p>
            <BarListChart key={theme} items={charts.leads_by_state} />
          </div>
          <div className="card p-5">
            <p className="label mb-3">Leads by Industry</p>
            <BarListChart key={theme} items={charts.leads_by_industry} />
          </div>
        </div>
      )}

      {/* Filters */}
      <div className="card p-4">
        <div className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-7 gap-3">
          <div>
            <label className="label" style={{ marginBottom: 2 }}>Source</label>
            <select value={filters.source_type} onChange={e => setFilter("source_type", e.target.value)}
              className="input text-xs" style={{ padding: "6px 8px" }}>
              <option value="">All</option>
              <option value="business">Business Leads</option>
              <option value="people">People Leads</option>
            </select>
          </div>
          <div>
            <label className="label" style={{ marginBottom: 2 }}>Category</label>
            <select value={filters.file_category} onChange={e => setFilter("file_category", e.target.value)}
              className="input text-xs" style={{ padding: "6px 8px" }}>
              <option value="">All</option>
              <option value="business_with_website">With Website</option>
              <option value="business_no_website">Without Website</option>
              <option value="business_with_website_email">With Email</option>
              <option value="business_with_website_no_email">Without Email</option>
              <option value="people_leads">People Leads</option>
            </select>
          </div>
          <div>
            <label className="label" style={{ marginBottom: 2 }}>State</label>
            <input value={filters.state} onChange={e => setFilter("state", e.target.value.toUpperCase().slice(0, 2))}
              placeholder="FL" className="input text-xs mono" style={{ padding: "6px 8px" }} />
          </div>
          <div>
            <label className="label" style={{ marginBottom: 2 }}>Format</label>
            <select value={filters.file_type} onChange={e => setFilter("file_type", e.target.value)}
              className="input text-xs" style={{ padding: "6px 8px" }}>
              <option value="">All</option>
              <option value="csv">CSV</option>
              <option value="xlsx">Excel</option>
            </select>
          </div>
          <div>
            <label className="label" style={{ marginBottom: 2 }}>Downloaded</label>
            <select value={filters.downloaded} onChange={e => setFilter("downloaded", e.target.value)}
              className="input text-xs" style={{ padding: "6px 8px" }}>
              <option value="">All</option>
              <option value="true">Downloaded</option>
              <option value="false">Not downloaded</option>
            </select>
          </div>
          <div>
            <label className="label" style={{ marginBottom: 2 }}>From</label>
            <input type="date" value={filters.date_from} onChange={e => setFilter("date_from", e.target.value)}
              className="input text-xs" style={{ padding: "6px 8px" }} />
          </div>
          <div>
            <label className="label" style={{ marginBottom: 2 }}>To</label>
            <input type="date" value={filters.date_to} onChange={e => setFilter("date_to", e.target.value)}
              className="input text-xs" style={{ padding: "6px 8px" }} />
          </div>
        </div>
      </div>

      {/* File library */}
      {loading ? (
        <div className="card p-10 text-center animate-soft-pulse">
          <p className="text-sm" style={{ color: "var(--text-3)" }}>Loading files…</p>
        </div>
      ) : error ? (
        <div className="alert-danger">{error}</div>
      ) : files.length === 0 ? (
        <div className="card p-12 text-center animate-fade-in">
          <p className="text-3xl mb-3">▤</p>
          <p className="font-medium" style={{ color: "var(--text-2)" }}>No files yet</p>
          <p className="text-sm mt-1" style={{ color: "var(--text-3)" }}>
            Completed Business and People Leads files will appear here.
          </p>
        </div>
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 gap-4">
          {files.map(f => (
            <FileCard key={f.id} file={f} onNavigate={onNavigate} onRenamed={loadFiles} />
          ))}
        </div>
      )}
    </div>
  );
}
