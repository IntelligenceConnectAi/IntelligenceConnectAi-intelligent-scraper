import { useEffect, useState } from "react";
import { Eye, EyeOff } from "lucide-react";
import { supabase } from "../lib/supabase";

const API_BASE = import.meta.env.VITE_API_BASE_URL || "http://127.0.0.1:8000";

const PLAN_LABELS = {
  starter: { name: "Starter", price: "$29/mo", color: "#555" },
  pro:     { name: "Pro",     price: "$79/mo", color: "#19DAB3" },
  elite:   { name: "Elite",   price: "$199/mo", color: "#2176d9" },
};

export default function Signup({ onSuccess }) {
  const [email, setEmail]         = useState("");
  const [password, setPassword]   = useState("");
  const [confirm, setConfirm]     = useState("");
  const [name, setName]           = useState("");
  const [loading, setLoading]     = useState(false);
  const [checking, setChecking]   = useState(false);
  const [error, setError]         = useState("");
  const [planId, setPlanId]       = useState(null);
  const [step, setStep]           = useState("email"); // email | details
  const [showPass, setShowPass]   = useState(false);
  const [showConfirm, setShowConfirm] = useState(false);

  // Pre-fill email from URL param
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const urlEmail = params.get("email");
    if (urlEmail) {
      setEmail(urlEmail);
      checkPayment(urlEmail);
    }
  }, []);

  const checkPayment = async (emailToCheck) => {
    if (!emailToCheck) return;
    setChecking(true); setError("");
    try {
      const res = await fetch(
        `${API_BASE}/auth/check-payment?email=${encodeURIComponent(emailToCheck)}`
      );
      const data = await res.json();
      if (data.paid) {
        setPlanId(data.plan_id);
        setStep("details");
      } else {
        setError("No payment found for this email. Please purchase a plan first.");
      }
    } catch {
      setError("Network error. Please try again.");
    } finally {
      setChecking(false);
    }
  };

  const handleEmailStep = async (e) => {
    e.preventDefault();
    await checkPayment(email);
  };

  const handleRegister = async (e) => {
    e.preventDefault();
    setError("");

    if (password !== confirm) {
      setError("Passwords do not match");
      return;
    }
    if (password.length < 8) {
      setError("Password must be at least 8 characters");
      return;
    }
    if (!name.trim()) {
      setError("Please enter your full name");
      return;
    }

    setLoading(true);
    try {
      const res = await fetch(`${API_BASE}/auth/register`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email, password, full_name: name }),
      });

      const data = await res.json();

      if (!res.ok) {
        throw new Error(data.detail || "Registration failed");
      }

      // Set Supabase session from tokens
      const { error: sessionError } = await supabase.auth.setSession({
        access_token:  data.access_token,
        refresh_token: data.refresh_token,
      });

      if (sessionError) throw sessionError;

      onSuccess?.();

    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  };

  const plan = planId ? PLAN_LABELS[planId] : null;

  return (
    <div className="min-h-screen flex items-center justify-center px-4"
      style={{ background: "var(--bg)" }}>

      <div className="card-glass w-full max-w-sm p-8 animate-fade-up">

        {/* Logo */}
        <div className="flex items-center gap-2 mb-6">
          <div className="h-8 w-8 rounded-lg flex items-center justify-center font-bold text-sm"
            style={{ background: "var(--accent)", color: "#fff" }}>IS</div>
          <span className="text-sm font-semibold" style={{ color: "var(--text)" }}>
            Intelligent Scraper
          </span>
        </div>

        {step === "email" ? (
          <>
            <h1 className="text-2xl font-bold mb-1" style={{ color: "var(--text)" }}>
              Complete your account
            </h1>
            <p className="text-sm mb-6" style={{ color: "var(--text-2)" }}>
              Enter the email you used during payment
            </p>

            <form onSubmit={handleEmailStep} className="space-y-4">
              <div>
                <label className="label">Email</label>
                <input
                  type="email"
                  value={email}
                  onChange={e => setEmail(e.target.value)}
                  required
                  placeholder="you@example.com"
                  className="input"
                />
              </div>
              {error && (
                <p className="text-xs" style={{ color: "var(--danger)" }}>{error}</p>
              )}
              <button type="submit" disabled={checking} className="btn-primary w-full">
                {checking
                  ? <span className="flex items-center justify-center gap-2">
                      <span className="h-3.5 w-3.5 rounded-full border-2 border-white/30 border-t-white animate-spin"/>
                      Checking…
                    </span>
                  : "Continue →"}
              </button>
            </form>

            <p className="text-center text-xs mt-4" style={{ color: "var(--text-3)" }}>
              Already have an account?{" "}
              <a href="/" className="font-medium" style={{ color: "var(--accent)" }}>
                Sign in
              </a>
            </p>
          </>
        ) : (
          <>
            <h1 className="text-2xl font-bold mb-1" style={{ color: "var(--text)" }}>
              Set up your account
            </h1>

            {/* Plan badge */}
            {plan && (
              <div className="flex items-center gap-2 mb-5 p-3 rounded-lg"
                style={{ background: "var(--accent-dim)", border: "1px solid rgba(25,218,179,0.2)" }}>
                <div className="h-6 w-6 rounded-md flex items-center justify-center text-xs font-bold"
                  style={{ background: "var(--accent)", color: "#fff" }}>✓</div>
                <div>
                  <p className="text-xs font-semibold" style={{ color: "var(--accent)" }}>
                    {plan.name} Plan — {plan.price}
                  </p>
                  <p className="text-xs" style={{ color: "var(--text-2)" }}>{email}</p>
                </div>
              </div>
            )}

            <form onSubmit={handleRegister} className="space-y-4">
              <div>
                <label className="label">Full Name</label>
                <input
                  type="text"
                  value={name}
                  onChange={e => setName(e.target.value)}
                  required
                  placeholder="Your full name"
                  className="input"
                />
              </div>
              <div>
                <label className="label">Password</label>
                <div style={{ position: "relative" }}>
                  <input
                    type={showPass ? "text" : "password"}
                    value={password}
                    onChange={e => setPassword(e.target.value)}
                    required
                    placeholder="Min 8 characters"
                    className="input"
                    style={{ paddingRight: "40px" }}
                  />
                  <button type="button" onClick={() => setShowPass(p => !p)}
                    style={{ position:"absolute", right:"12px", top:"50%", transform:"translateY(-50%)", background:"none", border:"none", cursor:"pointer", color:"var(--text-2)", display:"flex", alignItems:"center" }}>
                    {showPass ? <EyeOff size={16}/> : <Eye size={16}/>}
                  </button>
                </div>
              </div>
              <div>
                <label className="label">Confirm Password</label>
                <div style={{ position: "relative" }}>
                  <input
                    type={showConfirm ? "text" : "password"}
                    value={confirm}
                    onChange={e => setConfirm(e.target.value)}
                    required
                    placeholder="Repeat password"
                    className="input"
                    style={{ paddingRight: "40px" }}
                  />
                  <button type="button" onClick={() => setShowConfirm(p => !p)}
                    style={{ position:"absolute", right:"12px", top:"50%", transform:"translateY(-50%)", background:"none", border:"none", cursor:"pointer", color:"var(--text-2)", display:"flex", alignItems:"center" }}>
                    {showConfirm ? <EyeOff size={16}/> : <Eye size={16}/>}
                  </button>
                </div>
              </div>

              {error && (
                <p className="text-xs" style={{ color: "var(--danger)" }}>{error}</p>
              )}

              <button type="submit" disabled={loading} className="btn-primary w-full">
                {loading
                  ? <span className="flex items-center justify-center gap-2">
                      <span className="h-3.5 w-3.5 rounded-full border-2 border-white/30 border-t-white animate-spin"/>
                      Creating account…
                    </span>
                  : "Create Account & Login →"}
              </button>
            </form>

            <button
              onClick={() => { setStep("email"); setError(""); setPlanId(null); }}
              className="w-full text-center text-xs mt-3 transition"
              style={{ color: "var(--text-3)" }}>
              ← Use a different email
            </button>
          </>
        )}
      </div>
    </div>
  );
}
