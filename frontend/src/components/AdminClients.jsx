import { useEffect, useState } from "react";
import { api } from "../lib/api";

const PAGE_SIZE = 50;

function fmt(iso) {
  if (!iso) return "—";
  return new Date(iso).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
}

function fmtMoney(amount, currency) {
  return `${Number(amount).toFixed(2)} ${(currency || "USD").toUpperCase()}`;
}

function ClientDetail({ orgId, isSuperAdmin, onBack }) {
  const [client, setClient] = useState(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [plans, setPlans] = useState([]);
  const [selectedPlan, setSelectedPlan] = useState("");

  const [invoices, setInvoices] = useState([]);
  const [selectedInvoice, setSelectedInvoice] = useState("");
  const [refundAmount, setRefundAmount] = useState("");
  const [refundReason, setRefundReason] = useState("");
  const [alsoSuspend, setAlsoSuspend] = useState(true);

  const load = () => {
    api.adminGetClient(orgId)
      .then(c => { setClient(c); setSelectedPlan(c.plan_id || ""); })
      .catch(e => setError(e.message));
  };

  useEffect(() => { load(); }, [orgId]);

  useEffect(() => {
    if (!isSuperAdmin) return;
    api.adminListPlans().then(setPlans).catch(() => {});
    api.adminListClientInvoices(orgId).then(setInvoices).catch(() => {});
  }, [isSuperAdmin, orgId]);

  const toggleSuspend = async () => {
    setBusy(true);
    try {
      if (client.owner_is_active) await api.adminSuspendClient(orgId);
      else await api.adminReactivateClient(orgId);
      load();
    } catch (e) {
      alert(`Failed: ${e.message}`);
    } finally {
      setBusy(false);
    }
  };

  const savePlan = async () => {
    if (!selectedPlan || selectedPlan === client.plan_id) return;
    setBusy(true);
    try {
      await api.adminUpdateClientPlan(orgId, { plan_id: selectedPlan });
      load();
    } catch (e) {
      alert(`Failed: ${e.message}`);
    } finally {
      setBusy(false);
    }
  };

  const issueRefund = async () => {
    if (!selectedInvoice) return;
    if (!confirm(`Refund invoice ${selectedInvoice}${alsoSuspend ? " and suspend this client" : ""}? This cannot be undone.`)) return;
    setBusy(true);
    try {
      await api.adminRefundClient(orgId, {
        invoice_id: selectedInvoice,
        amount: refundAmount ? Number(refundAmount) : undefined,
        reason: refundReason || undefined,
        also_suspend: alsoSuspend,
      });
      setSelectedInvoice(""); setRefundAmount(""); setRefundReason("");
      load();
    } catch (e) {
      alert(`Refund failed: ${e.message}`);
    } finally {
      setBusy(false);
    }
  };

  if (error) return <p className="text-sm" style={{ color: "var(--danger)" }}>{error}</p>;
  if (!client) return <p className="text-sm animate-soft-pulse" style={{ color: "var(--text-3)" }}>Loading…</p>;

  return (
    <div className="space-y-5 animate-fade-in">
      <button onClick={onBack} className="btn-ghost text-xs">← Back to list</button>
      <div className="card p-5">
        <div className="flex items-start justify-between gap-3 mb-1">
          <p className="font-semibold" style={{ color: "var(--text)" }}>{client.name}</p>
          <div className="flex items-center gap-2">
            <span className={`badge ${client.owner_is_active ? "badge-accent" : "badge-danger"}`}>
              {client.owner_is_active ? "Active" : "Suspended"}
            </span>
            {isSuperAdmin && (
              <button
                onClick={toggleSuspend}
                disabled={busy}
                className={`badge ${client.owner_is_active ? "badge-danger" : "badge-accent"} cursor-pointer hover:opacity-80 transition disabled:opacity-40`}
              >
                {client.owner_is_active ? "Suspend" : "Reactivate"}
              </button>
            )}
          </div>
        </div>
        <p className="text-xs mb-4" style={{ color: "var(--text-3)" }}>{client.owner_email} · Joined {fmt(client.created_at)}</p>
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
          <div className="text-center"><p className="stat-number text-xl">{client.plan_name || "—"}</p><p className="text-[10px] uppercase" style={{ color: "var(--text-3)" }}>Plan</p></div>
          <div className="text-center"><p className="stat-number text-xl">{client.seats_used}/{client.max_team_seats ?? "∞"}</p><p className="text-[10px] uppercase" style={{ color: "var(--text-3)" }}>Seats</p></div>
          <div className="text-center"><p className="stat-number text-xl">{client.jobs_count}</p><p className="text-[10px] uppercase" style={{ color: "var(--text-3)" }}>Business Requests</p></div>
          <div className="text-center"><p className="stat-number text-xl">{client.people_requests_count}</p><p className="text-[10px] uppercase" style={{ color: "var(--text-3)" }}>People Requests</p></div>
          <div className="text-center"><p className="stat-number text-xl">{client.lead_files_count}</p><p className="text-[10px] uppercase" style={{ color: "var(--text-3)" }}>Lead Files</p></div>
          <div className="text-center"><p className="stat-number text-xl">{client.support_tickets_count}</p><p className="text-[10px] uppercase" style={{ color: "var(--text-3)" }}>Support Tickets</p></div>
        </div>

        {isSuperAdmin && (
          <div className="flex items-center gap-2 mt-4 pt-4" style={{ borderTop: "1px solid var(--border)" }}>
            <label className="text-xs" style={{ color: "var(--text-3)" }}>Plan</label>
            <select value={selectedPlan} onChange={e => setSelectedPlan(e.target.value)} className="input" style={{ width: "auto" }}>
              {plans.map(p => (
                <option key={p.id} value={p.id}>{p.name}{p.is_active ? "" : " (inactive)"}</option>
              ))}
            </select>
            <button
              onClick={savePlan}
              disabled={busy || !selectedPlan || selectedPlan === client.plan_id}
              className="btn-ghost text-xs disabled:opacity-40"
            >
              Save
            </button>
          </div>
        )}
      </div>

      <div className="card overflow-hidden">
        <div className="px-5 py-3.5" style={{ borderBottom: "1px solid var(--border)" }}>
          <p className="text-sm font-semibold" style={{ color: "var(--text)" }}>Members</p>
        </div>
        <div className="divide-y" style={{ borderColor: "var(--border)" }}>
          {client.members.map(m => (
            <div key={m.user_id} className="flex items-center justify-between px-5 py-3">
              <div>
                <p className="text-sm" style={{ color: "var(--text)" }}>{m.full_name || m.email}</p>
                <p className="text-xs" style={{ color: "var(--text-3)" }}>{m.email}</p>
              </div>
              <div className="flex items-center gap-1.5">
                <span className="badge badge-muted">{m.role}</span>
                <span className={`badge ${m.is_active ? "badge-accent" : "badge-danger"}`}>{m.is_active ? "Active" : "Disabled"}</span>
              </div>
            </div>
          ))}
        </div>
      </div>

      {isSuperAdmin && (
        <div className="card p-5">
          <p className="text-sm font-semibold mb-3" style={{ color: "var(--text)" }}>Refund</p>
          {invoices.length === 0 ? (
            <p className="text-xs" style={{ color: "var(--text-3)" }}>No invoices found for this client.</p>
          ) : (
            <div className="space-y-3">
              <select value={selectedInvoice} onChange={e => setSelectedInvoice(e.target.value)} className="input">
                <option value="">Select an invoice…</option>
                {invoices.map(inv => (
                  <option key={inv.id} value={inv.id}>
                    {fmt(inv.created_at)} — {fmtMoney(inv.amount_paid, inv.currency)} ({inv.status})
                  </option>
                ))}
              </select>
              <div className="flex flex-wrap items-center gap-2">
                <input
                  value={refundAmount} onChange={e => setRefundAmount(e.target.value)}
                  type="number" min="0" step="0.01" placeholder="Full amount"
                  className="input" style={{ width: 140 }}
                />
                <select value={refundReason} onChange={e => setRefundReason(e.target.value)} className="input" style={{ width: "auto" }}>
                  <option value="">No reason</option>
                  <option value="requested_by_customer">Requested by customer</option>
                  <option value="duplicate">Duplicate</option>
                  <option value="fraudulent">Fraudulent</option>
                </select>
                <label className="flex items-center gap-1.5 text-xs" style={{ color: "var(--text-2)" }}>
                  <input type="checkbox" checked={alsoSuspend} onChange={e => setAlsoSuspend(e.target.checked)} />
                  Also suspend this client
                </label>
                <button
                  onClick={issueRefund}
                  disabled={busy || !selectedInvoice}
                  className="badge badge-danger cursor-pointer hover:opacity-80 transition disabled:opacity-40"
                >
                  Issue Refund
                </button>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export default function AdminClients({ isSuperAdmin }) {
  const [clients, setClients] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [viewingId, setViewingId] = useState(null);

  const [q, setQ] = useState("");
  const [active, setActive] = useState("");
  const [offset, setOffset] = useState(0);

  const load = () => {
    setLoading(true); setError("");
    api.adminListClients({ q: q || undefined, active: active || undefined, limit: PAGE_SIZE, offset })
      .then(setClients)
      .catch(e => setError(e.message))
      .finally(() => setLoading(false));
  };

  useEffect(() => { load(); }, [offset]);

  const submitFilters = (e) => {
    e.preventDefault();
    setOffset(0);
    load();
  };

  if (viewingId) return <ClientDetail orgId={viewingId} isSuperAdmin={isSuperAdmin} onBack={() => setViewingId(null)} />;

  return (
    <div className="space-y-4 animate-fade-in">
      <form onSubmit={submitFilters} className="flex flex-wrap items-center gap-2">
        <input value={q} onChange={e => setQ(e.target.value)} placeholder="Search org, owner name or email…" className="input" style={{ maxWidth: 280 }} />
        <select value={active} onChange={e => setActive(e.target.value)} className="input" style={{ width: "auto" }}>
          <option value="">All statuses</option>
          <option value="true">Active</option>
          <option value="false">Suspended</option>
        </select>
        <button type="submit" className="btn-ghost text-xs">Search</button>
      </form>

      {loading ? (
        <div className="card p-10 text-center animate-soft-pulse">
          <p className="text-sm" style={{ color: "var(--text-3)" }}>Loading clients…</p>
        </div>
      ) : error ? (
        <p className="text-sm" style={{ color: "var(--danger)" }}>{error}</p>
      ) : (
        <div className="card overflow-hidden">
          <div className="px-5 py-3.5 flex items-center justify-between" style={{ borderBottom: "1px solid var(--border)" }}>
            <p className="text-sm font-semibold" style={{ color: "var(--text)" }}>Clients</p>
            <span className="badge badge-muted mono">{clients.length}</span>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead>
                <tr style={{ borderBottom: "1px solid var(--border)" }}>
                  {["Organization", "Owner", "Plan", "Status", "Seats", "Joined", ""].map(h => (
                    <th key={h} className="px-4 py-3 text-left text-xs font-medium tracking-wider uppercase" style={{ color: "var(--text-3)" }}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {clients.map((c, i) => (
                  <tr key={c.id} style={{ borderTop: i > 0 ? "1px solid var(--border)" : "none" }}>
                    <td className="px-4 py-3 text-sm font-medium" style={{ color: "var(--text)" }}>{c.name}</td>
                    <td className="px-4 py-3 text-xs" style={{ color: "var(--text-2)" }}>{c.owner_email}</td>
                    <td className="px-4 py-3"><span className="badge badge-muted">{c.plan_name || "—"}</span></td>
                    <td className="px-4 py-3">
                      <span className={`badge ${c.owner_is_active ? "badge-accent" : "badge-danger"}`}>
                        {c.owner_is_active ? "Active" : "Suspended"}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-xs mono" style={{ color: "var(--text-2)" }}>{c.seats_used}/{c.max_team_seats ?? "∞"}</td>
                    <td className="px-4 py-3 text-xs" style={{ color: "var(--text-3)" }}>{fmt(c.created_at)}</td>
                    <td className="px-4 py-3">
                      <button onClick={() => setViewingId(c.id)} className="badge badge-muted cursor-pointer hover:opacity-80 transition">View →</button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="flex items-center justify-between px-5 py-3" style={{ borderTop: "1px solid var(--border)" }}>
            <button onClick={() => setOffset(o => Math.max(0, o - PAGE_SIZE))} disabled={offset === 0} className="btn-ghost text-xs disabled:opacity-40">← Prev</button>
            <button onClick={() => setOffset(o => o + PAGE_SIZE)} disabled={clients.length < PAGE_SIZE} className="btn-ghost text-xs disabled:opacity-40">Next →</button>
          </div>
        </div>
      )}
    </div>
  );
}
