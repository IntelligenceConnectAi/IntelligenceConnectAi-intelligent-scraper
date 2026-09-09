import { useEffect, useState } from "react";
import { supabase } from "./lib/supabase";
import { api } from "./lib/api";
import Signup from "./components/Signup";
import AcceptInvitation from "./components/AcceptInvitation";
import ClientApp from "./ClientApp";
import AdminApp from "./AdminApp";

// ═══════════════════════════════════════════════════════════════
// Phase 8: trimmed to what's genuinely shared across both shells — session
// listener, theme, the /signup and /join public routes, and the login/forgot
// screens. Everything post-login now lives in ClientApp.jsx (moved verbatim)
// or AdminApp.jsx (new), chosen by platform_role + the ?view= toggle below.
// ═══════════════════════════════════════════════════════════════
export default function App() {

  // ── Auth ──
  const [session, setSession]         = useState(null);
  const [authLoading, setAuthLoading] = useState(true);

  // ── Login form ──
  const [view, setView]               = useState("login");
  const [email, setEmail]             = useState("");
  const [password, setPassword]       = useState("");
  const [formLoading, setFormLoading] = useState(false);
  const [formMsg, setFormMsg]         = useState("");
  const [isError, setIsError]         = useState(false);

  // ── Which shell to render (admin vs client) — a gate-keeping profile fetch,
  // independent of ClientApp's own profile/plan state ──
  const [gateProfile, setGateProfile]   = useState(null);
  const [gateLoading, setGateLoading]   = useState(false);
  const [viewMode, setViewMode]         = useState(
    () => new URLSearchParams(window.location.search).get("view")
  );

  // ── Theme ── (light/dark, applied via the `data-theme` attribute so CSS
  // owns the whole palette — see index.html's inline script for the
  // matching FOUC guard that sets this attribute before first paint)
  const [theme, setTheme] = useState(
    () => localStorage.getItem("theme") === "light" ? "light" : "dark"
  );
  useEffect(() => {
    document.documentElement.setAttribute("data-theme", theme);
    localStorage.setItem("theme", theme);
  }, [theme]);
  const toggleTheme = () => setTheme(t => t === "light" ? "dark" : "light");

  // ── Session ──
  useEffect(() => {
    supabase.auth.getSession().then(({ data: { session } }) => {
      setSession(session); setAuthLoading(false);
    });
    const { data: sub } = supabase.auth.onAuthStateChange((_e, s) => setSession(s));
    return () => sub.subscription.unsubscribe();
  }, []);

  // ── Gate-keeping profile fetch — learns platform_role once per session,
  // not on every navigation (see AdminApp/ClientApp split rationale) ──
  useEffect(() => {
    if (!session) { setGateProfile(null); return; }
    setGateLoading(true);
    api.me()
      .then(setGateProfile)
      .catch(() => setGateProfile(null))
      .finally(() => setGateLoading(false));
  }, [session]);

  // ── Handlers ──
  const handleLogin = async (e) => {
    e.preventDefault(); setFormLoading(true); setFormMsg("");
    try {
      const { error } = await supabase.auth.signInWithPassword({ email, password });
      if (error) throw error;
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

  const handleLogout = async () => {
    await supabase.auth.signOut();
    setFormMsg(""); setIsError(false); setView("login"); setPassword("");
  };

  const setUrlView = (mode) => {
    const url = new URL(window.location.href);
    if (mode) url.searchParams.set("view", mode);
    else url.searchParams.delete("view");
    window.history.replaceState({}, "", url);
    setViewMode(mode);
  };

  // ── Auth guards ──
  const isSignupRoute = window.location.pathname === "/signup";
  if (isSignupRoute && !session) {
    return <Signup onSuccess={() => { window.location.href = "/"; }} />;
  }

  const isJoinRoute = window.location.pathname === "/join";
  if (isJoinRoute && !session) {
    return <AcceptInvitation onSuccess={() => { window.location.href = "/"; }} />;
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

  if (gateLoading || !gateProfile) return (
    <div className="flex min-h-screen items-center justify-center" style={{ background: "var(--bg)" }}>
      <div className="flex flex-col items-center gap-3">
        <div className="h-8 w-8 rounded-full border-2 border-[var(--accent)] border-t-transparent animate-spin" />
        <p className="text-sm muted-text">Loading…</p>
      </div>
    </div>
  );

  const isAdminRole = gateProfile.platform_role === "admin" || gateProfile.platform_role === "super_admin";

  if (isAdminRole && viewMode !== "client") {
    return (
      <AdminApp
        onLogout={handleLogout}
        onSwitchToClientView={() => setUrlView("client")}
        theme={theme}
        onToggleTheme={toggleTheme}
      />
    );
  }

  return (
    <ClientApp
      session={session} onLogout={handleLogout}
      onSwitchToAdminView={isAdminRole ? () => setUrlView(null) : null}
      theme={theme}
      onToggleTheme={toggleTheme}
    />
  );
}
