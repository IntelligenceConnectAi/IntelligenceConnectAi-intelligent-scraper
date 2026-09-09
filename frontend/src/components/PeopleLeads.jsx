import { useEffect, useRef, useState } from "react";
import { api } from "../lib/api";
import { normalizeStateInput } from "../lib/usStates";
import RequestTabs from "./RequestTabs";
import PeopleLeadsTable from "./PeopleLeadsTable";
import SecureProcessingGlobe from "./SecureProcessingGlobe";
import StatusIndicator from "./StatusIndicator";
import BusinessTargetingSection, { initialTargetingState } from "./people-leads/BusinessTargetingSection";
import DncPhoneNumbersField from "./people-leads/DncPhoneNumbersField";
import { BUSINESS_NICHES } from "../lib/businessNiches";

const LEAD_TYPE_LABELS = {
  property_owners: "Property Owners",
  absentee_owners: "Absentee Owners",
  vacant_property_owners: "Vacant Property Owners",
  high_equity_homeowners: "High-Equity Homeowners",
  landowners: "Landowners",
  other: "Other",
};

function NewRequestForm({ onCreated }) {
  const [dashboard, setDashboard]     = useState(null);
  const [requestName, setRequestName] = useState("");
  const [targeting, setTargeting]     = useState(initialTargetingState);
  const [quantity, setQuantity]       = useState("");
  const [instructions, setInstructions] = useState("");
  const [dncIncluded, setDncIncluded] = useState(true);
  const [dncTermsAgreed, setDncTermsAgreed] = useState(false);
  const [loading, setLoading]         = useState(false);
  const [error, setError]             = useState("");

  useEffect(() => { api.clientDashboard().then(setDashboard).catch(() => {}); }, []);

  const niche = targeting.isOtherBusinessType ? null : (BUSINESS_NICHES.find(n => n.id === targeting.nicheId) || null);
  const audienceRequired = targeting.isOtherBusinessType || (!!niche && niche.serves === "Both");

  const canSubmit =
    !!requestName.trim() &&
    !!(targeting.nicheId || (targeting.isOtherBusinessType && targeting.otherBusinessType.trim())) &&
    (!audienceRequired || !!targeting.audience) &&
    !!targeting.businessName.trim() &&
    !!targeting.stateName &&
    targeting.cities.length > 0 &&
    (!dncIncluded || dncTermsAgreed);

  const submit = async (e) => {
    e.preventDefault();
    if (!requestName.trim())              { setError("Request name is required"); return; }
    if (!targeting.businessName.trim())   { setError("Business name is required"); return; }
    if (!targeting.nicheId && !(targeting.isOtherBusinessType && targeting.otherBusinessType.trim())) {
      setError("Business type is required"); return;
    }
    if (audienceRequired && !targeting.audience) { setError("Choose who you want to target"); return; }
    if (!targeting.stateName)             { setError("State is required"); return; }
    if (targeting.cities.length === 0)    { setError("Add at least one city"); return; }
    const qty = parseInt(quantity, 10);
    if (!qty || qty <= 0)                 { setError("Enter a valid number of leads"); return; }
    if (dncIncluded && !dncTermsAgreed)   { setError("Please agree to the DNC Terms & Conditions"); return; }

    setLoading(true); setError("");
    try {
      await api.createPeopleLeadRequest({
        request_name: requestName.trim(),
        lead_type: "other",
        state: normalizeStateInput(targeting.stateName),
        city: targeting.cities[0],
        zip_codes: targeting.zips,
        requested_quantity: qty,
        client_instructions: instructions.trim() || undefined,
        targeting: {
          business_name: targeting.businessName.trim(),
          business_type: targeting.isOtherBusinessType
            ? { id: null, name: targeting.otherBusinessType.trim(), category: null, is_other: true }
            : { id: niche.id, name: niche.name, category: niche.category, is_other: false },
          target_audience: targeting.audience || null,
          filter_stacks: targeting.audience === "Consumers" ? targeting.consumerStacks
                        : targeting.audience === "Businesses" ? targeting.businessStacks : [],
          cities: targeting.cities,
          dnc_included: dncIncluded,
          dnc_terms_accepted: dncIncluded ? dncTermsAgreed : null,
        },
      });
      setRequestName(""); setTargeting(initialTargetingState);
      setQuantity(""); setInstructions("");
      setDncIncluded(true); setDncTermsAgreed(false);
      onCreated();
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  };

  const remaining = dashboard?.leads_remaining_period;

  return (
    <div className="card p-6">
      <p className="font-semibold mb-1" style={{ color: "var(--text)" }}>New People Leads Request</p>
      <p className="text-xs mb-5" style={{ color: "var(--text-3)" }}>
        Delivered within 24 hours by our data team.
        {remaining != null && ` ${remaining.toLocaleString()} leads remaining this period.`}
      </p>
      <form onSubmit={submit} className="space-y-4">
        <div>
          <label className="label">Request Name</label>
          <input value={requestName} onChange={e => setRequestName(e.target.value)}
            placeholder="e.g. Miami absentee owners" className="input" />
        </div>

        <BusinessTargetingSection value={targeting} onChange={setTargeting} />

        <div>
          <label className="label">Number of Leads Requested</label>
          <input type="number" min="1" value={quantity} onChange={e => setQuantity(e.target.value)}
            placeholder="500" className="input mono" />
        </div>

        <div>
          <label className="label">Additional Instructions <span className="normal-case" style={{ color: "var(--text-3)", fontWeight: 400 }}>Optional</span></label>
          <textarea value={instructions} onChange={e => setInstructions(e.target.value)} rows={3}
            placeholder="Any targeting details, exclusions, or notes for our data team…"
            className="input" style={{ resize: "vertical" }} />
        </div>

        <DncPhoneNumbersField
          included={dncIncluded}
          onIncludedChange={setDncIncluded}
          termsAgreed={dncTermsAgreed}
          onTermsAgreedChange={setDncTermsAgreed}
        />

        {error && <p className="text-xs" style={{ color: "var(--danger)" }}>{error}</p>}

        <button type="submit" disabled={loading || !canSubmit} className="btn-primary w-full">
          {loading ? "Submitting…" : "◇ Submit Request"}
        </button>
      </form>
    </div>
  );
}

function RequestDetail({ requestId }) {
  const [req, setReq]         = useState(null);
  const [error, setError]     = useState("");
  const [respondText, setRespondText] = useState("");
  const [responding, setResponding]   = useState(false);
  const timer = useRef(null);

  const fetchReq = async () => {
    try {
      const d = await api.getPeopleLeadRequest(requestId);
      setReq(d);
      if (["Completed", "Cancelled"].includes(d.status)) clearInterval(timer.current);
    } catch (e) {
      setError(e.message);
      clearInterval(timer.current);
    }
  };

  useEffect(() => {
    fetchReq();
    timer.current = setInterval(fetchReq, 5000);
    return () => clearInterval(timer.current);
  }, [requestId]);

  const cancel = async () => {
    try { await api.cancelPeopleLeadRequest(requestId); clearInterval(timer.current); fetchReq(); }
    catch (e) { setError(e.message); }
  };

  const respond = async (e) => {
    e.preventDefault();
    if (!respondText.trim()) return;
    setResponding(true);
    try {
      const updated = await api.respondPeopleLeadRequest(requestId, { client_instructions: respondText.trim() });
      setReq(updated);
      setRespondText("");
    } catch (e) {
      setError(e.message);
    } finally {
      setResponding(false);
    }
  };

  if (error) return (
    <div className="alert-danger">{error}</div>
  );

  if (!req) return (
    <div className="text-sm animate-soft-pulse" style={{ color: "var(--text-3)" }}>Loading request…</div>
  );

  const isProcessing = req.status === "Submitted" || req.status === "Processing";
  const needsInfo     = req.status === "Needs Information";

  return (
    <div className="space-y-5 animate-fade-in">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="font-semibold" style={{ color: "var(--text)" }}>{req.request_name}</p>
          <p className="text-xs mt-0.5" style={{ color: "var(--text-3)" }}>
            {req.targeting?.business_type?.name || LEAD_TYPE_LABELS[req.lead_type] || req.lead_type} · {[req.city, req.county, req.state].filter(Boolean).join(", ")}
          </p>
        </div>
        <StatusIndicator status={req.status} variant="people" />
      </div>

      {isProcessing && <SecureProcessingGlobe variant="people" />}

      {needsInfo && (
        <div className="card p-5 space-y-3">
          <p className="text-sm" style={{ color: "var(--text-2)", lineHeight: 1.6 }}>{req.message}</p>
          <form onSubmit={respond} className="space-y-2">
            <label className="label">Your response</label>
            <textarea value={respondText} onChange={e => setRespondText(e.target.value)} rows={3}
              placeholder="Add the requested details…" className="input" style={{ resize: "vertical" }} />
            <button type="submit" disabled={responding || !respondText.trim()} className="btn-primary">
              {responding ? "Sending…" : "Send Response"}
            </button>
          </form>
        </div>
      )}

      {req.status === "Completed" && (
        <div className="grid grid-cols-2 gap-2">
          <div className="card p-3 text-center">
            <p className="stat-number text-2xl">{req.delivered_quantity}</p>
            <p className="text-xs mt-1" style={{ color: "var(--text-3)" }}>Leads delivered</p>
          </div>
          <div className="card p-3 flex items-center justify-center">
            {req.download_url && (
              <a href={req.download_url} target="_blank" rel="noreferrer" className="btn-primary">⬇ Download</a>
            )}
          </div>
        </div>
      )}

      {req.status === "Cancelled" && (
        <div className="p-3 rounded-lg text-sm" style={{
          background: "var(--surface-soft)", border: "1px solid var(--border)", color: "var(--text-2)"
        }}>{req.message}</div>
      )}

      {(isProcessing || needsInfo) && (
        <button onClick={cancel} className="btn-danger">Cancel request</button>
      )}
    </div>
  );
}

export default function PeopleLeads() {
  const [tab, setTab]           = useState("new");
  const [requests, setRequests] = useState([]);
  const [loading, setLoading]   = useState(true);
  const [error, setError]       = useState("");
  const [viewingId, setViewingId] = useState(null);

  const load = async () => {
    setLoading(true); setError("");
    try { setRequests(await api.listPeopleLeadRequests()); }
    catch (e) { setError(e.message); }
    finally { setLoading(false); }
  };

  useEffect(() => { load(); }, []);
  useEffect(() => {
    if (tab === "active" || tab === "completed") load();
  }, [tab]);

  const activeRequests = requests.filter(r => ["Submitted", "Processing", "Needs Information"].includes(r.status));
  const completedRequests = requests.filter(r => !["Submitted", "Processing", "Needs Information"].includes(r.status));

  const tabs = [
    { id: "new",       label: "New Request" },
    { id: "active",    label: "Active Requests",    count: activeRequests.length },
    { id: "completed", label: "Completed Requests", count: completedRequests.length },
  ];

  return (
    <div className="space-y-4 animate-fade-in">
      <RequestTabs tabs={tabs} activeTab={tab} onChange={(id) => { setViewingId(null); setTab(id); }} />

      {tab === "new" && <NewRequestForm onCreated={() => setTab("active")} />}

      {tab === "active" && (
        viewingId ? (
          <div className="card p-6">
            <button onClick={() => setViewingId(null)} className="btn-ghost text-xs mb-4">← Back to list</button>
            <RequestDetail requestId={viewingId} />
          </div>
        ) : loading ? (
          <div className="card p-10 text-center animate-soft-pulse">
            <p className="text-sm" style={{ color: "var(--text-3)" }}>Loading…</p>
          </div>
        ) : error ? (
          <div className="alert-danger">{error}</div>
        ) : activeRequests.length === 0 ? (
          <div className="card p-12 text-center animate-fade-in">
            <p className="text-3xl mb-3">◇</p>
            <p className="font-medium" style={{ color: "var(--text-2)" }}>No active requests</p>
            <p className="text-sm mt-1" style={{ color: "var(--text-3)" }}>
              Submit a new People Leads request to see it here while it's prepared.
            </p>
          </div>
        ) : (
          <div className="card overflow-hidden">
            <div className="divide-y" style={{ borderColor: "var(--border)" }}>
              {activeRequests.map(r => (
                <button key={r.id} onClick={() => setViewingId(r.id)}
                  className="w-full flex items-center justify-between px-5 py-3.5 text-left transition"
                  style={{ background: "transparent" }}
                  onMouseEnter={e => e.currentTarget.style.background = "var(--row-hover)"}
                  onMouseLeave={e => e.currentTarget.style.background = "transparent"}>
                  <div>
                    <p className="text-sm font-medium" style={{ color: "var(--text)" }}>{r.request_name}</p>
                    <p className="text-xs" style={{ color: "var(--text-3)" }}>
                      {r.targeting?.business_type?.name || LEAD_TYPE_LABELS[r.lead_type] || r.lead_type} · {[r.city, r.state].filter(Boolean).join(", ")}
                    </p>
                  </div>
                  <StatusIndicator status={r.status} variant="people" />
                </button>
              ))}
            </div>
          </div>
        )
      )}

      {tab === "completed" && (
        loading ? (
          <div className="card p-10 text-center animate-soft-pulse">
            <p className="text-sm" style={{ color: "var(--text-3)" }}>Loading…</p>
          </div>
        ) : error ? (
          <div className="alert-danger">{error}</div>
        ) : (
          <PeopleLeadsTable requests={completedRequests} />
        )
      )}
    </div>
  );
}
