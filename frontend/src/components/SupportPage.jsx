import { useEffect, useRef, useState } from "react";
import { api } from "../lib/api";
import RequestTabs from "./RequestTabs";

const CATEGORY_LABELS = {
  business_leads: "Business Leads",
  people_leads: "People Leads",
  billing: "Billing",
  account: "Account",
  file_download: "File Download",
  data_quality: "Data Quality",
  technical_issue: "Technical Issue",
  other: "Other",
};

const STATUS_BADGE = {
  open: "badge-blue",
  in_progress: "badge-blue animate-soft-pulse",
  escalated: "badge-warning animate-soft-pulse",
  resolved: "badge-accent",
  closed: "badge-muted",
};

const STATUS_LABELS = {
  open: "Open", in_progress: "In Progress", escalated: "Escalated",
  resolved: "Resolved", closed: "Closed",
};

const LINK_TYPES = [
  { id: "", label: "None" },
  { id: "business_request", label: "Business Leads Request" },
  { id: "people_lead_request", label: "People Leads Request" },
  { id: "lead_file", label: "Lead File" },
  { id: "invoice", label: "Invoice" },
];

function StatusBadge({ status }) {
  return <span className={`badge ${STATUS_BADGE[status] || "badge-muted"}`}>{STATUS_LABELS[status] || status}</span>;
}

