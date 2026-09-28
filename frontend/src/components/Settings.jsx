import { useEffect, useState } from "react";
import { CreditCard, CheckCircle2, XCircle, ExternalLink } from "lucide-react";
import { supabase } from "../lib/supabase";
import { api } from "../lib/api";
import TeamSection from "./TeamSection";
import NotificationsSettings from "./NotificationsSettings";
import IntegrationsSettings from "./IntegrationsSettings";
import UsageRadialChart from "./charts/UsageRadialChart";

// Nominal monthly cycle length for the renewal progress meter — Stripe's real
// cycles vary 28-31 days depending on start date; this is an ambient visual,
// not a claimed exact fact (the text label next to it states the real days-left).
const CYCLE_LENGTH_DAYS = 30;

function fmtDate(iso) {
  if (!iso) return "—";
  return new Date(iso).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
}

function subscriptionStatusMeta(status, cancelAtPeriodEnd) {
  if (cancelAtPeriodEnd) return { label: "Canceling", badgeClass: "badge-warning", tone: "warning" };
  switch (status) {
    case "active":   return { label: "Active", badgeClass: "badge-accent", tone: "accent" };
    case "trialing": return { label: "Trial", badgeClass: "badge-accent", tone: "accent" };
    case "past_due":
    case "unpaid":
    case "incomplete": return { label: "Payment issue", badgeClass: "badge-danger", tone: "danger" };
    case "canceled": return { label: "Canceled", badgeClass: "badge-muted", tone: "muted" };
    default: return { label: status || "Unknown", badgeClass: "badge-muted", tone: "muted" };
  }
}

function invoiceStatusBadge(status) {
  if (status === "paid") return "badge-accent";
  if (status === "open") return "badge-warning";
  if (status === "void" || status === "uncollectible") return "badge-danger";
  return "badge-muted";
}

// ── Plan price IDs from env ─────────────────────────────────────
const PRICE_IDS = {
  starter:    import.meta.env.VITE_STRIPE_STARTER_PRICE_ID    || "",
  pro:        import.meta.env.VITE_STRIPE_PRO_PRICE_ID        || "",
  elite:      import.meta.env.VITE_STRIPE_ELITE_PRICE_ID      || "",
  enterprise: import.meta.env.VITE_STRIPE_ENTERPRISE_PRICE_ID || "",
};

// NOTE: `id` deliberately stays the legacy internal identifier (matches
// plans.id / STRIPE_*_PRICE_ID env vars in the backend) — only `name` and
// `features` reflect the current user-facing rebrand. id="pro" is branded
// "Growth"; id="elite" is branded "Pro". See migrations/0012_lead_topups.sql.
const PLANS = [
  {
    id: "starter", name: "Starter", price: 49, priceId: PRICE_IDS.starter,
    features: ["10,000 leads/month", "333 leads per day", "10 cities per job", "Phone, address, website", "7-day history"],
    popular: false,
  },
  {
    id: "pro", name: "Growth", price: 197, priceId: PRICE_IDS.pro,
    features: ["25,000 leads/month", "833 leads per day", "30 cities per job", "Email scraping included", "30-day history"],
    popular: true,
  },
  {
    id: "elite", name: "Pro", price: 397, priceId: PRICE_IDS.elite,
    features: ["50,000 leads/month", "1,667 leads per day", "100 cities per job", "Email scraping included", "365-day history + API access"],
    popular: false,
  },
  {
    id: "enterprise", name: "Enterprise", price: 1500, priceId: PRICE_IDS.enterprise,
    features: ["125,000+ leads/month", "4,167+ leads per day", "Unlimited cities per job", "Email scraping included", "Dedicated support + custom SLA"],
    popular: false, isEnterprise: true,
  },
];

// Additional-records top-ups: flat $0.025/record, sold in fixed package sizes.
// Eligibility (a plan may buy a package up to 100% of its own monthly limit)
// is computed at render time from the caller's plan.monthly_limit, not
// hardcoded per package — see the "available to" column in the pricing
// reference this was built from.
const TOPUP_PACKAGES = [1000, 2500, 5000, 10000, 25000, 50000];
const TOPUP_PRICE_PER_RECORD = 0.025;

