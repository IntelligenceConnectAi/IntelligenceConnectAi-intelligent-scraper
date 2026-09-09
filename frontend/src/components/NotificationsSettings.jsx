import { useEffect, useState } from "react";
import { api } from "../lib/api";

const CATEGORIES = [
  { key: "business_updates", label: "Business Leads updates", description: "Submitted, completed, failed, and cancelled requests." },
  { key: "people_updates", label: "People Leads updates", description: "Submitted, needs information, and completed requests." },
  { key: "billing_limits", label: "Billing & limits", description: "Subscription renewals, payment issues, and usage limits." },
  { key: "team", label: "Team", description: "New team members joining your organization." },
  { key: "support", label: "Support", description: "Replies to your support tickets." },
];

function Toggle({ checked, onChange, disabled }) {
  return (
    <button type="button" role="switch" aria-checked={checked} disabled={disabled}
      onClick={() => onChange(!checked)}
      className="relative shrink-0 transition disabled:opacity-50"
      style={{
        width: 40, height: 22, borderRadius: 999,
        background: checked ? "var(--accent)" : "var(--border)",
      }}>
      <span className="absolute rounded-full transition-transform" style={{
        width: 16, height: 16, top: 3, left: 3, background: "#fff",
        transform: checked ? "translateX(18px)" : "translateX(0)",
      }} />
    </button>
  );
}

export default function NotificationsSettings() {
  const [muted, setMuted] = useState([]);
  const [emailEnabled, setEmailEnabled] = useState(true);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    api.getNotificationPreferences()
      .then(res => { setMuted(res.muted_categories); setEmailEnabled(res.email_enabled); })
      .catch(e => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  const toggle = async (key, enabled) => {
    const next = enabled ? muted.filter(c => c !== key) : [...muted, key];
    setMuted(next);
    setSaving(key);
    try {
      await api.updateNotificationPreferences({ muted_categories: next, email_enabled: emailEnabled });
    } catch (e) {
      setError(e.message);
      setMuted(muted); // revert on failure
    } finally {
      setSaving("");
    }
  };

  const toggleEmail = async (enabled) => {
    setEmailEnabled(enabled);
    setSaving("email");
    try {
      await api.updateNotificationPreferences({ muted_categories: muted, email_enabled: enabled });
    } catch (e) {
      setError(e.message);
      setEmailEnabled(!enabled); // revert on failure
    } finally {
      setSaving("");
    }
  };

  if (loading) return (
    <div className="card p-10 text-center animate-soft-pulse">
      <p className="text-sm" style={{ color: "var(--text-3)" }}>Loading notification preferences…</p>
    </div>
  );

  return (
    <div className="space-y-5 animate-fade-in">
      {error && (
        <p className="text-xs" style={{ color: "var(--danger)" }}>{error}</p>
      )}

      <div className="card p-5">
        <div className="flex items-center justify-between">
          <div>
            <p className="label mb-1">Email notifications</p>
            <p className="text-xs" style={{ color: "var(--text-3)" }}>
              Also send an email for the categories below. In-app notifications always stay on.
            </p>
          </div>
          <Toggle checked={emailEnabled} disabled={saving === "email"} onChange={toggleEmail} />
        </div>
      </div>

      <div className="card p-5">
        <p className="label mb-1">Notification Categories</p>
        <p className="text-xs mb-4" style={{ color: "var(--text-3)" }}>
          Choose which notifications you want to receive. Categories below control both in-app and email delivery when email is on.
        </p>
        <div className="space-y-0">
          {CATEGORIES.map(c => (
            <div key={c.key} className="flex items-center justify-between py-3" style={{ borderTop: "1px solid var(--border)" }}>
              <div>
                <p className="text-sm font-medium" style={{ color: "var(--text)" }}>{c.label}</p>
                <p className="text-xs mt-0.5" style={{ color: "var(--text-3)" }}>{c.description}</p>
              </div>
              <Toggle checked={!muted.includes(c.key)} disabled={saving === c.key} onChange={enabled => toggle(c.key, enabled)} />
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
