import { useEffect, useMemo, useState } from "react";
import { supabase } from "./lib/supabase";
import { api } from "./lib/api";
import ScrapeLeads from "./components/ScrapeLeads";
import History from "./components/History";
import Signup from "./components/Signup";

// ── Plan price IDs from env ─────────────────────────────────────
const PRICE_IDS = {
  starter:    import.meta.env.VITE_STRIPE_STARTER_PRICE_ID    || "",
  pro:        import.meta.env.VITE_STRIPE_PRO_PRICE_ID        || "",
  elite:      import.meta.env.VITE_STRIPE_ELITE_PRICE_ID      || "",
  enterprise: import.meta.env.VITE_STRIPE_ENTERPRISE_PRICE_ID || "",
};

// ── Tab config ──────────────────────────────────────────────────
const TAB_CONFIG = [
  { id: "Dashboard",      icon: "⬡", label: "Dashboard"      },
  { id: "Scrape Leads",   icon: "⚡", label: "Scrape Leads"   },
  { id: "History",        icon: "◫", label: "History"         },
  { id: "Plan & Billing", icon: "◈", label: "Plan & Billing"  },
  { id: "Settings",       icon: "◎", label: "Settings"        },
];

// ── Stat card ───────────────────────────────────────────────────
function StatCard({ label, value, accent = false, delay = 0 }) {
  return (
    <div className={`card p-5 animate-fade-up delay-${delay} relative overflow-hidden`}>
      {accent && (
        <div className="absolute inset-0 bg-gradient-to-br from-[var(--accent-dim)] to-transparent opacity-60 pointer-events-none" />
      )}
      <p className="label">{label}</p>
      <p className={`stat-number mt-2 ${accent ? "accent-text" : ""}`}>{value.toLocaleString()}</p>
    </div>
  );
}