function PricingCard({ name, price, priceId, features, popular, current, onBuy, loading, isEnterprise }) {
  return (
    <div
      className={`dashboard-panel is-interactive relative ${popular ? "ring-2 ring-[var(--accent)]" : ""}`}
      style={{ padding: popular ? "2rem 1.25rem 1.25rem" : "1.25rem" }}
    >
      {popular && (
        <div style={{ textAlign: "center", marginBottom: "0.75rem", marginTop: "-0.5rem" }}>
          <span className="badge badge-accent text-xs px-3">Most Popular</span>
        </div>
      )}
      <div className="flex items-baseline justify-between mb-1">
        <p className="font-semibold text-sm" style={{ color: "var(--text-primary)" }}>{name}</p>
        {current && <span className="badge badge-accent text-xs">Current</span>}
      </div>
      <p className="text-2xl font-bold mono mb-3" style={{ color: popular ? "var(--accent)" : "var(--text-primary)" }}>
        ${price}{isEnterprise ? "+" : ""}<span className="text-sm font-normal" style={{ color: "var(--text-muted)" }}>/mo</span>
      </p>
      <ul className="space-y-1.5 mb-4">
        {features.map((f, i) => (
          <li key={i} className="flex items-center gap-2 text-xs" style={{ color: "var(--text-secondary)" }}>
            <span style={{ color: "var(--accent)" }}>✓</span> {f}
          </li>
        ))}
      </ul>
      {current ? (
        <button disabled className="btn-ghost w-full text-sm opacity-50 cursor-not-allowed">Active plan</button>
      ) : isEnterprise ? (
        <a href="mailto:support@intelligenceconnectai.com?subject=Enterprise Plan Inquiry"
          className="btn-primary w-full text-sm text-center block" style={{ textDecoration: "none" }}>
          Contact Sales →
        </a>
      ) : (
        <button onClick={() => onBuy(priceId)} disabled={loading}
          className={popular ? "btn-primary w-full text-sm" : "btn-ghost w-full text-sm"}>
          {loading ? "Redirecting…" : `Get ${name} →`}
        </button>
      )}
    </div>
  );
}

function ProfileSection({ profile, onProfileUpdated, onLogout }) {
  const [nameInput, setNameInput]   = useState(profile?.full_name || "");
  const [nameSaving, setNameSaving] = useState(false);
  const [nameMsg, setNameMsg]       = useState("");

  useEffect(() => { setNameInput(profile?.full_name || ""); }, [profile?.full_name]);

  const handleSaveName = async () => {
    if (!nameInput.trim()) return;
    setNameSaving(true); setNameMsg("");
    try {
      await api.updateProfile({ full_name: nameInput.trim() });
      onProfileUpdated?.({ full_name: nameInput.trim() });
      setNameMsg("Saved!");
      setTimeout(() => setNameMsg(""), 2500);
    } catch (e) {
      setNameMsg("Failed: " + e.message);
    } finally {
      setNameSaving(false);
    }
  };

  return (
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
              <button onClick={handleSaveName} disabled={nameSaving || !nameInput.trim()} className="btn-primary shrink-0">
                {nameSaving ? "Saving…" : "Save"}
              </button>
            </div>
            {nameMsg && (
              <p className="text-xs mt-1.5" style={{ color: nameMsg.startsWith("Failed") ? "var(--danger)" : "var(--accent)" }}>
                {nameMsg}
              </p>
            )}
          </div>
          <div className="flex justify-between items-center py-2" style={{ borderTop: "1px solid var(--border)" }}>
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
            <button onClick={onLogout} className="btn-danger text-sm">Sign out</button>
          </div>
        </div>
      </div>
    </div>
  );
}

