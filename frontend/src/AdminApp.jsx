import { useEffect, useState } from "react";
import { Sun, Moon } from "lucide-react";
import { api } from "./lib/api";
import AdminSidebar from "./components/AdminSidebar";
import NotificationBell from "./components/NotificationBell";
import AdminOverview from "./components/AdminOverview";
import AdminClients from "./components/AdminClients";
import AdminUsers from "./components/AdminUsers";
import AdminBusinessRequests from "./components/AdminBusinessRequests";
import AdminPeopleRequests from "./components/AdminPeopleRequests";
import AdminLeadFiles from "./components/AdminLeadFiles";
import AdminSupport from "./components/AdminSupport";
import AdminAuditLogs from "./components/AdminAuditLogs";
import AdminCampaignOrganizer from "./components/AdminCampaignOrganizer";

const SECTION_TITLES = {
  overview: "Overview",
  clients: "Clients",
  admins: "Admins",
  "business-requests": "Business Requests",
  "people-requests": "People Requests",
  "lead-files": "Lead Files",
  "campaign-organizer": "Campaign Organizer",
  support: "Support",
  "audit-logs": "Audit Logs",
};

// ═══════════════════════════════════════════════════════════════
// Admin shell (Phase 8) — a sibling to ClientApp.jsx, not a branch bolted
// into it. Has its own activeSection state (deliberately not shared with
// ClientApp's — see the Phase 8 plan for why) and each page self-fetches its
// own data, matching this codebase's established pattern everywhere else.
// ═══════════════════════════════════════════════════════════════
export default function AdminApp({ onLogout, onSwitchToClientView, theme, onToggleTheme }) {
  const [activeSection, setActiveSection] = useState("overview");
  const [profile, setProfile] = useState(null);
  const [me, setMe] = useState(null); // { platform_role, permissions, has_client_org }
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    Promise.all([api.me(), api.adminMyPermissions()])
      .then(([p, m]) => { setProfile(p); setMe(m); })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  if (loading || !me) return (
    <div className="flex min-h-screen items-center justify-center" style={{ background: "var(--bg)" }}>
      <div className="flex flex-col items-center gap-3">
        <div className="h-8 w-8 rounded-full border-2 border-[var(--accent)] border-t-transparent animate-spin" />
        <p className="text-sm muted-text">Loading…</p>
      </div>
    </div>
  );

  const isSuperAdmin = me.platform_role === "super_admin";
  const hasPermission = (key) => me.permissions.includes(key);

  return (
    <div className="min-h-screen flex" style={{ background: "var(--bg)" }}>
      <AdminSidebar
        activeSection={activeSection}
        onNavigate={setActiveSection}
        isSuperAdmin={isSuperAdmin}
        hasPermission={hasPermission}
        profileEmail={profile?.email}
        onLogout={onLogout}
      />

      <div className="flex-1 flex flex-col min-w-0">
        <header className="flex items-center justify-between px-6 py-4 shrink-0"
          style={{ borderBottom: "1px solid var(--border)" }}>
          <h2 className="text-base font-semibold" style={{ color: "var(--text)" }}>
            {SECTION_TITLES[activeSection] || "Admin"}
          </h2>
          <div className="flex items-center gap-2">
            <span className="badge badge-accent">{isSuperAdmin ? "Super Admin" : "Admin"}</span>
            <NotificationBell onNavigate={setActiveSection} />
            <button
              onClick={onToggleTheme}
              className="btn-ghost"
              style={{ padding: "6px 10px" }}
              title={theme === "light" ? "Switch to dark mode" : "Switch to light mode"}
              aria-label={theme === "light" ? "Switch to dark mode" : "Switch to light mode"}
            >
              {theme === "light" ? <Moon size={16} strokeWidth={1.8} /> : <Sun size={16} strokeWidth={1.8} />}
            </button>
            {me.has_client_org && (
              <button onClick={onSwitchToClientView} className="btn-ghost text-xs">
                Switch to client view →
              </button>
            )}
          </div>
        </header>

        <main className="flex-1 p-6 overflow-auto">
          {activeSection === "overview" && <AdminOverview theme={theme} />}
          {activeSection === "clients" && <AdminClients isSuperAdmin={isSuperAdmin} />}
          {activeSection === "admins" && isSuperAdmin && <AdminUsers />}
          {activeSection === "business-requests" && <AdminBusinessRequests />}
          {activeSection === "people-requests" && <AdminPeopleRequests hasPermission={hasPermission} isSuperAdmin={isSuperAdmin} />}
          {activeSection === "lead-files" && <AdminLeadFiles />}
          {activeSection === "campaign-organizer" && <AdminCampaignOrganizer theme={theme} />}
          {activeSection === "support" && <AdminSupport />}
          {activeSection === "audit-logs" && isSuperAdmin && <AdminAuditLogs />}
        </main>
      </div>
    </div>
  );
}
