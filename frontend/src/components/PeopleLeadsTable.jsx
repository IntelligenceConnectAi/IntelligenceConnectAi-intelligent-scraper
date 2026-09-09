// Parallel to RequestsTable.jsx but for People Leads — different columns/fields,
// and download requires a detail fetch (the list endpoint doesn't carry download_url,
// only GET /people-leads/requests/{id} does, since it's a signed URL generated per-call).
import { useState } from "react";
import { api } from "../lib/api";
import StatusIndicator from "./StatusIndicator";

const LEAD_TYPE_LABELS = {
  property_owners: "Property Owners",
  absentee_owners: "Absentee Owners",
  vacant_property_owners: "Vacant Property Owners",
  high_equity_homeowners: "High-Equity Homeowners",
  landowners: "Landowners",
  other: "Other",
};

function fmt(iso) {
  if (!iso) return "—";
  return new Date(iso).toLocaleString("en-US", {
    month: "short", day: "numeric",
    hour: "2-digit", minute: "2-digit",
  });
}

export default function PeopleLeadsTable({ requests }) {
  const [dl, setDl] = useState({});

  const download = async (id) => {
    setDl(p => ({ ...p, [id]: true }));
    try {
      const detail = await api.getPeopleLeadRequest(id);
      if (detail.download_url) window.open(detail.download_url, "_blank");
      else alert("No file available for this request yet.");
    } catch (e) {
      alert(`Download failed: ${e.message}`);
    } finally {
      setDl(p => ({ ...p, [id]: false }));
    }
  };

  if (requests.length === 0) return (
    <div className="card p-12 text-center animate-fade-in">
      <p className="text-3xl mb-3">◇</p>
      <p className="font-medium" style={{ color: "var(--text-2)" }}>No requests yet</p>
      <p className="text-sm mt-1" style={{ color: "var(--text-3)" }}>Completed People Leads requests will appear here.</p>
    </div>
  );

  return (
    <div className="card overflow-hidden animate-fade-in">
      <div className="flex items-center justify-between px-5 py-3.5"
        style={{ borderBottom: "1px solid var(--border)" }}>
        <p className="text-sm font-semibold" style={{ color: "var(--text)" }}>Requests</p>
        <span className="badge badge-muted mono">{requests.length} {requests.length === 1 ? "request" : "requests"}</span>
      </div>

      {/* Desktop table */}
      <div className="hidden md:block overflow-x-auto">
        <table className="w-full">
          <thead>
            <tr style={{ borderBottom: "1px solid var(--border)" }}>
              {["Request Name","Lead Type","Location","Status","Requested","Delivered","Created",""].map(h => (
                <th key={h} className="px-4 py-3 text-left text-xs font-medium tracking-wider uppercase" style={{ color: "var(--text-3)" }}>
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {requests.map((r, i) => (
              <tr key={r.id} style={{ borderTop: i > 0 ? "1px solid var(--border)" : "none" }}
                className="transition-colors" onMouseEnter={e => e.currentTarget.style.background = "var(--row-hover)"}
                onMouseLeave={e => e.currentTarget.style.background = ""}>
                <td className="px-4 py-3 font-medium text-sm" style={{ color: "var(--text)" }}>{r.request_name}</td>
                <td className="px-4 py-3 text-xs" style={{ color: "var(--text-2)" }}>{LEAD_TYPE_LABELS[r.lead_type] || r.lead_type}</td>
                <td className="px-4 py-3 text-xs" style={{ color: "var(--text-3)" }}>{[r.city, r.state].filter(Boolean).join(", ")}</td>
                <td className="px-4 py-3"><StatusIndicator status={r.status} variant="people" /></td>
                <td className="px-4 py-3 mono text-sm text-right" style={{ color: "var(--text-2)" }}>{r.requested_quantity}</td>
                <td className="px-4 py-3 mono text-sm font-semibold text-right" style={{ color: "var(--text)" }}>{r.delivered_quantity}</td>
                <td className="px-4 py-3 text-xs" style={{ color: "var(--text-3)" }}>{fmt(r.created_at)}</td>
                <td className="px-4 py-3">
                  {r.status === "Completed" ? (
                    <button onClick={() => download(r.id)} disabled={dl[r.id]}
                      className="badge badge-accent cursor-pointer hover:opacity-80 transition disabled:opacity-40">
                      {dl[r.id] ? "…" : "⬇ Download"}
                    </button>
                  ) : <span className="text-xs" style={{ color: "var(--text-3)" }}>—</span>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Mobile cards */}
      <div className="md:hidden divide-y" style={{ borderColor: "var(--border)" }}>
        {requests.map(r => (
          <div key={r.id} className="p-4 space-y-3">
            <div className="flex items-start justify-between gap-2">
              <div>
                <p className="font-semibold text-sm" style={{ color: "var(--text)" }}>{r.request_name}</p>
                <p className="text-xs mt-0.5" style={{ color: "var(--text-3)" }}>
                  {LEAD_TYPE_LABELS[r.lead_type] || r.lead_type} · {[r.city, r.state].filter(Boolean).join(", ")}
                </p>
              </div>
              <StatusIndicator status={r.status} variant="people" />
            </div>
            <div className="flex gap-4 text-xs mono" style={{ color: "var(--text-2)" }}>
              <span><span style={{ color: "var(--text)" }}>{r.delivered_quantity}</span> / {r.requested_quantity}</span>
              <span style={{ color: "var(--text-3)" }}>{fmt(r.created_at)}</span>
            </div>
            {r.status === "Completed" && (
              <button onClick={() => download(r.id)} disabled={dl[r.id]} className="badge badge-accent cursor-pointer">
                {dl[r.id] ? "…" : "⬇ Download"}
              </button>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