function fmt(iso) {
  if (!iso) return "—";
  return new Date(iso).toLocaleString("en-US", { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

function linkOptionLabel(type, item) {
  if (type === "business_request") return `${item.industry} — ${item.state} (${item.cities?.join(", ")})`;
  if (type === "people_lead_request") return item.request_name;
  if (type === "lead_file") return item.display_name;
  if (type === "invoice") return `Invoice ${fmt(item.created_at)} — ${item.currency?.toUpperCase()} ${Number(item.amount_paid).toFixed(2)}`;
  return item.id;
}

async function fetchLinkOptions(type) {
  if (type === "business_request") return api.listBusinessRequests();
  if (type === "people_lead_request") return api.listPeopleLeadRequests();
  if (type === "lead_file") return api.listLeadFiles();
  if (type === "invoice") return api.billingInvoices();
  return [];
}

function NewTicketForm({ onCreated }) {
  const [subject, setSubject] = useState("");
  const [category, setCategory] = useState("other");
  const [body, setBody] = useState("");
  const [linkType, setLinkType] = useState("");
  const [linkOptions, setLinkOptions] = useState([]);
  const [linkLoading, setLinkLoading] = useState(false);
  const [linkedId, setLinkedId] = useState("");
  const [file, setFile] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    setLinkedId("");
    if (!linkType) { setLinkOptions([]); return; }
    setLinkLoading(true);
    fetchLinkOptions(linkType)
      .then(setLinkOptions)
      .catch(() => setLinkOptions([]))
      .finally(() => setLinkLoading(false));
  }, [linkType]);

  const submit = async (e) => {
    e.preventDefault();
    if (!subject.trim() || !body.trim()) { setError("Subject and message are required"); return; }
    setLoading(true); setError("");
    try {
      const fd = new FormData();
      fd.append("subject", subject.trim());
      fd.append("category", category);
      fd.append("body", body.trim());
      if (linkType && linkedId) {
        fd.append("linked_resource_type", linkType);
        fd.append("linked_resource_id", linkedId);
      }
      if (file) fd.append("file", file);
      await api.createTicket(fd);
      setSubject(""); setBody(""); setLinkType(""); setLinkedId(""); setFile(null);
      onCreated();
    } catch (e2) {
      setError(e2.message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="card p-6">
      <p className="font-semibold mb-1" style={{ color: "var(--text)" }}>New Support Ticket</p>
      <p className="text-xs mb-5" style={{ color: "var(--text-3)" }}>Our team typically responds within one business day.</p>
      <form onSubmit={submit} className="space-y-4">
        <div className="grid gap-4 sm:grid-cols-2">
          <div>
            <label className="label">Subject</label>
            <input value={subject} onChange={e => setSubject(e.target.value)}
              placeholder="Brief summary of your issue" className="input" />
          </div>
          <div>
            <label className="label">Category</label>
            <select value={category} onChange={e => setCategory(e.target.value)} className="input">
              {Object.entries(CATEGORY_LABELS).map(([v, l]) => <option key={v} value={v}>{l}</option>)}
            </select>
          </div>
        </div>

        <div>
          <label className="label">Message</label>
          <textarea value={body} onChange={e => setBody(e.target.value)} rows={4}
            placeholder="Describe your issue in detail…" className="input" style={{ resize: "vertical" }} />
        </div>

        <div className="grid gap-4 sm:grid-cols-2">
          <div>
            <label className="label">Link to <span className="normal-case" style={{ color: "var(--text-3)", fontWeight: 400 }}>Optional</span></label>
            <select value={linkType} onChange={e => setLinkType(e.target.value)} className="input">
              {LINK_TYPES.map(t => <option key={t.id} value={t.id}>{t.label}</option>)}
            </select>
          </div>
          {linkType && (
            <div>
              <label className="label">Select item</label>
              <select value={linkedId} onChange={e => setLinkedId(e.target.value)} className="input" disabled={linkLoading}>
                <option value="">{linkLoading ? "Loading…" : "Choose…"}</option>
                {linkOptions.map(item => (
                  <option key={item.id} value={item.id}>{linkOptionLabel(linkType, item)}</option>
                ))}
              </select>
            </div>
          )}
        </div>

        <div>
          <label className="label">Attach a file <span className="normal-case" style={{ color: "var(--text-3)", fontWeight: 400 }}>Optional · PNG, JPG, PDF, CSV, XLSX, TXT — max 10MB</span></label>
          <input type="file" onChange={e => setFile(e.target.files?.[0] || null)}
            accept=".png,.jpg,.jpeg,.pdf,.csv,.xlsx,.txt" className="input" style={{ padding: "8px 12px" }} />
        </div>

        {error && <p className="text-xs" style={{ color: "var(--danger)" }}>{error}</p>}

        <button type="submit" disabled={loading} className="btn-primary w-full">
          {loading ? "Submitting…" : "◇ Submit Ticket"}
        </button>
      </form>
    </div>
  );
}

function MessageBubble({ message, onDownload }) {
  const isAdmin = message.sender_is_admin;
  return (
    <div className={`flex ${isAdmin ? "justify-start" : "justify-end"}`}>
      <div className="max-w-[80%] rounded-lg p-3" style={{
        background: isAdmin ? "var(--bg-secondary)" : "var(--accent-dim)",
        border: "1px solid var(--border)",
      }}>
        <p className="text-xs font-semibold mb-1" style={{ color: isAdmin ? "var(--text-2)" : "var(--accent)" }}>
          {isAdmin ? "Support Team" : "You"}
        </p>
        <p className="text-sm whitespace-pre-wrap" style={{ color: "var(--text)" }}>{message.body}</p>
        {message.attachments.length > 0 && (
          <div className="flex flex-wrap gap-1.5 mt-2">
            {message.attachments.map(a => (
              <button key={a.id} onClick={() => onDownload(a.id)}
                className="badge badge-muted cursor-pointer hover:opacity-80 transition">
                📎 {a.original_filename}
              </button>
            ))}
          </div>
        )}
        <p className="text-[10px] mt-1.5" style={{ color: "var(--text-3)" }}>{fmt(message.created_at)}</p>
      </div>
    </div>
  );
}

function TicketDetail({ ticketId }) {
  const [ticket, setTicket] = useState(null);
  const [error, setError] = useState("");
  const [replyText, setReplyText] = useState("");
  const [replyFile, setReplyFile] = useState(null);
  const [sending, setSending] = useState(false);
  const timer = useRef(null);

  const fetchTicket = async () => {
    try {
      const t = await api.getTicket(ticketId);
      setTicket(t);
      if (t.status === "resolved" || t.status === "closed") clearInterval(timer.current);
    } catch (e) {
      setError(e.message);
      clearInterval(timer.current);
    }
  };

  useEffect(() => {
    fetchTicket();
    timer.current = setInterval(fetchTicket, 15000);
    return () => clearInterval(timer.current);
  }, [ticketId]);

  const sendReply = async (e) => {
    e.preventDefault();
    if (!replyText.trim()) return;
    setSending(true);
    try {
      const fd = new FormData();
      fd.append("body", replyText.trim());
      if (replyFile) fd.append("file", replyFile);
      await api.replyToTicket(ticketId, fd);
      setReplyText(""); setReplyFile(null);
      await fetchTicket();
    } catch (e2) {
      setError(e2.message);
    } finally {
      setSending(false);
    }
  };

  const downloadAttachment = async (attachmentId) => {
    try {
      const r = await api.downloadTicketAttachment(ticketId, attachmentId);
      window.open(r.url, "_blank");
    } catch (e) {
      alert(`Download failed: ${e.message}`);
    }
  };

  if (error) return (
    <div className="alert-danger">{error}</div>
  );

  if (!ticket) return (
    <div className="text-sm animate-soft-pulse" style={{ color: "var(--text-3)" }}>Loading ticket…</div>
  );

  const isClosed = ticket.status === "closed";

  return (
    <div className="space-y-5 animate-fade-in">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="font-semibold" style={{ color: "var(--text)" }}>{ticket.subject}</p>
          <p className="text-xs mt-0.5" style={{ color: "var(--text-3)" }}>
            {CATEGORY_LABELS[ticket.category] || ticket.category}
            {ticket.linked_resource_type && ` · Linked to ${LINK_TYPES.find(t => t.id === ticket.linked_resource_type)?.label || ticket.linked_resource_type}`}
          </p>
        </div>
        <div className="flex gap-1.5">
          <StatusBadge status={ticket.status} />
          <span className="badge badge-muted">{ticket.priority}</span>
        </div>
      </div>

      <div className="space-y-3">
        {ticket.messages.map(m => <MessageBubble key={m.id} message={m} onDownload={downloadAttachment} />)}
      </div>

      {isClosed ? (
        <div className="p-3 rounded-lg text-sm" style={{
          background: "var(--surface-soft)", border: "1px solid var(--border)", color: "var(--text-2)"
        }}>This ticket is closed. Please open a new ticket if you need further help.</div>
      ) : (
        <form onSubmit={sendReply} className="card p-4 space-y-2">
          <label className="label">Reply</label>
          <textarea value={replyText} onChange={e => setReplyText(e.target.value)} rows={3}
            placeholder="Type your reply…" className="input" style={{ resize: "vertical" }} />
          <input type="file" onChange={e => setReplyFile(e.target.files?.[0] || null)}
            accept=".png,.jpg,.jpeg,.pdf,.csv,.xlsx,.txt" className="input text-xs" style={{ padding: "6px 10px" }} />
          <button type="submit" disabled={sending || !replyText.trim()} className="btn-primary">
            {sending ? "Sending…" : "Send Reply"}
          </button>
        </form>
      )}
    </div>
  );
}

export default function SupportPage() {
  const [tab, setTab] = useState("new");
  const [tickets, setTickets] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [viewingId, setViewingId] = useState(null);

  const load = async (bucket) => {
    setLoading(true); setError("");
    try { setTickets(await api.listTickets(bucket)); }
    catch (e) { setError(e.message); }
    finally { setLoading(false); }
  };

  useEffect(() => { if (tab === "open") load("open"); if (tab === "closed") load("closed"); }, [tab]);

  const tabs = [
    { id: "new", label: "New Ticket" },
    { id: "open", label: "Open" },
    { id: "closed", label: "Closed" },
  ];

  return (
    <div className="space-y-4 animate-fade-in">
      <RequestTabs tabs={tabs} activeTab={tab} onChange={(id) => { setViewingId(null); setTab(id); }} />

      {tab === "new" && <NewTicketForm onCreated={() => setTab("open")} />}

      {(tab === "open" || tab === "closed") && (
        viewingId ? (
          <div className="card p-6">
            <button onClick={() => setViewingId(null)} className="btn-ghost text-xs mb-4">← Back to list</button>
            <TicketDetail ticketId={viewingId} />
          </div>
        ) : loading ? (
          <div className="card p-10 text-center animate-soft-pulse">
            <p className="text-sm" style={{ color: "var(--text-3)" }}>Loading…</p>
          </div>
        ) : error ? (
          <div className="alert-danger">{error}</div>
        ) : tickets.length === 0 ? (
          <div className="card p-12 text-center animate-fade-in">
            <p className="text-3xl mb-3">◈</p>
            <p className="font-medium" style={{ color: "var(--text-2)" }}>No {tab} tickets</p>
            <p className="text-sm mt-1" style={{ color: "var(--text-3)" }}>
              {tab === "open" ? "Submit a new ticket to see it here." : "Resolved and closed tickets will appear here."}
            </p>
          </div>
        ) : (
          <div className="card overflow-hidden">
            <div className="divide-y" style={{ borderColor: "var(--border)" }}>
              {tickets.map(t => (
                <button key={t.id} onClick={() => setViewingId(t.id)}
                  className="w-full flex items-center justify-between px-5 py-3.5 text-left transition"
                  style={{ background: "transparent" }}
                  onMouseEnter={e => e.currentTarget.style.background = "var(--row-hover)"}
                  onMouseLeave={e => e.currentTarget.style.background = "transparent"}>
                  <div>
                    <p className="text-sm font-medium" style={{ color: "var(--text)" }}>{t.subject}</p>
                    <p className="text-xs" style={{ color: "var(--text-3)" }}>
                      {CATEGORY_LABELS[t.category] || t.category} · {fmt(t.updated_at)}
                    </p>
                  </div>
                  <div className="flex gap-1.5">
                    <StatusBadge status={t.status} />
                  </div>
                </button>
              ))}
            </div>
          </div>
        )
      )}
    </div>
  );
}
