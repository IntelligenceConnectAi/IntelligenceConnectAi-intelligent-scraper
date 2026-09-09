import { useEffect, useMemo, useState } from "react";
import { Menu, LogOut, Sun, Moon } from "lucide-react";
import { supabase } from "./lib/supabase";
import { api } from "./lib/api";
import Sidebar from "./components/Sidebar";
import DashboardOverview from "./components/DashboardOverview";
import BusinessLeads from "./components/BusinessLeads";
import PeopleLeads from "./components/PeopleLeads";
import MyLeads from "./components/MyLeads";
import HistoryPage from "./components/HistoryPage";
import Settings from "./components/Settings";
import NotificationBell from "./components/NotificationBell";
import SupportPage from "./components/SupportPage";
import CampaignOrganizer from "./components/CampaignOrganizer";

const SECTION_TITLES = {
  dashboard: "Dashboard",
  "my-leads": "My Leads",
  history: "History",
  support: "Support",
};
const GET_LEADS_TITLES = { people: "People Leads", business: "Business Leads" };
const SETTINGS_TITLES = { integrations: "Integrations", team: "Team", billing: "Billing", notifications: "Notifications" };
const CAMPAIGN_ORGANIZER_TITLES = { people: "People Leads", business: "Business Leads", guardrails: "Guardrails Reports" };

// ═══════════════════════════════════════════════════════════════
// Today's entire post-login client shell, moved verbatim out of App.jsx
// (Phase 8) so it can sit as a sibling to AdminApp.jsx rather than living
// behind an if/else in one monolithic component. Unchanged behavior.
// ═══════════════════════════════════════════════════════════════
export default function ClientApp({ session, onLogout, onSwitchToAdminView, theme, onToggleTheme }) {

  // ── Navigation ──
  const [activeSection, setActiveSection] = useState("dashboard");
  const [activeSubTab, setActiveSubTab]   = useState(null);
  const [mobileNavOpen, setMobileNavOpen] = useState(false);

  // ── Profile / plan (shared across sections) ──
  const [profile, setProfile]         = useState(null);
  const [plan, setPlan]               = useState(null);
  const [organization, setOrganization] = useState(null);
  const [dashLoading, setDashLoading] = useState(false);
  const [dashError, setDashError]     = useState("");

  // ── Load profile + plan (refetched when the top-level section changes, e.g.
  // returning to Dashboard/Settings after a Stripe checkout/portal round trip) ──
  useEffect(() => {
    if (!session) return;
    (async () => {
      setDashLoading(true); setDashError("");
      try {
        const [meRes, planRes, orgRes] = await Promise.all([
          api.me(),
          api.currentPlan().catch(() => null),
          api.getOrganization().catch(() => null),
        ]);
        setProfile(meRes);
        setPlan(planRes);
        setOrganization(orgRes);
      } catch (e) {
        // A removed team member's next org-scoped call now returns a clean 403
        // (Phase 6) instead of a 500 — treat it as a forced sign-out rather than
        // a scary error banner.
        if (e.message?.includes("you may have been removed")) {
          await supabase.auth.signOut();
          return;
        }
        setDashError(e.message);
      } finally {
        setDashLoading(false);
      }
    })();
  }, [session, activeSection]);

  const handleNavigate = (section, subTab = null) => {
    setActiveSection(section);
    setActiveSubTab(subTab);
  };

  // ── Derived values ──
  const planName = plan?.plan_name || null;

  const pageTitle = useMemo(() => {
    if (activeSection === "get-leads") return GET_LEADS_TITLES[activeSubTab] || "Get the Leads";
    if (activeSection === "settings")  return SETTINGS_TITLES[activeSubTab] || "Settings";
    if (activeSection === "campaign-organizer") return CAMPAIGN_ORGANIZER_TITLES[activeSubTab] || "Campaign Organizer";
    return SECTION_TITLES[activeSection] || "Dashboard";
  }, [activeSection, activeSubTab]);

  return (
    <div className="min-h-screen flex" style={{ background: "var(--bg)" }}>

      <Sidebar
        activeSection={activeSection}
        activeSubTab={activeSubTab}
        onNavigate={handleNavigate}
        mobileOpen={mobileNavOpen}
        onCloseMobile={() => setMobileNavOpen(false)}
        orgName={organization?.name}
      />

      {/* Main */}
      <div className="flex-1 flex flex-col min-w-0">

        {/* Top bar */}
        <header className="flex items-center justify-between px-6 py-4 shrink-0"
          style={{ borderBottom: "1px solid var(--border)" }}>
          <div className="flex items-center gap-3 min-w-0">
            <button
              onClick={() => setMobileNavOpen(true)}
              className="btn-ghost md:hidden"
              style={{ padding: "6px 8px" }}
              aria-label="Open navigation"
            >
              <Menu size={18} strokeWidth={1.8} />
            </button>
            <h2 className="text-base font-semibold truncate" style={{ color: "var(--text)" }}>
              {dashLoading ? <span className="animate-soft-pulse">{pageTitle}</span> : pageTitle}
            </h2>
          </div>
          <div className="flex items-center gap-2">
            {onSwitchToAdminView && (
              <button onClick={onSwitchToAdminView} className="btn-ghost text-xs">
                ← Admin view
              </button>
            )}
            {planName ? (
              <span className="badge badge-accent">{planName}</span>
            ) : (
              <span className="badge badge-warning">No plan</span>
            )}
            <NotificationBell onNavigate={handleNavigate} />
            <button
              onClick={onToggleTheme}
              className="btn-ghost"
              style={{ padding: "6px 10px" }}
              title={theme === "light" ? "Switch to dark mode" : "Switch to light mode"}
              aria-label={theme === "light" ? "Switch to dark mode" : "Switch to light mode"}
            >
              {theme === "light" ? <Moon size={16} strokeWidth={1.8} /> : <Sun size={16} strokeWidth={1.8} />}
            </button>
            <span className="text-xs truncate hidden lg:inline" style={{ color: "var(--text-3)", maxWidth: 160 }}
              title={profile?.email}>{profile?.email}</span>
            <button onClick={onLogout} className="btn-ghost" style={{ padding: "6px 10px" }} title="Sign out">
              <LogOut size={16} strokeWidth={1.8} />
            </button>
          </div>
        </header>

        {/* Page content */}
        <main className="flex-1 p-6 overflow-auto">
         <div className="dashboard-content">
          {dashError && (
            <div className="alert-danger mb-4">{dashError}</div>
          )}

          {activeSection === "dashboard" && <DashboardOverview onNavigate={handleNavigate} profile={profile} theme={theme} />}

          {activeSection === "get-leads" && activeSubTab === "people" && <PeopleLeads />}
          {activeSection === "get-leads" && (activeSubTab === "business" || !activeSubTab) && <BusinessLeads plan={plan} />}

          {activeSection === "campaign-organizer" && <CampaignOrganizer subTab={activeSubTab} theme={theme} />}

          {activeSection === "my-leads" && <MyLeads onNavigate={handleNavigate} theme={theme} />}

          {activeSection === "history" && <HistoryPage onNavigate={handleNavigate} theme={theme} />}

          {activeSection === "settings" && (
            <Settings
              subTab={activeSubTab}
              profile={profile}
              plan={plan}
              onProfileUpdated={(patch) => setProfile(p => ({ ...p, ...patch }))}
              onLogout={onLogout}
              theme={theme}
            />
          )}

          {activeSection === "support" && <SupportPage />}
         </div>
        </main>
      </div>
    </div>
  );
}