// ── Pricing card ───────────────────────────────────────────────
function PricingCard({ name, price, priceId, features, popular, current, onBuy, loading, isEnterprise }) {
  return (
    <div className={`card relative ${popular ? "ring-2 ring-[var(--accent)]" : ""}`}
      style={{ padding: popular ? "2rem 1.25rem 1.25rem" : "1.25rem" }}>
      {popular && (
        <div style={{ textAlign: "center", marginBottom: "0.75rem", marginTop: "-0.5rem" }}>
          <span className="badge badge-accent text-xs px-3">Most Popular</span>
        </div>
      )}
      <div className="flex items-baseline justify-between mb-1">
        <p className="font-semibold text-sm" style={{ color: "var(--text)" }}>{name}</p>
        {current && <span className="badge badge-accent text-xs">Current</span>}
      </div>
      <p className="text-2xl font-bold mono mb-3" style={{ color: popular ? "var(--accent)" : "var(--text)" }}>
        ${price}{isEnterprise ? "+" : ""}<span className="text-sm font-normal" style={{ color: "var(--text-2)" }}>/mo</span>
      </p>
      <ul className="space-y-1.5 mb-4">
        {features.map((f, i) => (
          <li key={i} className="flex items-center gap-2 text-xs" style={{ color: "var(--text-2)" }}>
            <span style={{ color: "var(--accent)" }}>✓</span> {f}
          </li>
        ))}
      </ul>
      {current ? (
        <button disabled className="btn-ghost w-full text-sm opacity-50 cursor-not-allowed">
          Active plan
        </button>
      ) : isEnterprise ? (
        <a
          href="mailto:support@intelligenceconnectai.com?subject=Enterprise Plan Inquiry"
          className="btn-primary w-full text-sm text-center block"
          style={{ textDecoration: "none" }}
        >
          Contact Sales →
        </a>
      ) : (
        <button
          onClick={() => onBuy(priceId)}
          disabled={loading}
          className={popular ? "btn-primary w-full text-sm" : "btn-ghost w-full text-sm"}
        >
          {loading ? "Redirecting…" : `Get ${name} →`}
        </button>
      )}
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════
export default function App() {

  // ── Auth ──
  const [session, setSession]         = useState(null);
  const [authLoading, setAuthLoading] = useState(true);
  const [darkMode, setDarkMode]       = useState(() => localStorage.getItem("theme") !== "light");

  // ── Login form ──
  const [view, setView]               = useState("login");
  const [email, setEmail]             = useState("");
  const [password, setPassword]       = useState("");
  const [formLoading, setFormLoading] = useState(false);
  const [formMsg, setFormMsg]         = useState("");
  const [isError, setIsError]         = useState(false);

  // ── Dashboard ──
  const [activeTab, setActiveTab]     = useState("Dashboard");
  const [profile, setProfile]         = useState(null);
  const [usage, setUsage]             = useState(null);
  const [plan, setPlan]               = useState(null);
  const [dashLoading, setDashLoading] = useState(false);
  const [dashError, setDashError]     = useState("");

  // ── Settings ──
  const [nameInput, setNameInput]     = useState("");
  const [nameSaving, setNameSaving]   = useState(false);
  const [nameMsg, setNameMsg]         = useState("");

  // ── Billing ──
  const [checkoutLoading, setCheckoutLoading] = useState(false);
  const [portalLoading, setPortalLoading]     = useState(false);
  const [billingError, setBillingError]       = useState("");

  // ── Theme ──
  useEffect(() => {
    const root = document.documentElement;
    if (darkMode) {
      root.style.setProperty("--bg",           "#080810");
      root.style.setProperty("--bg-secondary", "#0f0f1a");
      root.style.setProperty("--bg-card",      "#12121f");
      root.style.setProperty("--border",       "rgba(255,255,255,0.07)");
      root.style.setProperty("--border-hover", "rgba(255,255,255,0.14)");
      root.style.setProperty("--text",         "#f0f0f8");
      root.style.setProperty("--text-2",       "#8888aa");
      root.style.setProperty("--text-3",       "#55557a");
      localStorage.setItem("theme", "dark");
    } else {
      root.style.setProperty("--bg",           "#f4f4f8");
      root.style.setProperty("--bg-secondary", "#ffffff");
      root.style.setProperty("--bg-card",      "#ffffff");
      root.style.setProperty("--border",       "rgba(0,0,0,0.08)");
      root.style.setProperty("--border-hover", "rgba(0,0,0,0.15)");
      root.style.setProperty("--text",         "#0a0a14");
      root.style.setProperty("--text-2",       "#555566");
      root.style.setProperty("--text-3",       "#9999aa");
      localStorage.setItem("theme", "light");
    }
  }, [darkMode]);

  // ── Session ──
  useEffect(() => {
    supabase.auth.getSession().then(({ data: { session } }) => {
      setSession(session); setAuthLoading(false);
    });
    const { data: sub } = supabase.auth.onAuthStateChange((_e, s) => setSession(s));
    return () => sub.subscription.unsubscribe();
  }, []);

  // ── Load dashboard data ──
  useEffect(() => {
    if (!session) return;
    (async () => {
      setDashLoading(true); setDashError("");
      try {
        const [meRes, usageRes, planRes] = await Promise.all([
          api.me(),
          api.usageToday().catch(() => null),
          api.currentPlan().catch(() => null),
        ]);
        setProfile(meRes);
        setUsage(usageRes);
        setPlan(planRes);
        setNameInput(meRes?.full_name || "");
      } catch (e) {
        setDashError(e.message);
      } finally {
        setDashLoading(false);
      }
    })();
  }, [session, activeTab]);

  // ── Handlers ──
  const handleLogin = async (e) => {
    e.preventDefault(); setFormLoading(true); setFormMsg("");
    try {
      const { error } = await supabase.auth.signInWithPassword({ email, password });
      if (error) throw error;
      setActiveTab("Dashboard");
    } catch (e) {
      setIsError(true); setFormMsg(e.message || "Login failed");
    } finally {
      setFormLoading(false);
    }
  };

  const handleForgot = async (e) => {
    e.preventDefault(); setFormLoading(true); setFormMsg("");
    try {
      const { error } = await supabase.auth.resetPasswordForEmail(email, {
        redirectTo: `${window.location.origin}/reset-password`,
      });
      if (error) throw error;
      setIsError(false); setFormMsg("Reset link sent — check your inbox.");
    } catch (e) {
      setIsError(true); setFormMsg(e.message);
    } finally {
      setFormLoading(false);
    }
  };

  const handleSaveName = async () => {
    if (!nameInput.trim()) return;
    setNameSaving(true); setNameMsg("");
    try {
      await api.updateProfile({ full_name: nameInput.trim() });
      setProfile(p => ({ ...p, full_name: nameInput.trim() }));
      setNameMsg("Saved!");
      setTimeout(() => setNameMsg(""), 2500);
    } catch (e) {
      setNameMsg("Failed: " + e.message);
    } finally {
      setNameSaving(false);
    }
  };

  const handleLogout = async () => {
    await supabase.auth.signOut();
    setProfile(null); setUsage(null); setPlan(null);
    setFormMsg(""); setIsError(false); setView("login"); setPassword("");
  };

  const handleBuyPlan = async (priceId) => {
    if (!priceId) { setBillingError("Price ID not configured."); return; }
    setCheckoutLoading(true); setBillingError("");
    try {
      const res = await api.createCheckout(priceId);
      if (res.checkout_url) window.location.href = res.checkout_url;
      else setBillingError("No checkout URL received");
    } catch (e) {
      setBillingError(e.message);
    } finally {
      setCheckoutLoading(false);
    }
  };

  const handleManageBilling = async () => {
    setPortalLoading(true); setBillingError("");
    try {
      const res = await api.getBillingPortal();
      window.open(res.portal_url, "_blank");
    } catch (e) {
      setBillingError(e.message);
    } finally {
      setPortalLoading(false);
    }
  };

  // ── Derived values ──
  const greetingName = useMemo(() => {
    if (profile?.full_name) return profile.full_name.split(" ")[0];
    if (profile?.email)     return profile.email.split("@")[0];
    return "there";
  }, [profile]);

  const dailyLimit  = usage?.daily_limit         ?? 0;
  const leadsToday  = usage?.leads_used_today     ?? 0;
  const withWeb     = usage?.leads_with_web_today ?? 0;
  const noWeb       = usage?.leads_no_web_today   ?? 0;
  const emailsToday = usage?.emails_found_today   ?? 0;
  const remaining   = usage?.leads_remaining      ?? 0;
  const usagePct    = dailyLimit > 0 ? Math.min(100, Math.round((leadsToday / dailyLimit) * 100)) : 0;
  const planName    = plan?.plan_name  || null;
  const currentPlanId = plan?.plan_id || null;

  // ── Updated plans with new pricing ──
  const PLANS = [
    {
      id: "starter", name: "Starter", price: 49, priceId: PRICE_IDS.starter,
      features: [
        "5,000 leads/month",
        "167 leads per day",
        "10 cities per job",
        "Phone, address, website",
        "7-day history",
      ],
      popular: false,
    },
    {
      id: "pro", name: "Pro", price: 197, priceId: PRICE_IDS.pro,
      features: [
        "40,000 leads/month",
        "1,333 leads per day",
        "30 cities per job",
        "Email scraping included",
        "30-day history",
      ],
      popular: true,
    },
    {
      id: "elite", name: "Elite", price: 397, priceId: PRICE_IDS.elite,
      features: [
        "100,000 leads/month",
        "3,333 leads per day",
        "100 cities per job",
        "Email scraping included",
        "365-day history + API access",
      ],
      popular: false,
    },
    {
      id: "enterprise", name: "Enterprise", price: 1500, priceId: PRICE_IDS.enterprise,
      features: [
        "250,000+ leads/month",
        "8,333+ leads per day",
        "Unlimited cities per job",
        "Email scraping included",
        "Dedicated support + custom SLA",
      ],
      popular: false,
      isEnterprise: true,
    },
  ];

  // ── Auth guards ──
  const isSignupRoute = window.location.pathname === "/signup";
  if (isSignupRoute && !session) {
    return <Signup onSuccess={() => { window.location.href = "/"; }} />;
  }

  if (authLoading) return (
    <div className="flex min-h-screen items-center justify-center" style={{ background: "var(--bg)" }}>
      <div className="flex flex-col items-center gap-3">
        <div className="h-8 w-8 rounded-full border-2 border-[var(--accent)] border-t-transparent animate-spin" />
        <p className="text-sm muted-text">Loading…</p>
      </div>
    </div>
  );

  // ── Login / Forgot ──
  if (!session) return (
    <div className="min-h-screen flex items-center justify-center px-4 relative overflow-hidden"
      style={{ background: "var(--bg)" }}>
      <div className="pointer-events-none absolute top-1/4 left-1/4 h-96 w-96 rounded-full opacity-20 blur-[120px]"
        style={{ background: "var(--accent)" }} />
      <div className="pointer-events-none absolute bottom-1/4 right-1/4 h-64 w-64 rounded-full opacity-10 blur-[100px]"
        style={{ background: "#6060ff" }} />

      <div className="card-glass w-full max-w-sm p-8 animate-fade-up relative z-10">
        <div className="mb-8">
          <div className="flex items-center gap-2 mb-4">
            <div className="h-8 w-8 rounded-lg flex items-center justify-center font-bold text-sm"
              style={{ background: "var(--accent)", color: "#fff" }}>IS</div>
            <span className="text-sm font-semibold" style={{ color: "var(--text)" }}>Intelligent Scraper</span>
          </div>
          <h1 className="text-2xl font-bold" style={{ color: "var(--text)" }}>
            {view === "login" ? "Welcome back" : "Reset password"}
          </h1>
          <p className="text-sm mt-1" style={{ color: "var(--text-2)" }}>
            {view === "login" ? "Sign in to your account" : "Enter your email for a reset link"}
          </p>
        </div>

        {view === "login" ? (
          <form onSubmit={handleLogin} className="space-y-4">
            <div>
              <label className="label">Email</label>
              <input type="email" value={email} onChange={e => setEmail(e.target.value)}
                required autoComplete="email" placeholder="you@example.com" className="input" />
            </div>
            <div>
              <div className="flex items-center justify-between mb-[0.35rem]">
                <label className="label" style={{ marginBottom: 0 }}>Password</label>
                <button type="button" onClick={() => { setView("forgot"); setFormMsg(""); }}
                  className="text-xs font-medium transition" style={{ color: "var(--accent)" }}>
                  Forgot password?
                </button>
              </div>
              <input type="password" value={password} onChange={e => setPassword(e.target.value)}
                required autoComplete="current-password" placeholder="••••••••" className="input" />
            </div>
            {formMsg && (
              <p className={`text-xs ${isError ? "text-[var(--danger)]" : "text-[var(--accent)]"}`}>{formMsg}</p>
            )}
            <button type="submit" disabled={formLoading} className="btn-primary w-full mt-2">
              {formLoading
                ? <span className="flex items-center justify-center gap-2">
                    <span className="h-3.5 w-3.5 rounded-full border-2 border-white/30 border-t-white animate-spin" />
                    Signing in…
                  </span>
                : "Sign in →"}
            </button>
            <p className="text-center text-xs mt-3" style={{ color: "var(--text-3)" }}>
              Just purchased?{" "}
              <a href="/signup" className="font-medium" style={{ color: "var(--accent)" }}>
                Complete your account →
              </a>
            </p>
          </form>
        ) : (
          <form onSubmit={handleForgot} className="space-y-4">
            <div>
              <label className="label">Email</label>
              <input type="email" value={email} onChange={e => setEmail(e.target.value)}
                required autoComplete="email" placeholder="you@example.com" className="input" />
            </div>
            {formMsg && (
              <p className={`text-xs ${isError ? "text-[var(--danger)]" : "text-[var(--accent)]"}`}>{formMsg}</p>
            )}
            <button type="submit" disabled={formLoading} className="btn-primary w-full">
              {formLoading ? "Sending…" : "Send reset link →"}
            </button>
            <button type="button" onClick={() => { setView("login"); setFormMsg(""); }}
              className="w-full text-center text-xs transition" style={{ color: "var(--text-3)" }}>
              ← Back to sign in
            </button>
          </form>
        )}
      </div>
    </div>
  );

  // ═══════════════════════════════════════
  //  DASHBOARD
  // ═══════════════════════════════════════
  return (
    <div className="min-h-screen flex" style={{ background: "var(--bg)" }}>

      {/* Sidebar */}
      <aside className="hidden lg:flex flex-col w-56 shrink-0 border-r py-5 px-3"
        style={{ background: "var(--bg-secondary)", borderColor: "var(--border)" }}>
        <div className="flex items-center gap-2.5 px-2 mb-8">
          <div className="h-7 w-7 rounded-lg flex items-center justify-center font-bold text-xs shrink-0"
            style={{ background: "var(--accent)", color: "#fff" }}>IS</div>
          <span className="text-sm font-semibold truncate" style={{ color: "var(--text)" }}>
            Intelligent Scraper
          </span>
        </div>

        <nav className="flex-1 space-y-0.5">
          {TAB_CONFIG.map(tab => (
            <button key={tab.id} type="button"
              onClick={() => setActiveTab(tab.id)}
              className={`nav-item ${activeTab === tab.id ? "active" : ""}`}>
              <span className="text-base leading-none">{tab.icon}</span>
              <span>{tab.label}</span>
            </button>
          ))}
        </nav>

        <div className="mt-4 pt-4" style={{ borderTop: "1px solid var(--border)" }}>
          {planName && (
            <div className="px-2 mb-3">
              <span className="badge badge-accent">{planName} Plan</span>
            </div>
          )}
          <div className="px-2 mb-3 text-xs truncate" style={{ color: "var(--text-3)" }}
            title={profile?.email}>{profile?.email}</div>
          <button type="button" onClick={handleLogout} className="btn-ghost w-full text-left text-xs">
            Sign out
          </button>
        </div>
      </aside>

      {/* Main */}
      <div className="flex-1 flex flex-col min-w-0">

        {/* Top bar */}
        <header className="flex items-center justify-between px-6 py-4 shrink-0"
          style={{ borderBottom: "1px solid var(--border)" }}>
          <h2 className="text-base font-semibold" style={{ color: "var(--text)" }}>{activeTab}</h2>
          <div className="flex items-center gap-2">
            {dailyLimit > 0 && (
              <span className="badge badge-muted mono">{remaining.toLocaleString()} leads left</span>
            )}
            {planName ? (
              <span className="badge badge-accent">{planName}</span>
            ) : (
              <span className="badge badge-warning">No plan</span>
            )}
            <button
              onClick={() => setDarkMode(d => !d)}
              className="btn-ghost"
              style={{ padding: "6px 10px", fontSize: "16px", lineHeight: 1 }}
              title={darkMode ? "Switch to light mode" : "Switch to dark mode"}
            >
              {darkMode ? "☀️" : "🌙"}
            </button>
          </div>
        </header>

        {/* Page content */}
        <main className="flex-1 p-6 overflow-auto">
          {dashError && (
            <div className="mb-4 p-3 rounded-lg text-sm" style={{
              background: "rgba(255,77,106,0.08)",
              border: "1px solid rgba(255,77,106,0.2)",
              color: "var(--danger)"
            }}>{dashError}</div>
          )}

          {/* DASHBOARD */}
          {activeTab === "Dashboard" && (
            <div className="space-y-5 animate-fade-in">
              <div>
                <h3 className="text-2xl font-bold" style={{ color: "var(--text)" }}>
                  {dashLoading
                    ? <span className="animate-soft-pulse">Loading…</span>
                    : <>Good to see you, <span style={{ color: "var(--accent)" }}>{greetingName}</span></>
                  }
                </h3>
                <p className="text-sm mt-1" style={{ color: "var(--text-2)" }}>
                  Here's your lead generation overview for today.
                </p>
              </div>

              <div className="grid grid-cols-2 xl:grid-cols-4 gap-3">
                <StatCard label="Leads Today"  value={leadsToday}  accent delay={0} />
                <StatCard label="With Website" value={withWeb}     delay={1} />
                <StatCard label="No Website"   value={noWeb}       delay={2} />
                <StatCard label="Emails Found" value={emailsToday} delay={3} />
              </div>

              {dailyLimit > 0 && (
                <div className="card p-5 animate-fade-up delay-4">
                  <div className="flex items-center justify-between mb-3">
                    <p className="label">Daily Usage</p>
                    <span className="mono text-xs" style={{ color: "var(--text-2)" }}>
                      {leadsToday.toLocaleString()} / {dailyLimit.toLocaleString()}
                    </span>
                  </div>
                  <div className="progress-bar">
                    <div className="progress-fill" style={{ width: `${usagePct}%` }} />
                  </div>
                  <p className="text-xs mt-2" style={{ color: "var(--text-3)" }}>
                    {remaining.toLocaleString()} leads remaining today · resets at midnight UTC
                  </p>
                </div>
              )}

              <div className="card p-5 animate-fade-up delay-4">
                <p className="label mb-3">Quick Actions</p>
                <div className="flex flex-wrap gap-2">
                  <button onClick={() => setActiveTab("Scrape Leads")} className="btn-primary">
                    ⚡ New Scrape Job
                  </button>
                  <button onClick={() => setActiveTab("History")} className="btn-ghost">
                    ◫ View History
                  </button>
                </div>
              </div>
            </div>
          )}

          {/* SCRAPE LEADS */}
          {activeTab === "Scrape Leads" && <ScrapeLeads plan={plan} />}

          {/* HISTORY */}
          {activeTab === "History" && <History />}

          {/* PLAN & BILLING */}
          {activeTab === "Plan & Billing" && (
            <div className="space-y-5 animate-fade-in">

              {plan?.plan_name && (
                <div className="card p-5">
                  <p className="label mb-4">Current Plan</p>
                  <div className="space-y-0">
                    {[
                      ["Plan",           plan.plan_name],
                      ["Status",         plan.subscription_status],
                      ["Daily limit",    (plan.daily_limit?.toLocaleString() ?? "Unlimited") + " leads"],
                      ["Monthly limit",  (plan.monthly_limit?.toLocaleString() ?? "Unlimited") + " leads"],
                      ["Cities / job",   plan.cities_per_job],
                      ["Email scraping", plan.email_scraping ? "Included" : "Not included"],
                    ].map(([label, val]) => (
                      <div key={label} className="flex justify-between items-center py-2.5"
                        style={{ borderBottom: "1px solid var(--border)" }}>
                        <span className="text-sm" style={{ color: "var(--text-2)" }}>{label}</span>
                        <span className="text-sm font-semibold mono" style={{ color: "var(--text)" }}>{val}</span>
                      </div>
                    ))}
                  </div>
                  <div className="pt-4">
                    <button onClick={handleManageBilling} disabled={portalLoading} className="btn-ghost text-sm">
                      {portalLoading ? "Opening…" : "Manage billing via Stripe →"}
                    </button>
                  </div>
                </div>
              )}

              {billingError && (
                <div className="p-3 rounded-lg text-sm" style={{
                  background: "rgba(255,77,106,0.08)",
                  border: "1px solid rgba(255,77,106,0.2)",
                  color: "var(--danger)"
                }}>{billingError}</div>
              )}

              <div>
                <p className="label mb-3">
                  {plan?.plan_name ? "Upgrade / Change Plan" : "Choose a Plan"}
                </p>
                {/* 4 column grid for plans */}
                <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-4">
                  {PLANS.map(p => (
                    <PricingCard
                      key={p.id}
                      name={p.name}
                      price={p.price}
                      priceId={p.priceId}
                      features={p.features}
                      popular={p.popular}
                      current={currentPlanId === p.id}
                      onBuy={handleBuyPlan}
                      loading={checkoutLoading}
                      isEnterprise={p.isEnterprise}
                    />
                  ))}
                </div>
              </div>

            </div>
          )}

          {/* SETTINGS */}
          {activeTab === "Settings" && (
            <div className="space-y-4 animate-fade-in">

              <div className="card p-5">
                <p className="label mb-4">Profile</p>
                <div className="space-y-4">
                  <div>
                    <label className="label">Full Name</label>
                    <div className="flex gap-2">
                      <input
                        value={nameInput}
                        onChange={e => setNameInput(e.target.value)}
                        onKeyDown={e => e.key === "Enter" && handleSaveName()}
                        placeholder="Your full name"
                        className="input flex-1"
                      />
                      <button
                        onClick={handleSaveName}
                        disabled={nameSaving || !nameInput.trim()}
                        className="btn-primary shrink-0"
                      >
                        {nameSaving ? "Saving…" : "Save"}
                      </button>
                    </div>
                    {nameMsg && (
                      <p className="text-xs mt-1.5" style={{
                        color: nameMsg.startsWith("Failed") ? "var(--danger)" : "var(--accent)"
                      }}>
                        {nameMsg}
                      </p>
                    )}
                  </div>
                  <div className="flex justify-between items-center py-2"
                    style={{ borderTop: "1px solid var(--border)" }}>
                    <span className="text-sm" style={{ color: "var(--text-2)" }}>Email</span>
                    <span className="text-sm mono" style={{ color: "var(--text)" }}>{profile?.email}</span>
                  </div>
                </div>
              </div>

              <div className="card p-5">
                <p className="label mb-4">Account</p>
                <div className="space-y-3">
                  <div>
                    <p className="text-sm mb-1" style={{ color: "var(--text-2)" }}>Password</p>
                    <button
                      onClick={async () => {
                        await supabase.auth.resetPasswordForEmail(profile?.email, {
                          redirectTo: `${window.location.origin}/reset-password`,
                        });
                        alert("Password reset link sent to " + profile?.email);
                      }}
                      className="btn-ghost text-sm"
                    >
                      Send password reset email
                    </button>
                  </div>
                  <div style={{ borderTop: "1px solid var(--border)", paddingTop: "12px" }}>
                    <button onClick={handleLogout} className="btn-danger text-sm">Sign out</button>
                  </div>
                </div>
              </div>

            </div>
          )}
        </main>
      </div>
    </div>
  );
}
