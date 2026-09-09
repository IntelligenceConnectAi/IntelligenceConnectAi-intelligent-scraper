import { useState } from "react";
import { api } from "../../lib/api";
import { downloadBase64File } from "../../lib/downloadBase64Zip";
import StatCard from "../StatCard";

const MONTHS = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"];
const CHANNELS = [
  { key: "dialer", label: "📞 Dialer / AI Outbound" },
  { key: "sms", label: "💬 SMS" },
  { key: "email", label: "📧 Email" },
];

function ChannelCheckboxes({ selected, onToggle }) {
  return (
    <div className="flex flex-wrap gap-3">
      {CHANNELS.map((c) => (
        <label key={c.key} className="flex items-center gap-1.5 text-sm" style={{ color: "var(--text-2)" }}>
          <input type="checkbox" checked={selected.includes(c.key)} onChange={() => onToggle(c.key)} />
          {c.label}
        </label>
      ))}
    </div>
  );
}

export default function PeopleLeadsOrganizer({ onProcessed }) {
  const [files, setFiles] = useState([]);
  const [structured, setStructured] = useState(false);
  const [month, setMonth] = useState(MONTHS[0]);
  const [year, setYear] = useState("2026");
  const [state, setState] = useState("");
  const [dealType, setDealType] = useState("");
  const [freeformName, setFreeformName] = useState("");
  const [marketingChannels, setMarketingChannels] = useState([]);
  const [propertiesChannels, setPropertiesChannels] = useState([]);
  const [doSplit, setDoSplit] = useState(false);
  const [splitCount, setSplitCount] = useState(5);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState(null);

  const toggleMarketing = (key) =>
    setMarketingChannels((prev) => (prev.includes(key) ? prev.filter((k) => k !== key) : [...prev, key]));
  const toggleProperties = (key) =>
    setPropertiesChannels((prev) => (prev.includes(key) ? prev.filter((k) => k !== key) : [...prev, key]));

  const addFiles = (fileList) => {
    const next = Array.from(fileList || []);
    setFiles((prev) => [...prev, ...next]);
  };
  const removeFile = (name) => setFiles((prev) => prev.filter((f) => f.name !== name));

  const detailsOk = structured
    ? state.trim() && year.trim() && dealType.trim()
    : freeformName.trim();
  const channelsOk = marketingChannels.length > 0 || propertiesChannels.length > 0;
  const ready = files.length > 0 && detailsOk && channelsOk;

  const submit = async (e) => {
    e.preventDefault();
    if (!ready) return;
    setLoading(true);
    setError("");
    setResult(null);
    try {
      const fd = new FormData();
      files.forEach((f) => fd.append("files", f));
      fd.append("name_mode", structured ? "structured" : "freeform");
      fd.append("freeform_name", freeformName);
      fd.append("month", month);
      fd.append("year", year);
      fd.append("state", state);
      fd.append("deal_type", dealType);
      marketingChannels.forEach((c) => fd.append("marketing_channels", c));
      propertiesChannels.forEach((c) => fd.append("properties_channels", c));
      fd.append("split_count", doSplit ? String(splitCount) : "1");

      const res = await api.processPeopleLeadsCampaign(fd);
      setResult(res);
      onProcessed?.({
        campaignName: res.campaign_name,
        origPhoneCount: res.orig_phone_count,
        origEmailCount: res.orig_email_count,
        marketingCounts: res.marketing_counts,
        propertiesCounts: res.properties_counts,
        processedAt: Date.now(),
      });
    } catch (e2) {
      setError(e2.message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="space-y-5 animate-fade-in">
      <div className="dashboard-panel dashboard-panel--hero">
        <p className="page-title">People Leads Organizer</p>
        <p className="page-subtitle">Upload, clean, and split your people-lead lists into campaign-ready files.</p>
      </div>

      <form onSubmit={submit} className="space-y-5">
        <div className="card p-6">
          <p className="font-semibold mb-1" style={{ color: "var(--text)" }}>1. Upload Lead List</p>
          <p className="text-xs mb-4" style={{ color: "var(--text-3)" }}>Excel (.xlsx) files only — you can select more than one.</p>
          <input
            type="file"
            multiple
            accept=".xlsx"
            className="input"
            onChange={(e) => { addFiles(e.target.files); e.target.value = ""; }}
          />
          {files.length > 0 && (
            <div className="flex flex-wrap gap-1.5 mt-3">
              {files.map((f) => (
                <span key={f.name} className="badge badge-accent flex items-center gap-1 shrink-0">
                  {f.name}
                  <button type="button" onClick={() => removeFile(f.name)} className="hover:opacity-70 transition leading-none">×</button>
                </span>
              ))}
            </div>
          )}
        </div>

        <div className="card p-6">
          <p className="font-semibold mb-4" style={{ color: "var(--text)" }}>2. Campaign Name</p>
          <div className="flex gap-2 mb-4">
            <button type="button" className={!structured ? "btn-primary" : "btn-ghost"} style={{ fontSize: "0.8125rem" }} onClick={() => setStructured(false)}>Custom name</button>
            <button type="button" className={structured ? "btn-primary" : "btn-ghost"} style={{ fontSize: "0.8125rem" }} onClick={() => setStructured(true)}>Structured name</button>
          </div>
          {structured ? (
            <div className="grid gap-4 sm:grid-cols-4">
              <div>
                <label className="label">Month</label>
                <select value={month} onChange={(e) => setMonth(e.target.value)} className="input">
                  {MONTHS.map((m) => <option key={m} value={m}>{m}</option>)}
                </select>
              </div>
              <div>
                <label className="label">Year</label>
                <input value={year} onChange={(e) => setYear(e.target.value)} className="input mono" />
              </div>
              <div>
                <label className="label">State</label>
                <input value={state} onChange={(e) => setState(e.target.value.toUpperCase().slice(0, 2))} placeholder="FL" maxLength={2} className="input mono" />
              </div>
              <div>
                <label className="label">Type of Deal</label>
                <input value={dealType} onChange={(e) => setDealType(e.target.value)} placeholder="e.g. LUXURY LAND" className="input" />
              </div>
            </div>
          ) : (
            <div>
              <label className="label">Output File Name</label>
              <input value={freeformName} onChange={(e) => setFreeformName(e.target.value)} placeholder="e.g. Miami Absentee Owners" className="input" />
            </div>
          )}
        </div>

        <div className="card p-6">
          <p className="font-semibold mb-1" style={{ color: "var(--text)" }}>3. Marketing Process</p>
          <p className="text-xs mb-3" style={{ color: "var(--text-3)" }}>Channels to generate from the full uploaded list.</p>
          <ChannelCheckboxes selected={marketingChannels} onToggle={toggleMarketing} />
        </div>

        <div className="card p-6">
          <p className="font-semibold mb-1" style={{ color: "var(--text)" }}>4. Properties / Seller Leads <span className="badge badge-muted ml-1">Optional</span></p>
          <p className="text-xs mb-3" style={{ color: "var(--text-3)" }}>Same channels, filtered by MLS status first (blank status becomes "Off Market").</p>
          <ChannelCheckboxes selected={propertiesChannels} onToggle={toggleProperties} />
        </div>

        <div className="card p-6">
          <p className="font-semibold mb-3" style={{ color: "var(--text)" }}>5. Monthly Split <span className="badge badge-muted ml-1">Optional</span></p>
          <label className="flex items-center gap-1.5 text-sm mb-3" style={{ color: "var(--text-2)" }}>
            <input type="checkbox" checked={doSplit} onChange={(e) => setDoSplit(e.target.checked)} />
            Split output into multiple files
          </label>
          {doSplit && (
            <div style={{ maxWidth: 200 }}>
              <label className="label">How many files?</label>
              <input type="number" min="2" max="50" value={splitCount} onChange={(e) => setSplitCount(e.target.value)} className="input mono" />
            </div>
          )}
        </div>

        {error && <p className="text-xs" style={{ color: "var(--danger)" }}>{error}</p>}

        <button type="submit" disabled={!ready || loading} className="btn-primary w-full">
          {loading
            ? <span className="flex items-center justify-center gap-2">
                <span className="h-3.5 w-3.5 rounded-full border-2 border-black/30 border-t-black animate-spin" />
                Processing…
              </span>
            : "⚙️ Process Files"}
        </button>
      </form>

      {result && (
        <div className="space-y-4">
          <p className="section-title">Results</p>
          <div className="dashboard-grid">
            <div className="span-4 span-xl-4"><StatCard label="Total Rows Merged" value={result.total_rows} /></div>
            <div className="span-4 span-xl-4"><StatCard label="Original Phone Numbers" value={result.orig_phone_count} /></div>
            <div className="span-4 span-xl-4"><StatCard label="Original Emails" value={result.orig_email_count} /></div>
          </div>

          <div className="dashboard-panel">
            <p className="dashboard-panel-title">Downloads</p>
            <div className="space-y-2">
              {result.downloads.map((d) => (
                <button
                  key={d.filename}
                  type="button"
                  className="btn-primary w-full"
                  onClick={() => downloadBase64File(d.content_base64, d.filename)}
                >
                  ⬇️ Download {d.label}
                </button>
              ))}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
