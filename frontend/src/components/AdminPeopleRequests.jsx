import { useEffect, useState } from "react";
import { api } from "../lib/api";
import { CONSUMER_STACK_META, BUSINESS_STACK_META, STACK_ORDER } from "../lib/filterStackMeta";
import { CONSUMER_AUDIENCE, BUSINESS_AUDIENCE } from "../lib/audienceProfiles";

function fmt(iso) {
  if (!iso) return "—";
  return new Date(iso).toLocaleString("en-US", { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

function TargetingSummary({ targeting }) {
  if (!targeting) return null;
  const isConsumer = targeting.target_audience === "Consumers";
  const isBusiness = targeting.target_audience === "Businesses";
  const stackMeta = isConsumer ? CONSUMER_STACK_META : isBusiness ? BUSINESS_STACK_META : null;
  const stackKeys = targeting.filter_stacks || [];
  const nicheId = targeting.business_type?.id;
  const audienceSource = isConsumer ? CONSUMER_AUDIENCE : isBusiness ? BUSINESS_AUDIENCE : null;
  const audienceProfile = nicheId && audienceSource ? audienceSource[nicheId] : null;

  const field = (label, value) => (
    <div>
      <p className="text-xs uppercase tracking-wide" style={{ color: "var(--text-3)", letterSpacing: "0.04em" }}>{label}</p>
      <p className="text-sm mt-0.5" style={{ color: "var(--text)" }}>{value || "—"}</p>
    </div>
  );

  return (
    <div className="card p-5">
      <p className="text-sm font-semibold mb-3" style={{ color: "var(--text)" }}>Business Targeting</p>
      <div className="grid gap-4 sm:grid-cols-2">
        {field("Business Name", targeting.business_name)}
        {field("Business Type", targeting.business_type && (
          `${targeting.business_type.name}${targeting.business_type.is_other ? " (Other — client-typed)" : ""}` +
          (targeting.business_type.category ? ` · ${targeting.business_type.category}` : "")
        ))}
        {field("Who They Want to Target", targeting.target_audience === "Consumers" ? "People / Households"
          : targeting.target_audience === "Businesses" ? "Businesses" : null)}
      </div>

      {stackKeys.length > 0 && (
        <div className="mt-4 pt-4" style={{ borderTop: "1px solid var(--border)" }}>
          <p className="text-xs uppercase tracking-wide mb-1.5" style={{ color: "var(--text-3)", letterSpacing: "0.04em" }}>
            Filter Stack(s) Selected ({stackKeys.length})
          </p>
          {audienceProfile?.ideal && (
            <p className="text-xs mb-2.5" style={{ color: "var(--text-2)" }}>
              <span style={{ color: "var(--text-3)" }}>Ideal customer: </span>{audienceProfile.ideal}
            </p>
          )}
          <div className="grid gap-2.5 sm:grid-cols-3">
            {STACK_ORDER.filter(k => stackKeys.includes(k)).map(k => {
              const meta = stackMeta?.[k];
              const criteria = audienceProfile?.[k];
              return (
                <div key={k} className="rounded-lg p-3" style={{ background: "var(--surface-soft)", border: "1px solid var(--border)" }}>
                  <p className="text-xs font-semibold" style={{ color: "var(--people-primary)" }}>
                    {meta?.tag || k}{meta?.rec && " ★"}
                  </p>
                  <p className="text-sm font-semibold mt-0.5" style={{ color: "var(--text)" }}>{meta?.name || k}</p>
                  {meta?.sub && <p className="text-xs mt-0.5" style={{ color: "var(--text-3)" }}>{meta.sub}</p>}
                  <p className="text-xs mt-2 whitespace-pre-line" style={{ color: "var(--text-2)" }}>
                    {criteria || "No preset criteria on file (custom/other business type)."}
                  </p>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {targeting.cities?.length > 0 && (
        <div className="mt-4">
          <p className="text-xs uppercase tracking-wide mb-1.5" style={{ color: "var(--text-3)", letterSpacing: "0.04em" }}>
            Cities ({targeting.cities.length})
          </p>
          <div className="flex flex-wrap gap-1.5">
            {targeting.cities.map(c => <span key={c} className="badge badge-people">{c}</span>)}
          </div>
        </div>
      )}

      <div className="mt-4 pt-4 flex flex-wrap gap-6" style={{ borderTop: "1px solid var(--border)" }}>
        {field("DNC Numbers Included", targeting.dnc_included ? "Yes — keep all numbers" : "No — remove Public DNC numbers")}
        {targeting.dnc_included && field("Client Accepted DNC Terms", targeting.dnc_terms_accepted ? "Yes" : "No")}
      </div>
    </div>
  );
}

function RequestDetail({ requestId, onBack, onChanged, hasPermission, isSuperAdmin }) {
  const [req, setReq] = useState(null);
  const [error, setError] = useState("");
  const [admins, setAdmins] = useState([]);
  const [busy, setBusy] = useState(false);
  const [notes, setNotes] = useState("");
  const [revisionMsg, setRevisionMsg] = useState("");
  const [file, setFile] = useState(null);
  const [deliverQty, setDeliverQty] = useState("");

  const canPeopleLeads = isSuperAdmin || hasPermission("people_leads_admin");
  const canSupport = isSuperAdmin || hasPermission("support_admin");

  const load = () => api.adminGetPeopleLeadRequest(requestId).then(setReq).catch(e => setError(e.message));
  useEffect(() => { load(); }, [requestId]);
  useEffect(() => { api.adminListUsers({ permission: "people_leads_admin" }).then(setAdmins).catch(() => {}); }, []);

  const assign = async (adminId) => {
    setBusy(true);
    try { await api.adminAssignPeopleLeadRequest(requestId, adminId); await load(); onChanged(); }
    catch (e) { alert(`Assign failed: ${e.message}`); }
    finally { setBusy(false); }
  };

  const upload = async (e) => {
    e.preventDefault();
    if (!file) return;
    setBusy(true);
    try {
      const fd = new FormData();
      fd.append("file", file);
      await api.adminUploadPeopleLeadFile(requestId, fd);
      setFile(null);
      await load(); onChanged();
    } catch (e2) {
      alert(`Upload failed: ${e2.message}`);
    } finally {
      setBusy(false);
    }
  };

  const review = async (decision) => {
    setBusy(true);
    try { await api.adminReviewPeopleLeadRequest(requestId, decision, notes); setNotes(""); await load(); onChanged(); }
    catch (e) { alert(`Review failed: ${e.message}`); }
    finally { setBusy(false); }
  };

  const deliver = async () => {
    setBusy(true);
    try {
      await api.adminDeliverPeopleLeadRequest(requestId, deliverQty ? parseInt(deliverQty, 10) : undefined);
      await load(); onChanged();
    } catch (e) {
      alert(`Deliver failed: ${e.message}`);
    } finally {
      setBusy(false);
    }
  };

  const requestRevision = async (e) => {
    e.preventDefault();
    if (!revisionMsg.trim()) return;
    setBusy(true);
    try { await api.adminRequestPeopleLeadRevision(requestId, revisionMsg.trim()); setRevisionMsg(""); await load(); onChanged(); }
    catch (e2) { alert(`Request revision failed: ${e2.message}`); }
    finally { setBusy(false); }
  };

  if (error) return <p className="text-sm" style={{ color: "var(--danger)" }}>{error}</p>;
  if (!req) return <p className="text-sm animate-soft-pulse" style={{ color: "var(--text-3)" }}>Loading…</p>;

  const isTerminal = req.internal_status === "delivered" || req.internal_status === "cancelled";
  const latestFile = req.files[0];

  return (
    <div className="space-y-5 animate-fade-in">
      <button onClick={onBack} className="btn-ghost text-xs">← Back to list</button>

      <div className="card p-5">
        <div className="flex items-start justify-between gap-3 mb-3">
          <div>
            <p className="font-semibold" style={{ color: "var(--text)" }}>{req.request_name}</p>
            <p className="text-xs mt-0.5" style={{ color: "var(--text-3)" }}>
              {req.lead_type} · {[req.city, req.county, req.state].filter(Boolean).join(", ")} · {req.requested_quantity} requested
            </p>
          </div>
          <div className="flex gap-1.5">
            <span className="badge badge-accent">{req.client_status}</span>
            <span className="badge badge-muted mono">{req.internal_status}</span>
          </div>
        </div>
        {req.client_instructions && (
          <p className="text-xs p-2 rounded mb-2" style={{ background: "var(--bg-secondary)", color: "var(--text-2)" }}>
            {req.client_instructions}
          </p>
        )}
      </div>

      <TargetingSummary targeting={req.targeting_filters_json?.targeting} />

      {!isTerminal && canPeopleLeads && req.internal_status === "new" && (
        <div className="card p-5">
          <p className="label mb-3">Assign</p>
          <select onChange={e => e.target.value && assign(e.target.value)} disabled={busy} className="input" defaultValue="">
            <option value="" disabled>Choose an admin…</option>
            {admins.map(a => <option key={a.id} value={a.id}>{a.full_name || a.email}</option>)}
          </select>
        </div>
      )}

      {!isTerminal && canPeopleLeads && ["assigned", "collecting_data", "cleaning_data", "awaiting_upload", "revision_required"].includes(req.internal_status) && (
        <form onSubmit={upload} className="card p-5 space-y-2">
          <p className="label">Upload Lead File</p>
          <input type="file" onChange={e => setFile(e.target.files?.[0] || null)} accept=".csv,.xlsx" className="input" style={{ padding: "8px 12px" }} />
          <button type="submit" disabled={busy || !file} className="btn-primary text-sm">Upload</button>
        </form>
      )}

      {!isTerminal && canSupport && req.internal_status === "quality_review" && (
        <div className="card p-5 space-y-2">
          <p className="label">Quality Review</p>
          <textarea value={notes} onChange={e => setNotes(e.target.value)} rows={2} placeholder="Notes…" className="input" style={{ resize: "vertical" }} />
          <div className="flex gap-2">
            <button onClick={() => review("approve")} disabled={busy} className="btn-primary text-sm">Approve</button>
            <button onClick={() => review("reject")} disabled={busy} className="btn-danger text-sm">Reject</button>
          </div>
        </div>
      )}

      {!isTerminal && canPeopleLeads && req.internal_status === "approved" && (
        <div className="card p-5 space-y-2">
          <p className="label">Deliver</p>
          <input type="number" value={deliverQty} onChange={e => setDeliverQty(e.target.value)}
            placeholder={`Default: ${latestFile?.accepted_rows ?? req.requested_quantity}`} className="input" style={{ maxWidth: 220 }} />
          <button onClick={deliver} disabled={busy} className="btn-primary text-sm">Deliver</button>
        </div>
      )}

      {!isTerminal && canPeopleLeads && (
        <form onSubmit={requestRevision} className="card p-5 space-y-2">
          <p className="label">Request Revision from Client</p>
          <textarea value={revisionMsg} onChange={e => setRevisionMsg(e.target.value)} rows={2}
            placeholder="What do you need from the client?" className="input" style={{ resize: "vertical" }} />
          <button type="submit" disabled={busy || !revisionMsg.trim()} className="btn-ghost text-sm">Send</button>
        </form>
      )}

      {req.files.length > 0 && (
        <div className="card overflow-hidden">
          <div className="px-5 py-3.5" style={{ borderBottom: "1px solid var(--border)" }}>
            <p className="text-sm font-semibold" style={{ color: "var(--text)" }}>Uploaded Files</p>
          </div>
          <div className="divide-y" style={{ borderColor: "var(--border)" }}>
            {req.files.map(f => (
              <div key={f.id} className="px-5 py-3">
                <p className="text-sm" style={{ color: "var(--text)" }}>{f.original_filename}</p>
                <p className="text-xs mt-0.5" style={{ color: "var(--text-3)" }}>
                  {f.total_rows} rows · {f.accepted_rows} accepted · {f.rejected_rows} rejected · {f.duplicate_rows} duplicate · {fmt(f.created_at)}
                  {f.approved_by && " · Approved"}
                  {f.delivered_at && ` · Delivered ${fmt(f.delivered_at)}`}
                </p>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

export default function AdminPeopleRequests({ hasPermission, isSuperAdmin }) {
  const [requests, setRequests] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [viewingId, setViewingId] = useState(null);

  const load = async () => {
    setLoading(true); setError("");
    try { setRequests(await api.adminListPeopleLeadRequests()); }
    catch (e) { setError(e.message); }
    finally { setLoading(false); }
  };

  useEffect(() => { load(); }, []);

  // Refetch on return to the list — see AdminBusinessRequests.jsx for why.
  if (viewingId) return (
    <RequestDetail requestId={viewingId} onBack={() => { setViewingId(null); load(); }} onChanged={load}
      hasPermission={hasPermission} isSuperAdmin={isSuperAdmin} />
  );

  if (loading) return (
    <div className="card p-10 text-center animate-soft-pulse">
      <p className="text-sm" style={{ color: "var(--text-3)" }}>Loading people requests…</p>
    </div>
  );
  if (error) return <p className="text-sm" style={{ color: "var(--danger)" }}>{error}</p>;

  return (
    <div className="card overflow-hidden animate-fade-in">
      <div className="px-5 py-3.5 flex items-center justify-between" style={{ borderBottom: "1px solid var(--border)" }}>
        <p className="text-sm font-semibold" style={{ color: "var(--text)" }}>People Requests</p>
        <span className="badge badge-muted mono">{requests.length}</span>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full">
          <thead>
            <tr style={{ borderBottom: "1px solid var(--border)" }}>
              {["Request", "Type", "Location", "Client Status", "Internal Status", "Created", ""].map(h => (
                <th key={h} className="px-4 py-3 text-left text-xs font-medium tracking-wider uppercase" style={{ color: "var(--text-3)" }}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {requests.map((r, i) => (
              <tr key={r.id} style={{ borderTop: i > 0 ? "1px solid var(--border)" : "none" }}>
                <td className="px-4 py-3 text-sm font-medium" style={{ color: "var(--text)" }}>{r.request_name}</td>
                <td className="px-4 py-3 text-xs" style={{ color: "var(--text-2)" }}>{r.lead_type}</td>
                <td className="px-4 py-3 text-xs" style={{ color: "var(--text-3)" }}>{[r.city, r.state].filter(Boolean).join(", ")}</td>
                <td className="px-4 py-3"><span className="badge badge-accent">{r.client_status}</span></td>
                <td className="px-4 py-3"><span className="badge badge-muted mono">{r.internal_status}</span></td>
                <td className="px-4 py-3 text-xs" style={{ color: "var(--text-3)" }}>{fmt(r.created_at)}</td>
                <td className="px-4 py-3">
                  <button onClick={() => setViewingId(r.id)} className="badge badge-muted cursor-pointer hover:opacity-80 transition">View →</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
