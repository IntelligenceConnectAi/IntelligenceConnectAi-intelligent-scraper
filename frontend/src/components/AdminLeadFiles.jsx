import { useEffect, useState } from "react";
import { api } from "../lib/api";

function fmt(iso) {
  if (!iso) return "—";
  return new Date(iso).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
}

export default function AdminLeadFiles() {
  const [files, setFiles] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [downloading, setDownloading] = useState(null);

  useEffect(() => {
    api.adminListLeadFiles().then(setFiles).catch(e => setError(e.message)).finally(() => setLoading(false));
  }, []);

  const download = async (id) => {
    setDownloading(id);
    try { const r = await api.adminDownloadLeadFile(id); window.open(r.url, "_blank"); }
    catch (e) { alert(`Download failed: ${e.message}`); }
    finally { setDownloading(null); }
  };

  if (loading) return (
    <div className="card p-10 text-center animate-soft-pulse">
      <p className="text-sm" style={{ color: "var(--text-3)" }}>Loading lead files…</p>
    </div>
  );
  if (error) return <p className="text-sm" style={{ color: "var(--danger)" }}>{error}</p>;

  return (
    <div className="card overflow-hidden animate-fade-in">
      <div className="px-5 py-3.5 flex items-center justify-between" style={{ borderBottom: "1px solid var(--border)" }}>
        <p className="text-sm font-semibold" style={{ color: "var(--text)" }}>Lead Files</p>
        <span className="badge badge-muted mono">{files.length}</span>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full">
          <thead>
            <tr style={{ borderBottom: "1px solid var(--border)" }}>
              {["File", "Client", "Source", "Records", "Created", ""].map(h => (
                <th key={h} className="px-4 py-3 text-left text-xs font-medium tracking-wider uppercase" style={{ color: "var(--text-3)" }}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {files.map((f, i) => (
              <tr key={f.id} style={{ borderTop: i > 0 ? "1px solid var(--border)" : "none" }}>
                <td className="px-4 py-3 text-sm font-medium" style={{ color: "var(--text)" }}>{f.display_name}</td>
                <td className="px-4 py-3 text-xs" style={{ color: "var(--text-2)" }}>{f.organization_name} · {f.user_email}</td>
                <td className="px-4 py-3"><span className="badge badge-muted">{f.source_type === "business" ? "Business" : "People"}</span></td>
                <td className="px-4 py-3 text-sm mono text-right" style={{ color: "var(--text)" }}>{f.record_count}</td>
                <td className="px-4 py-3 text-xs" style={{ color: "var(--text-3)" }}>{fmt(f.created_at)}</td>
                <td className="px-4 py-3">
                  <button onClick={() => download(f.id)} disabled={downloading === f.id}
                    className="badge badge-accent cursor-pointer hover:opacity-80 transition disabled:opacity-40">
                    {downloading === f.id ? "…" : "⬇"}
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
