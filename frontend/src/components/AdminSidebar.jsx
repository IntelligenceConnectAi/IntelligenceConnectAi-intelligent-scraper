// Admin nav — mirrors Sidebar.jsx's structure but flat (no admin section has
// sub-tabs). Visibility here is UI-only defense in depth; every route behind
// these links is independently backend-gated (see the Phase 8 plan).
const NAV = [
  { id: "overview", icon: "⬡", label: "Overview", always: true },
  { id: "clients", icon: "◎", label: "Clients", always: true },
  { id: "admins", icon: "◈", label: "Admins", requireSuperAdmin: true },
  { id: "business-requests", icon: "⚡", label: "Business Requests", permission: "operations_admin" },
  { id: "people-requests", icon: "◇", label: "People Requests", permission: ["people_leads_admin", "support_admin"] },
  { id: "lead-files", icon: "▤", label: "Lead Files", permission: "operations_admin" },
  { id: "campaign-organizer", icon: "▣", label: "Campaign Organizer", always: true },
  { id: "support", icon: "◈", label: "Support", permission: "support_admin" },
  { id: "audit-logs", icon: "◫", label: "Audit Logs", requireSuperAdmin: true },
];

export default function AdminSidebar({ activeSection, onNavigate, isSuperAdmin, hasPermission, profileEmail, onLogout }) {
  const visible = NAV.filter(item => {
    if (item.always) return true;
    if (item.requireSuperAdmin) return isSuperAdmin;
    if (Array.isArray(item.permission)) return isSuperAdmin || item.permission.some(hasPermission);
    return isSuperAdmin || hasPermission(item.permission);
  });

  return (
    <aside className="hidden lg:flex flex-col w-56 shrink-0 border-r py-5 px-3"
      style={{ background: "var(--bg-secondary)", borderColor: "var(--border)" }}>
      <div className="flex items-center gap-2.5 px-2 mb-8">
        <div className="h-7 w-7 rounded-lg flex items-center justify-center font-bold text-xs shrink-0"
          style={{ background: "var(--accent)", color: "#fff" }}>IS</div>
        <span className="text-sm font-semibold truncate" style={{ color: "var(--text)" }}>
          Admin Console
        </span>
      </div>

      <nav className="flex-1 space-y-0.5 overflow-y-auto">
        {visible.map(item => (
          <button key={item.id} type="button"
            onClick={() => onNavigate(item.id)}
            className={`nav-item ${activeSection === item.id ? "active" : ""}`}>
            <span className="text-base leading-none">{item.icon}</span>
            <span>{item.label}</span>
          </button>
        ))}
      </nav>

      <div className="mt-4 pt-4" style={{ borderTop: "1px solid var(--border)" }}>
        <div className="px-2 mb-3 text-xs truncate" style={{ color: "var(--text-3)" }}
          title={profileEmail}>{profileEmail}</div>
        <button type="button" onClick={onLogout} className="btn-ghost w-full text-left text-xs">
          Sign out
        </button>
      </div>
    </aside>
  );
}
