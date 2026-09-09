import { useEffect, useState } from "react";
import { api } from "../lib/api";

const STATUSES = ["open", "in_progress", "escalated", "resolved", "closed"];
const PRIORITIES = ["low", "normal", "high", "urgent"];

function fmt(iso) {
  if (!iso) return "—";
  return new Date(iso).toLocaleString("en-US", { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

function MessageBubble({ message, onDownload }) {
  const bg = message.is_internal_note ? "rgba(255,193,7,0.08)" : message.sender_is_admin ? "var(--bg-secondary)" : "var(--accent-dim)";
  return (
    <div className="rounded-lg p-3" style={{ background: bg, border: "1px solid var(--border)" }}>
      <p className="text-xs font-semibold mb-1" style={{ color: message.is_internal_note ? "var(--warning)" : "var(--text-2)" }}>
        {message.is_internal_note ? "Internal Note" : message.sender_is_admin ? "Support Team" : "Client"}
      </p>
      <p className="text-sm whitespace-pre-wrap" style={{ color: "var(--text)" }}>{message.body}</p>
      {message.attachments.length > 0 && (
        <div className="flex flex-wrap gap-1.5 mt-2">
          {message.attachments.map(a => (
            <button key={a.id} onClick={() => onDownload(a.id)} className="badge badge-muted cursor-pointer hover:opacity-80 transition">
              📎 {a.original_filename}
            </button>
          ))}
        </div>
      )}
      <p className="text-[10px] mt-1.5" style={{ color: "var(--text-3)" }}>{fmt(message.created_at)}</p>
    </div>
  );
}

function TicketDetail({ ticketId, onBack, onChanged }) {
  const [ticket, setTicket] = useState(null);
  const [error, setError] = useState("");
  const [admins, setAdmins] = useState([]);
  const [busy, setBusy] = useState(false);
  const [replyText, setReplyText] = useState("");
  const [noteText, setNoteText] = useState("");

  const load = () => api.adminGetTicket(ticketId).then(setTicket).catch(e => setError(e.message));
  useEffect(() => { load(); }, [ticketId]);
  useEffect(() => { api.adminListUsers({ permission: "support_admin" }).then(setAdmins).catch(() => {}); }, []);

  const patch = async (field, value) => {
    setBusy(true);
    try { await api.adminPatchTicket(ticketId, { [field]: value }); await load(); onChanged(); }
    catch (e) { alert(`Update failed: ${e.message}`); }
    finally { setBusy(false); }
  };

  const assign = async (adminId) => {
    if (!adminId) return;
    setBusy(true);
    try { await api.adminAssignTicket(ticketId, adminId); await load(); onChanged(); }
    catch (e) { alert(`Assign failed: ${e.message}`); }
    finally { setBusy(false); }
  };

  const sendReply = async (e) => {
    e.preventDefault();
    if (!replyText.trim()) return;
    setBusy(true);
    try {
      const fd = new FormData(); fd.append("body", replyText.trim());
      await api.adminReplyTicket(ticketId, fd);
      setReplyText(""); await load(); onChanged();
    } catch (e2) { alert(`Reply failed: ${e2.message}`); }
    finally { setBusy(false); }
  };

  const sendNote = async (e) => {
    e.preventDefault();
    if (!noteText.trim()) return;
    setBusy(true);
    try {
      const fd = new FormData(); fd.append("body", noteText.trim());
      await api.adminAddInternalNote(ticketId, fd);
      setNoteText(""); await load(); onChanged();
    } catch (e2) { alert(`Note failed: ${e2.message}`); }
    finally { setBusy(false); }
  };

  const downloadAttachment = async (attachmentId) => {
    try { const r = await api.adminDownloadTicketAttachment(ticketId, attachmentId); window.open(r.url, "_blank"); }
    catch (e) { alert(`Download failed: ${e.message}`); }
  };

  if (error) return <p className="text-sm" style={{ color: "var(--danger)" }}>{error}</p>;
  if (!ticket) return <p className="text-sm animate-soft-pulse" style={{ color: "var(--text-3)" }}>Loading…</p>;

  return (
    <div className="space-y-5 animate-fade-in">
      <button onClick={onBack} className="btn-ghost text-xs">← Back to list</button>

      <div className="card p-5">
        <p className="font-semibold mb-1" style={{ color: "var(--text)" }}>{ticket.subject}</p>
        <p className="text-xs mb-4" style={{ color: "var(--text-3)" }}>{ticket.category}</p>
        <div className="flex flex-wrap gap-3">
          <div>
            <label className="label" style={{ marginBottom: 2 }}>Status</label>
            <select value={ticket.status} disabled={busy} onChange={e => patch("status", e.target.value)} className="input text-xs" style={{ padding: "6px 8px" }}>
              {STATUSES.map(s => <option key={s} value={s}>{s}</option>)}
            </select>
          </div>
          <div>
            <label className="label" style={{ marginBottom: 2 }}>Priority</label>
            <select value={ticket.priority} disabled={busy} onChange={e => patch("priority", e.target.value)} className="input text-xs" style={{ padding: "6px 8px" }}>
              {PRIORITIES.map(p => <option key={p} value={p}>{p}</option>)}
            </select>
          </div>
          <div>
            <label className="label" style={{ marginBottom: 2 }}>Assign</label>
            <select defaultValue="" disabled={busy} onChange={e => assign(e.target.value)} className="input text-xs" style={{ padding: "6px 8px" }}>
              <option value="" disabled>Choose…</option>
              {admins.map(a => <option key={a.id} value={a.id}>{a.full_name || a.email}</option>)}
            </select>
          </div>
        </div>
      </div>

      <div className="space-y-3">
        {ticket.messages.map(m => <MessageBubble key={m.id} message={m} onDownload={downloadAttachment} />)}
      </div>

      <form onSubmit={sendReply} className="card p-4 space-y-2">
        <label className="label">Reply to Client</label>
        <textarea value={replyText} onChange={e => setReplyText(e.target.value)} rows={3} placeholder="Visible to the client…" className="input" style={{ resize: "vertical" }} />
        <button type="submit" disabled={busy || !replyText.trim()} className="btn-primary text-sm">Send Reply</button>
      </form>

      <form onSubmit={sendNote} className="card p-4 space-y-2">
        <label className="label">Internal Note <span className="normal-case" style={{ color: "var(--text-3)", fontWeight: 400 }}>Never visible to the client</span></label>
        <textarea value={noteText} onChange={e => setNoteText(e.target.value)} rows={2} placeholder="Notes for the team…" className="input" style={{ resize: "vertical" }} />
        <button type="submit" disabled={busy || !noteText.trim()} className="btn-ghost text-sm">Add Note</button>
      </form>
    </div>
  );
}

export default function AdminSupport() {
  const [tickets, setTickets] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [viewingId, setViewingId] = useState(null);

  const load = async () => {
    setLoading(true); setError("");
    try { setTickets(await api.adminListTickets()); }
    catch (e) { setError(e.message); }
    finally { setLoading(false); }
  };

  useEffect(() => { load(); }, []);

  if (viewingId) return <TicketDetail ticketId={viewingId} onBack={() => setViewingId(null)} onChanged={load} />;

  if (loading) return (
    <div className="card p-10 text-center animate-soft-pulse">
      <p className="text-sm" style={{ color: "var(--text-3)" }}>Loading tickets…</p>
    </div>
  );
  if (error) return <p className="text-sm" style={{ color: "var(--danger)" }}>{error}</p>;

  return (
    <div className="card overflow-hidden animate-fade-in">
      <div className="px-5 py-3.5 flex items-center justify-between" style={{ borderBottom: "1px solid var(--border)" }}>
        <p className="text-sm font-semibold" style={{ color: "var(--text)" }}>Support Tickets</p>
        <span className="badge badge-muted mono">{tickets.length}</span>
      </div>
      <div className="divide-y" style={{ borderColor: "var(--border)" }}>
        {tickets.map(t => (
          <button key={t.id} onClick={() => setViewingId(t.id)}
            className="w-full flex items-center justify-between px-5 py-3.5 text-left transition"
            onMouseEnter={e => e.currentTarget.style.background = "var(--row-hover)"}
            onMouseLeave={e => e.currentTarget.style.background = "transparent"}>
            <div>
              <p className="text-sm font-medium" style={{ color: "var(--text)" }}>{t.subject}</p>
              <p className="text-xs" style={{ color: "var(--text-3)" }}>{t.category} · {fmt(t.updated_at)}</p>
            </div>
            <div className="flex gap-1.5">
              <span className="badge badge-muted">{t.priority}</span>
              <span className="badge badge-accent">{t.status}</span>
            </div>
          </button>
        ))}
      </div>
    </div>
  );
}
