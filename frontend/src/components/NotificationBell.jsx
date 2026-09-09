import { useEffect, useRef, useState } from "react";
import { api } from "../lib/api";

const POLL_MS = 30000;

function fmt(iso) {
  const d = new Date(iso);
  const diffMin = Math.round((Date.now() - d.getTime()) / 60000);
  if (diffMin < 1) return "just now";
  if (diffMin < 60) return `${diffMin}m ago`;
  const diffHr = Math.round(diffMin / 60);
  if (diffHr < 24) return `${diffHr}h ago`;
  return d.toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

export default function NotificationBell({ onNavigate }) {
  const [open, setOpen] = useState(false);
  const [items, setItems] = useState([]);
  const [unreadCount, setUnreadCount] = useState(0);
  const ref = useRef(null);

  const load = async () => {
    try {
      const res = await api.listNotifications();
      setItems(res.items);
      setUnreadCount(res.unread_count);
    } catch { /* silent — bell just shows stale data until next poll */ }
  };

  useEffect(() => {
    load();
    const interval = setInterval(load, POLL_MS);
    return () => clearInterval(interval);
  }, []);

  useEffect(() => {
    const onClickOutside = (e) => { if (ref.current && !ref.current.contains(e.target)) setOpen(false); };
    document.addEventListener("mousedown", onClickOutside);
    return () => document.removeEventListener("mousedown", onClickOutside);
  }, []);

  const handleClick = async (n) => {
    if (!n.is_read) {
      try { await api.markNotificationRead(n.id); } catch { /* ignore */ }
      setItems(prev => prev.map(i => i.id === n.id ? { ...i, is_read: true } : i));
      setUnreadCount(c => Math.max(0, c - 1));
    }
    setOpen(false);
    if (n.link_section) onNavigate?.(n.link_section, n.link_sub_tab || null);
  };

  const handleMarkAll = async () => {
    try { await api.markAllNotificationsRead(); } catch { /* ignore */ }
    setItems(prev => prev.map(i => ({ ...i, is_read: true })));
    setUnreadCount(0);
  };

  return (
    <div className="relative" ref={ref}>
      <button onClick={() => setOpen(o => !o)} className="btn-ghost relative"
        style={{ padding: "6px 10px", fontSize: "16px", lineHeight: 1 }} title="Notifications">
        🔔
        {unreadCount > 0 && (
          <span className="absolute flex items-center justify-center text-[10px] font-bold"
            style={{
              top: 2, right: 2, minWidth: 16, height: 16, borderRadius: 999,
              background: "var(--danger)", color: "#fff", padding: "0 3px",
            }}>
            {unreadCount > 9 ? "9+" : unreadCount}
          </span>
        )}
      </button>

      {open && (
        <div className="absolute right-0 mt-2 card animate-fade-in z-50"
          style={{ width: 340, maxHeight: 420, overflowY: "auto" }}>
          <div className="flex items-center justify-between px-4 py-3" style={{ borderBottom: "1px solid var(--border)" }}>
            <p className="text-sm font-semibold" style={{ color: "var(--text)" }}>Notifications</p>
            {unreadCount > 0 && (
              <button onClick={handleMarkAll} className="text-xs font-medium" style={{ color: "var(--accent)" }}>
                Mark all read
              </button>
            )}
          </div>
          {items.length === 0 ? (
            <p className="text-sm p-6 text-center" style={{ color: "var(--text-3)" }}>No notifications yet.</p>
          ) : (
            <div>
              {items.map((n, i) => (
                <button key={n.id} onClick={() => handleClick(n)}
                  className="w-full text-left px-4 py-3 transition hover:opacity-80"
                  style={{
                    borderTop: i > 0 ? "1px solid var(--border)" : "none",
                    background: n.is_read ? "transparent" : "rgba(96,165,250,0.06)",
                  }}>
                  <div className="flex items-start justify-between gap-2">
                    <p className="text-sm font-medium" style={{ color: "var(--text)" }}>{n.title}</p>
                    {!n.is_read && <span className="h-1.5 w-1.5 rounded-full shrink-0 mt-1.5" style={{ background: "var(--accent)" }} />}
                  </div>
                  <p className="text-xs mt-0.5" style={{ color: "var(--text-2)" }}>{n.body}</p>
                  <p className="text-[10px] mt-1" style={{ color: "var(--text-3)" }}>{fmt(n.created_at)}</p>
                </button>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
