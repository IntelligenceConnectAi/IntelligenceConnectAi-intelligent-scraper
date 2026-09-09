import { useEffect, useState } from "react";
import { Eye, EyeOff } from "lucide-react";
import { supabase } from "../lib/supabase";
import { api } from "../lib/api";

const ROLE_LABELS = {
  account_owner: "Account Owner",
  client_admin: "Client Admin",
  client_member: "Client Member",
};

export default function AcceptInvitation({ onSuccess }) {
  const [token] = useState(() => new URLSearchParams(window.location.search).get("token") || "");
  const [checking, setChecking] = useState(true);
  const [preview, setPreview] = useState(null);

  const [fullName, setFullName] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [showPass, setShowPass] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!token) { setChecking(false); return; }
    api.previewInvitation(token)
      .then(setPreview)
      .catch(() => setPreview({ valid: false, reason: "Could not verify this invitation." }))
      .finally(() => setChecking(false));
  }, [token]);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError("");
    if (password !== confirm) { setError("Passwords do not match"); return; }
    if (password.length < 8) { setError("Password must be at least 8 characters"); return; }
    if (!fullName.trim()) { setError("Please enter your full name"); return; }

    setLoading(true);
    try {
      const data = await api.acceptInvitation(token, { password, full_name: fullName.trim() });
      const { error: sessionError } = await supabase.auth.setSession({
        access_token: data.access_token,
        refresh_token: data.refresh_token,
      });
      if (sessionError) throw sessionError;
      onSuccess?.();
    } catch (e2) {
      setError(e2.message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center px-4" style={{ background: "var(--bg)" }}>
      <div className="card-glass w-full max-w-sm p-8 animate-fade-up">
        <div className="flex items-center gap-2 mb-6">
          <div className="h-8 w-8 rounded-lg flex items-center justify-center font-bold text-sm"
            style={{ background: "var(--accent)", color: "#fff" }}>IS</div>
          <span className="text-sm font-semibold" style={{ color: "var(--text)" }}>Intelligent Scraper</span>
        </div>

        {checking ? (
          <p className="text-sm" style={{ color: "var(--text-2)" }}>Checking your invitation…</p>
        ) : !token || !preview?.valid ? (
          <>
            <h1 className="text-2xl font-bold mb-1" style={{ color: "var(--text)" }}>Invitation not available</h1>
            <p className="text-sm mb-6" style={{ color: "var(--text-2)" }}>
              {preview?.reason || "This invitation link is missing or invalid."}
            </p>
            <a href="/" className="btn-ghost w-full text-center block" style={{ textDecoration: "none" }}>← Back to sign in</a>
          </>
        ) : (
          <>
            <h1 className="text-2xl font-bold mb-1" style={{ color: "var(--text)" }}>Join {preview.organization_name}</h1>
            <div className="flex items-center gap-2 mb-5 p-3 rounded-lg"
              style={{ background: "var(--accent-dim)", border: "1px solid var(--accent-glow)" }}>
              <div className="h-6 w-6 rounded-md flex items-center justify-center text-xs font-bold"
                style={{ background: "var(--accent)", color: "#fff" }}>✓</div>
              <div>
                <p className="text-xs font-semibold" style={{ color: "var(--accent)" }}>
                  {ROLE_LABELS[preview.role] || preview.role}
                </p>
                <p className="text-xs" style={{ color: "var(--text-2)" }}>{preview.email}</p>
              </div>
            </div>

            <form onSubmit={handleSubmit} className="space-y-4">
              <div>
                <label className="label">Full Name</label>
                <input type="text" value={fullName} onChange={e => setFullName(e.target.value)}
                  required placeholder="Your full name" className="input" />
              </div>
              <div>
                <label className="label">Password</label>
                <div style={{ position: "relative" }}>
                  <input type={showPass ? "text" : "password"} value={password} onChange={e => setPassword(e.target.value)}
                    required placeholder="Min 8 characters" className="input" style={{ paddingRight: "40px" }} />
                  <button type="button" onClick={() => setShowPass(p => !p)}
                    style={{ position: "absolute", right: "12px", top: "50%", transform: "translateY(-50%)", background: "none", border: "none", cursor: "pointer", color: "var(--text-2)", display: "flex", alignItems: "center" }}>
                    {showPass ? <EyeOff size={16} /> : <Eye size={16} />}
                  </button>
                </div>
              </div>
              <div>
                <label className="label">Confirm Password</label>
                <input type={showPass ? "text" : "password"} value={confirm} onChange={e => setConfirm(e.target.value)}
                  required placeholder="Repeat password" className="input" />
              </div>

              {error && <p className="text-xs" style={{ color: "var(--danger)" }}>{error}</p>}

              <button type="submit" disabled={loading} className="btn-primary w-full">
                {loading
                  ? <span className="flex items-center justify-center gap-2">
                      <span className="h-3.5 w-3.5 rounded-full border-2 border-white/30 border-t-white animate-spin" />
                      Joining…
                    </span>
                  : "Join Organization →"}
              </button>
            </form>
          </>
        )}
      </div>
    </div>
  );
}
