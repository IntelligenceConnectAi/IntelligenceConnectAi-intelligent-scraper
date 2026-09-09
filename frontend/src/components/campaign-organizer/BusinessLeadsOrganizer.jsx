import { useState } from "react";
import { api } from "../../lib/api";
import { downloadBase64File } from "../../lib/downloadBase64Zip";
import StatCard from "../StatCard";

const MONTHS = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"];

export default function BusinessLeadsOrganizer() {
  const [files, setFiles] = useState([]);
  const [structured, setStructured] = useState(false);
  const [month, setMonth] = useState(MONTHS[0]);
  const [year, setYear] = useState("2026");
  const [state, setState] = useState("");
  const [dealType, setDealType] = useState("");
  const [freeformName, setFreeformName] = useState("");
  const [doSplit, setDoSplit] = useState(false);
  const [splitCount, setSplitCount] = useState(5);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState(null);

  const addFiles = (fileList) => setFiles((prev) => [...prev, ...Array.from(fileList || [])]);
  const removeFile = (name) => setFiles((prev) => prev.filter((f) => f.name !== name));

  const detailsOk = structured ? state.trim() && year.trim() && dealType.trim() : freeformName.trim();
  const ready = files.length > 0 && detailsOk;

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
      fd.append("split_count", doSplit ? String(splitCount) : "1");

      const res = await api.processBusinessLeadsCampaign(fd);
      setResult(res);
    } catch (e2) {
      setError(e2.message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="space-y-5 animate-fade-in">
      <div className="dashboard-panel dashboard-panel--hero">
        <p className="page-title">Business Leads Organizer</p>
        <p className="page-subtitle">Merge your business lead files and export in one click.</p>
      </div>

      <form onSubmit={submit} className="space-y-5">
        <div className="card p-6">
          <p className="font-semibold mb-1" style={{ color: "var(--text)" }}>1. Upload Lead List</p>
          <p className="text-xs mb-4" style={{ color: "var(--text-3)" }}>Excel (.xlsx) or CSV files — you can select more than one.</p>
          <input
            type="file"
            multiple
            accept=".xlsx,.csv"
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
              <input value={freeformName} onChange={(e) => setFreeformName(e.target.value)} placeholder="e.g. Tampa Commercial List" className="input" />
            </div>
          )}
        </div>

        <div className="card p-6">
          <p className="font-semibold mb-3" style={{ color: "var(--text)" }}>3. Monthly Split <span className="badge badge-muted ml-1">Optional</span></p>
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
          </div>
          <div className="dashboard-panel">
            <p className="dashboard-panel-title">Downloads</p>
            <button type="button" className="btn-primary w-full" onClick={() => downloadBase64File(result.download.content_base64, result.download.filename)}>
              ⬇️ Download {result.download.label}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
