import { useEffect, useState } from "react";
import { GUARDRAILS, buildScheduleRows, calculateAll } from "../../lib/campaignGuardrails";
import StatCard from "../StatCard";
import GaugeThresholdChart from "./charts/GaugeThresholdChart";
import CapacityBarChart from "./charts/CapacityBarChart";
import RotationScheduleTimeline from "./charts/RotationScheduleTimeline";

const fmtDate = (d) => d.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });

export default function GuardrailsReport({ prefill, theme }) {
  const [totalPhones, setTotalPhones] = useState("0");
  const [totalSms, setTotalSms] = useState("0");
  const [totalEmails, setTotalEmails] = useState("0");
  const [callers, setCallers] = useState("2");
  const [useDates, setUseDates] = useState(false);
  const [startDateStr, setStartDateStr] = useState(() => new Date().toISOString().slice(0, 10));

  useEffect(() => {
    if (!prefill?.processedAt) return;
    const counts = prefill.marketingCounts || prefill.propertiesCounts;
    if (!counts) return;
    setTotalPhones(String(counts.dialer));
    setTotalSms(String(counts.sms));
    setTotalEmails(String(counts.email));
  }, [prefill?.processedAt]);

  const phones = Math.max(0, parseInt(totalPhones, 10) || 0);
  const sms = Math.max(0, parseInt(totalSms, 10) || 0);
  const emails = Math.max(0, parseInt(totalEmails, 10) || 0);
  const callerCount = Math.max(0, parseInt(callers, 10) || 0);
  const startDate = useDates && startDateStr ? new Date(`${startDateStr}T00:00:00`) : null;

  const hasInput = phones > 0 || sms > 0 || emails > 0;
  const r = calculateAll({ totalPhones: phones, totalSms: sms, totalEmails: emails, callers: callerCount, startDate });

  const checks = [
    { name: "Cold Calling", ok: r.dialsCheckOk },
    { name: "SMS", ok: r.smsCheckOk },
    { name: "Email", ok: r.emailCheckOk },
    { name: "Staffing", ok: r.staffingOk },
  ];
  const passed = checks.filter((c) => c.ok).length;

  const scheduleRows = buildScheduleRows(startDate, r.schedule);

  return (
    <div className="space-y-5 animate-fade-in">
      <div className="dashboard-panel dashboard-panel--hero">
        <p className="page-title">Marketing Guardrails</p>
        <p className="page-subtitle">Monthly campaign capacity &amp; compliance dashboard.</p>
      </div>

      <div className="card p-6">
        <p className="font-semibold mb-4" style={{ color: "var(--text)" }}>Campaign Inputs</p>
        <div className="grid gap-4 sm:grid-cols-3">
          <div>
            <label className="label">📞 Total Phone Numbers</label>
            <input type="number" min="0" value={totalPhones} onChange={(e) => setTotalPhones(e.target.value)} className="input mono" />
          </div>
          <div>
            <label className="label">💬 Total SMS Numbers (Mobile)</label>
            <input type="number" min="0" value={totalSms} onChange={(e) => setTotalSms(e.target.value)} className="input mono" />
          </div>
          <div>
            <label className="label">📧 Total Email Addresses</label>
            <input type="number" min="0" value={totalEmails} onChange={(e) => setTotalEmails(e.target.value)} className="input mono" />
          </div>
        </div>
        <div className="grid gap-4 sm:grid-cols-2 mt-4">
          <div>
            <label className="label">👥 Callers on Team</label>
            <input type="number" min="0" value={callers} onChange={(e) => setCallers(e.target.value)} className="input mono" />
          </div>
          <div>
            <label className="label">📅 Campaign Dates <span className="normal-case" style={{ color: "var(--text-3)", fontWeight: 400 }}>Optional</span></label>
            <div className="flex items-center gap-2" style={{ height: 38 }}>
              <label className="flex items-center gap-1.5 text-sm" style={{ color: "var(--text-2)" }}>
                <input type="checkbox" checked={useDates} onChange={(e) => setUseDates(e.target.checked)} />
                Add campaign start date
              </label>
            </div>
            {useDates && (
              <input type="date" value={startDateStr} onChange={(e) => setStartDateStr(e.target.value)} className="input mono mt-2" />
            )}
          </div>
        </div>
      </div>

      {!hasInput ? (
        <p className="text-sm" style={{ color: "var(--text-3)" }}>
          👆 Enter your numbers above to generate the report, or process a People Leads batch first — the counts auto-populate here.
        </p>
      ) : (
        <>
          <div
            style={{
              padding: "0.75rem 1rem", borderRadius: 8, fontSize: "0.875rem",
              background: passed === checks.length ? "var(--success-soft)" : "var(--warning-soft)",
              border: `1px solid ${passed === checks.length ? "var(--success)" : "var(--warning)"}`,
              color: passed === checks.length ? "var(--success)" : "var(--warning)",
            }}
          >
            {passed === checks.length
              ? `✅ All ${checks.length} guardrails within limits — campaign is safe to launch.`
              : `⚠️ ${passed}/${checks.length} guardrails OK — needs attention: ${checks.filter(c => !c.ok).map(c => c.name).join(", ")}`}
          </div>

          {/* Cold Calling */}
          <div className="dashboard-panel">
            <p className="dashboard-panel-title">📞 Cold Calling — Landline + Mobile · all phone numbers</p>
            <div className="dashboard-grid">
              <div className="span-3 span-xl-3"><StatCard label="Dials / Day" value={r.dialsPerDay} footnote="Total ÷ 20 days" /></div>
              <div className="span-3 span-xl-3"><StatCard label="Callers Needed" value={r.callersNeeded} footnote="Dials ÷ 600/caller" /></div>
              <div className="span-3 span-xl-3"><StatCard label="Active Caller IDs" value={r.activeCallerIds} footnote="Per rotation cycle" /></div>
              <div className="span-3 span-xl-3"><StatCard label="Total Caller IDs" value={r.totalCallerIds} footnote={`Active × ${r.rotationCycles} cycles`} /></div>
            </div>
            <div className="grid gap-4 sm:grid-cols-2 mt-4">
              <div key={`cc-gauge-${theme}`}>
                <GaugeThresholdChart label="Dials / Number / Day" value={r.dialsPerNumber} limit={GUARDRAILS.MAX_DIALS_PER_NUMBER} />
              </div>
              <div key={`cc-bar-${theme}`}>
                <CapacityBarChart
                  title="Daily Calling Capacity"
                  items={[
                    { label: "Dials/Day", value: r.dialsPerDay },
                    { label: "Team Cap/Day", value: callerCount * GUARDRAILS.DIALS_PER_CALLER },
                    { label: "Per Caller", value: GUARDRAILS.DIALS_PER_CALLER },
                  ]}
                />
              </div>
            </div>
          </div>

          {/* Staffing */}
          <div className="dashboard-panel">
            <p className="dashboard-panel-title">👥 Staffing Analysis</p>
            <p className="text-sm mb-4" style={{ color: r.staffingOk ? "var(--success)" : "var(--danger-2)" }}>
              {r.staffingOk
                ? `✅ Sufficient — ${callerCount} callers, ${r.callersDiff} surplus over the ${r.callersNeeded} needed. List finishes in ~${r.daysToFinish} days.`
                : `⚠️ Shortfall — ${callerCount} callers but need ${r.callersNeeded}. Hire ${Math.abs(r.callersDiff)} more to finish in 20 days (currently ~${r.daysToFinish} days).`}
            </p>
            <div className="dashboard-grid">
              <div className="span-4 span-xl-4"><StatCard label="Callers Needed" value={r.callersNeeded} footnote="To finish in 20 days" /></div>
              <div className="span-4 span-xl-4"><StatCard label="Team Capacity (20d)" value={r.teamCapacity} footnote={`${callerCount} × 600 × 20`} /></div>
              <div className="span-4 span-xl-4"><StatCard label="Days to Finish" value={r.daysToFinish} footnote="Target: ≤ 20" /></div>
            </div>
          </div>

          {/* SMS */}
          <div className="dashboard-panel">
            <p className="dashboard-panel-title">💬 SMS — Mobile numbers only · A2P 10DLC</p>
            <div className="dashboard-grid">
              <div className="span-3 span-xl-3"><StatCard label="Texts / Day" value={r.textsPerDay} footnote="SMS ÷ 20 days" /></div>
              <div className="span-3 span-xl-3"><StatCard label="Campaigns Required" value={r.campaignsRequired} footnote="÷ 2,000/campaign/day" /></div>
              <div className="span-3 span-xl-3"><StatCard label="Active SMS Numbers" value={r.activeSmsNumbers} footnote={`${GUARDRAILS.SMS_NUMBERS_PER_CAMPAIGN}/campaign`} /></div>
              <div className="span-3 span-xl-3"><StatCard label="Total SMS Numbers" value={r.totalSmsNumbers} footnote={`Active × ${r.rotationCycles} cycles`} /></div>
            </div>
            <div className="grid gap-4 sm:grid-cols-2 mt-4">
              <div key={`sms-gauge-${theme}`}>
                <GaugeThresholdChart label="Texts / Number / Day" value={r.textsPerNumber} limit={GUARDRAILS.MAX_SMS_PER_NUMBER} />
              </div>
              <div key={`sms-bar-${theme}`}>
                <CapacityBarChart
                  title="SMS Volume & Numbers"
                  items={[
                    { label: "Texts/Day", value: r.textsPerDay },
                    { label: "Min Numbers", value: r.minSmsNumbers },
                    { label: "Active Numbers", value: r.activeSmsNumbers },
                  ]}
                />
              </div>
            </div>
          </div>

          {/* Email */}
          <div className="dashboard-panel">
            <p className="dashboard-panel-title">📧 Email — Verified emails only · CAN-SPAM compliant</p>
            <div className="dashboard-grid">
              <div className="span-3 span-xl-3"><StatCard label="Emails / Day" value={r.emailsPerDay} footnote="Total ÷ 20 days" /></div>
              <div className="span-3 span-xl-3"><StatCard label="Inboxes Needed" value={r.inboxesNeeded} footnote="÷ 35/inbox/day" /></div>
              <div className="span-3 span-xl-3"><StatCard label="Domains Needed" value={r.domainsNeeded} footnote="÷ 5 inboxes/domain" /></div>
              <div className="span-3 span-xl-3"><StatCard label="Domain Daily Cap" value={r.domainCapacity} footnote="Domains × 175/day" /></div>
            </div>
            <div className="grid gap-4 sm:grid-cols-2 mt-4">
              <div key={`email-gauge-${theme}`}>
                <GaugeThresholdChart label="Emails / Inbox / Day" value={r.emailsPerInbox} limit={GUARDRAILS.MAX_EMAILS_PER_INBOX} />
              </div>
              <div key={`email-bar-${theme}`}>
                <CapacityBarChart
                  title="Email Infrastructure"
                  items={[
                    { label: "Inboxes", value: r.inboxesNeeded },
                    { label: "Domains", value: r.domainsNeeded },
                    { label: "Cap ÷ 100", value: Math.max(1, Math.floor(r.domainCapacity / 100)) },
                  ]}
                />
              </div>
            </div>
          </div>

          {/* Rotation timeline */}
          {startDate && r.schedule && (
            <div className="dashboard-panel">
              <p className="dashboard-panel-title">🗓️ Rotation Schedule</p>
              <div key={`timeline-${theme}`}>
                <RotationScheduleTimeline rows={scheduleRows} />
              </div>
              <div className="dashboard-grid mt-4">
                <div className="span-4 span-xl-4"><StatCard label="Campaign End" value={fmtDate(r.schedule.campaignEnd)} footnote="20 business days" /></div>
                <div className="span-4 span-xl-4"><StatCard label="Warmup Start" value={fmtDate(r.schedule.warmupStart)} footnote="Start − 30 days" /></div>
                <div className="span-4 span-xl-4"><StatCard label="Email Rotation" value={fmtDate(r.schedule.emailRotate)} footnote="After 20 sending days" /></div>
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}