function BillingSection({ plan, theme }) {
  const [checkoutLoading, setCheckoutLoading] = useState(false);
  const [portalLoading, setPortalLoading]     = useState(false);
  const [topupLoading, setTopupLoading]       = useState(null); // holds the quantity being purchased, or null
  const [billingError, setBillingError]       = useState("");
  const [dashboard, setDashboard]             = useState(null);
  const [invoices, setInvoices]               = useState([]);
  const [paymentMethod, setPaymentMethod]     = useState(null);
  const [myRole, setMyRole]                   = useState(null);

  useEffect(() => {
    Promise.all([
      api.clientDashboard().catch(() => null),
      api.billingInvoices().catch(() => []),
      api.billingPaymentMethod().catch(() => null),
      api.getOrganization().catch(() => null),
    ]).then(([d, inv, pm, org]) => {
      setDashboard(d); setInvoices(inv); setPaymentMethod(pm); setMyRole(org?.my_role || null);
    });
  }, []);

  const isOwner = myRole === "account_owner";
  const currentPlanId = plan?.plan_id || null;

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

  const handleBuyTopup = async (quantity) => {
    setTopupLoading(quantity); setBillingError("");
    try {
      const res = await api.createTopupCheckout(quantity, window.location.href, window.location.href);
      if (res.checkout_url) window.location.href = res.checkout_url;
      else setBillingError("No checkout URL received");
    } catch (e) {
      setBillingError(e.message);
    } finally {
      setTopupLoading(null);
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

  const statusMeta = subscriptionStatusMeta(plan?.subscription_status, plan?.cancel_at_period_end);
  const daysUntilReset = dashboard?.days_until_reset;
  const cyclePct = daysUntilReset != null
    ? Math.min(Math.max(Math.round(((CYCLE_LENGTH_DAYS - daysUntilReset) / CYCLE_LENGTH_DAYS) * 100), 0), 100)
    : null;

  return (
    <div className="space-y-5 animate-fade-in">
      {plan?.plan_name ? (
        <>
          {/* Hero: current plan + usage */}
          <div className="dashboard-grid">
            <div className="span-8 span-xl-8">
              <div className="dashboard-panel dashboard-panel--hero">
                <div className="flex items-start justify-between flex-wrap gap-3">
                  <div>
                    <p className="dashboard-panel-title" style={{ marginBottom: 4 }}>Current plan</p>
                    <p style={{
                      fontFamily: "var(--font-display)", fontSize: 28, fontWeight: 700,
                      color: "var(--text-primary)", letterSpacing: "-0.02em",
                    }}>
                      {plan.plan_name}
                      {plan.price_monthly != null && (
                        <span style={{ fontSize: 15, fontWeight: 500, color: "var(--text-muted)", marginLeft: 10 }}>
                          ${Number(plan.price_monthly)}/mo
                        </span>
                      )}
                    </p>
                  </div>
                  <span className={`badge ${statusMeta.badgeClass}`}>{statusMeta.label}</span>
                </div>

                <p className="text-sm mt-2" style={{ color: statusMeta.tone === "warning" ? "var(--warning)" : "var(--text-secondary)" }}>
                  {plan.cancel_at_period_end
                    ? `Access ends ${fmtDate(dashboard?.package_renewal_date)} — no further charges`
                    : dashboard?.package_renewal_date
                      ? `Renews ${fmtDate(dashboard.package_renewal_date)}${daysUntilReset != null ? ` · in ${daysUntilReset} day${daysUntilReset === 1 ? "" : "s"}` : ""}`
                      : "—"}
                </p>

                {cyclePct != null && (
                  <div style={{ marginTop: 10, height: 4, borderRadius: 999, background: "var(--border-soft)", overflow: "hidden" }}>
                    <div style={{
                      width: `${cyclePct}%`, height: "100%", borderRadius: 999,
                      background: statusMeta.tone === "warning" ? "var(--warning)" : "var(--accent)",
                      transition: "width 400ms ease",
                    }} />
                  </div>
                )}

                <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 mt-5 pt-5" style={{ borderTop: "1px solid var(--border-soft)" }}>
                  <div>
                    <p className="text-xs" style={{ color: "var(--text-muted)" }}>Daily limit</p>
                    <p className="text-sm mono font-semibold mt-1" style={{ color: "var(--text-primary)" }}>
                      {plan.daily_limit != null ? plan.daily_limit.toLocaleString() : "Unlimited"}
                    </p>
                  </div>
                  <div>
                    <p className="text-xs" style={{ color: "var(--text-muted)" }}>Cities / job</p>
                    <p className="text-sm mono font-semibold mt-1" style={{ color: "var(--text-primary)" }}>{plan.cities_per_job ?? "—"}</p>
                  </div>
                  <div>
                    <p className="text-xs" style={{ color: "var(--text-muted)" }}>Email scraping</p>
                    <p className="text-sm font-semibold mt-1 flex items-center gap-1.5"
                      style={{ color: plan.email_scraping ? "var(--accent)" : "var(--text-muted)" }}>
                      {plan.email_scraping ? <CheckCircle2 size={14} /> : <XCircle size={14} />}
                      {plan.email_scraping ? "Included" : "Not included"}
                    </p>
                  </div>
                  <div>
                    <p className="text-xs" style={{ color: "var(--text-muted)" }}>API access</p>
                    <p className="text-sm font-semibold mt-1 flex items-center gap-1.5"
                      style={{ color: plan.api_access ? "var(--accent)" : "var(--text-muted)" }}>
                      {plan.api_access ? <CheckCircle2 size={14} /> : <XCircle size={14} />}
                      {plan.api_access ? "Included" : "Not included"}
                    </p>
                  </div>
                </div>

                {isOwner ? (
                  <div className="flex items-center gap-2 mt-5">
                    <button onClick={handleManageBilling} disabled={portalLoading} className="btn-primary text-sm flex items-center gap-1.5">
                      {portalLoading ? "Opening…" : "Manage billing"}
                      {!portalLoading && <ExternalLink size={14} />}
                    </button>
                    <a href="#available-plans" className="btn-ghost text-sm">Change plan</a>
                  </div>
                ) : (
                  <p className="text-xs mt-5" style={{ color: "var(--text-muted)" }}>
                    Contact your account owner to manage billing or change your plan.
                  </p>
                )}
              </div>
            </div>

            <div className="span-4 span-xl-4">
              <UsageRadialChart
                key={theme}
                used={dashboard?.leads_used_period ?? 0}
                remaining={dashboard?.leads_remaining_period ?? 0}
                limit={dashboard?.effective_monthly_limit ?? plan.monthly_limit ?? 0}
                renewalDate={dashboard?.package_renewal_date}
                daysUntilReset={dashboard?.days_until_reset}
                processingCount={dashboard?.leads_processing}
              />
              {dashboard?.effective_monthly_limit > (plan.monthly_limit ?? 0) && (
                <p className="text-xs mt-2 text-center" style={{ color: "var(--accent)" }}>
                  +{(dashboard.effective_monthly_limit - plan.monthly_limit).toLocaleString()} extra this period
                </p>
              )}
            </div>
          </div>

          {/* Additional records top-up */}
          {isOwner && currentPlanId && currentPlanId !== "enterprise" && (
            <div className="dashboard-grid">
              <div className="span-12">
                <div className="dashboard-panel" style={{ padding: 0, overflow: "hidden" }}>
                  <div className="px-5 py-3.5" style={{ borderBottom: "1px solid var(--border-soft)" }}>
                    <p className="section-title" style={{ margin: 0 }}>Buy additional records</p>
                    <p className="text-xs mt-1" style={{ color: "var(--text-muted)" }}>
                      Need more capacity this period? Top up instantly — added records apply immediately and expire at your next renewal.
                    </p>
                  </div>
                  <div className="overflow-x-auto">
                    <table className="w-full">
                      <thead>
                        <tr style={{ borderBottom: "1px solid var(--border-soft)" }}>
                          {["Additional records", "You pay", ""].map(h => (
                            <th key={h} className="px-4 py-3 text-left text-xs font-medium tracking-wider uppercase" style={{ color: "var(--text-muted)" }}>{h}</th>
                          ))}
                        </tr>
                      </thead>
                      <tbody>
                        {TOPUP_PACKAGES.map((qty, i) => {
                          const eligible = qty <= (plan.monthly_limit ?? 0);
                          const price = (qty * TOPUP_PRICE_PER_RECORD).toFixed(2);
                          return (
                            <tr key={qty} style={{ borderTop: i > 0 ? "1px solid var(--border-soft)" : "none", opacity: eligible ? 1 : 0.4 }}>
                              <td className="px-4 py-3 text-sm mono font-semibold" style={{ color: "var(--text-primary)" }}>+{qty.toLocaleString()}</td>
                              <td className="px-4 py-3 text-sm mono" style={{ color: "var(--text-secondary)" }}>${price}</td>
                              <td className="px-4 py-3 text-right">
                                {eligible ? (
                                  <button onClick={() => handleBuyTopup(qty)} disabled={topupLoading !== null}
                                    className="btn-ghost text-xs">
                                    {topupLoading === qty ? "Redirecting…" : "Buy →"}
                                  </button>
                                ) : (
                                  <span className="text-xs" style={{ color: "var(--text-muted)" }}>Requires a higher plan</span>
                                )}
                              </td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  </div>
                  <p className="text-xs px-4 py-3" style={{ color: "var(--text-muted)", borderTop: "1px solid var(--border-soft)" }}>
                    Additional capacity is limited to up to 100% more than your plan's included amount. If you consistently need more, consider upgrading your plan instead.
                  </p>
                </div>
              </div>
            </div>
          )}

          {/* Payment method */}
          <div className="dashboard-grid">
            <div className="span-12">
              <div className="dashboard-panel">
                <p className="dashboard-panel-title">Payment method</p>
                {paymentMethod?.has_payment_method ? (
                  <div className="flex items-center justify-between flex-wrap gap-3">
                    <div className="flex items-center gap-3">
                      <div style={{
                        width: 38, height: 38, borderRadius: 10, display: "grid", placeItems: "center",
                        background: "var(--accent-dim)", border: "1px solid var(--accent-glow)",
                      }}>
                        <CreditCard size={18} style={{ color: "var(--accent)" }} />
                      </div>
                      <div>
                        <p className="text-sm mono font-semibold" style={{ color: "var(--text-primary)" }}>
                          {paymentMethod.brand?.toUpperCase()} •••• {paymentMethod.last4}
                        </p>
                        <p className="text-xs" style={{ color: "var(--text-muted)" }}>
                          Expires {String(paymentMethod.exp_month).padStart(2, "0")}/{paymentMethod.exp_year}
                        </p>
                      </div>
                    </div>
                    {isOwner && (
                      <button onClick={handleManageBilling} disabled={portalLoading} className="btn-ghost text-xs">Update →</button>
                    )}
                  </div>
                ) : (
                  <div className="flex items-center justify-between flex-wrap gap-3">
                    <p className="text-sm" style={{ color: "var(--text-muted)" }}>No payment method on file.</p>
                    {isOwner && (
                      <button onClick={handleManageBilling} disabled={portalLoading} className="btn-ghost text-xs">Add payment method →</button>
                    )}
                  </div>
                )}
              </div>
            </div>
          </div>
        </>
      ) : (
        <div className="dashboard-panel">
          <p className="text-sm" style={{ color: "var(--text-secondary)" }}>You don't have an active plan yet.</p>
        </div>
      )}

      {billingError && (
        <div className="alert-danger">{billingError}</div>
      )}

      {/* Invoice history */}
      <div className="dashboard-grid">
        <div className="span-12">
          <div className="dashboard-panel" style={{ padding: 0, overflow: "hidden" }}>
            <div className="px-5 py-3.5" style={{ borderBottom: "1px solid var(--border-soft)" }}>
              <p className="section-title" style={{ margin: 0 }}>Invoice history</p>
            </div>
            {invoices.length === 0 ? (
              <p className="text-sm p-5" style={{ color: "var(--text-muted)" }}>
                No invoices yet — your first invoice will appear here after your next payment.
              </p>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full">
                  <thead>
                    <tr style={{ borderBottom: "1px solid var(--border-soft)" }}>
                      {["Date", "Amount", "Status", ""].map(h => (
                        <th key={h} className="px-4 py-3 text-left text-xs font-medium tracking-wider uppercase" style={{ color: "var(--text-muted)" }}>{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {invoices.map((inv, i) => (
                      <tr key={inv.id} style={{ borderTop: i > 0 ? "1px solid var(--border-soft)" : "none" }}>
                        <td className="px-4 py-3 text-xs" style={{ color: "var(--text-muted)" }}>
                          {fmtDate(inv.created_at)}
                        </td>
                        <td className="px-4 py-3 text-sm mono" style={{ color: "var(--text-primary)" }}>
                          {Number(inv.amount_paid).toFixed(2)} {inv.currency.toUpperCase()}
                        </td>
                        <td className="px-4 py-3">
                          <span className={`badge ${invoiceStatusBadge(inv.status)}`}>{inv.status}</span>
                        </td>
                        <td className="px-4 py-3">
                          {inv.hosted_invoice_url && (
                            <a href={inv.hosted_invoice_url} target="_blank" rel="noreferrer"
                              className="text-xs font-medium" style={{ color: "var(--accent)" }}>View →</a>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </div>
      </div>

      {isOwner && (
        <div id="available-plans">
          <p className="section-title mb-1">{plan?.plan_name ? "Change plan" : "Choose a plan"}</p>
          <p className="text-sm mb-4" style={{ color: "var(--text-muted)" }}>
            {plan?.plan_name ? "Switch plans any time — changes take effect immediately." : "Pick the plan that fits how many leads you need."}
          </p>
          <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-4">
            {PLANS.map(p => (
              <PricingCard key={p.id} name={p.name} price={p.price} priceId={p.priceId} features={p.features}
                popular={p.popular} current={currentPlanId === p.id} onBuy={handleBuyPlan}
                loading={checkoutLoading} isEnterprise={p.isEnterprise} />
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

export default function Settings({ subTab, profile, plan, onProfileUpdated, onLogout, theme }) {
  if (subTab === "billing") return <BillingSection plan={plan} theme={theme} />;

  if (subTab === "integrations") return <IntegrationsSettings />;

  if (subTab === "team") return <TeamSection />;

  if (subTab === "notifications") return <NotificationsSettings />;

  return <ProfileSection profile={profile} onProfileUpdated={onProfileUpdated} onLogout={onLogout} />;
}
