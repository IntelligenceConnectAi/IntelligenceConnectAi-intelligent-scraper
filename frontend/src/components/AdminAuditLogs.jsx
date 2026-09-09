import { useEffect, useState } from "react";
import { api } from "../lib/api";

function fmt(iso) {
  return new Date(iso).toLocaleString("en-US", { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

export default function AdminAuditLogs() {
  const [logs, setLogs] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [actionFilter, setActionFilter] = useState("");
  const [expanded, setExpanded] = useState(null);

  const load = async (filters) => {
    setLoading(true); setError("");
    try { setLogs(await api.adminListAuditLogs(filters)); }
    catch (e) { setError(e.message); }
    finally { setLoading(false); }
  };

  useEffect(() => { load({}); }, []);

  const applyFilter = (e) => {
    e.preventDefault();
    load({ action: actionFilter || undefined });
  };

  return (
    <div className="space-y-4 animate-fade-in">
      <form onSubmit={applyFilter} className="card p-4 flex gap-2 items-end">
        <div className="flex-1">
          <label className="label" style={{ marginBottom: 2 }}>Filter by action</label>
          <input value={actionFilter} onChange={e => setActionFilter(e.target.value)}
            placeholder="e.g. admin_user_disabled" className="input mono text-xs" />
        </div>
        <button type="submit" className="btn-ghost text-sm">Filter</button>
      </form>

      {loading ? (
        <div className="card p-10 text-center animate-soft-pulse">
          <p className="text-sm" style={{ color: "var(--text-3)" }}>Loading audit logs…</p>
        </div>
      ) : error ? (
        <p className="text-sm" style={{ color: "var(--danger)" }}>{error}</p>
      ) : (
        <div className="card overflow-hidden">
          <div className="px-5 py-3.5 flex items-center justify-between" style={{ borderBottom: "1px solid var(--border)" }}>
            <p className="text-sm font-semibold" style={{ color: "var(--text)" }}>Audit Logs</p>
            <span className="badge badge-muted mono">{logs.length}</span>
          </div>
          <div className="divide-y" style={{ borderColor: "var(--border)" }}>
            {logs.map(l => (
              <div key={l.id}>
                <button onClick={() => setExpanded(e => e === l.id ? null : l.id)}
                  className="w-full flex items-center justify-between px-5 py-3 text-left transition"
                  onMouseEnter={e => e.currentTarget.style.background = "var(--row-hover)"}
                  onMouseLeave={e => e.currentTarget.style.background = "transparent"}>
                  <div>
                    <p className="text-sm font-medium mono" style={{ color: "var(--text)" }}>{l.action}</p>
                    <p className="text-xs" style={{ color: "var(--text-3)" }}>
                      {l.actor_email || "system"} · {l.resource_type || "—"} · {fmt(l.created_at)}
                    </p>
                  </div>
                  <span className="text-xs" style={{ color: "var(--text-3)" }}>{expanded === l.id ? "▲" : "▼"}</span>
                </button>
                {expanded === l.id && (
                  <div className="px-5 pb-4 text-xs mono" style={{ color: "var(--text-2)" }}>
                    <p>Resource ID: {l.resource_id || "—"}</p>
                    <p>Actor role: {l.actor_role || "—"}</p>
                    <p>IP: {l.ip_address || "—"}</p>
                    {l.previous_value_json && <pre className="mt-1 p-2 rounded overflow-x-auto" style={{ background: "var(--bg-secondary)" }}>{JSON.stringify(l.previous_value_json, null, 2)}</pre>}
                    {l.new_value_json && <pre className="mt-1 p-2 rounded overflow-x-auto" style={{ background: "var(--bg-secondary)" }}>{JSON.stringify(l.new_value_json, null, 2)}</pre>}
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
