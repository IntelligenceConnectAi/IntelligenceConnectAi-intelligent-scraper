import { describe, expect, it } from "vitest";
import { addBusinessDays, buildScheduleRows, calculateAll, GUARDRAILS } from "./campaignGuardrails";

describe("calculateAll", () => {
  const base = { totalPhones: 12000, totalSms: 6000, totalEmails: 4000, callers: 2, startDate: null };

  it("computes cold-calling capacity", () => {
    const r = calculateAll(base);
    expect(r.dialsPerDay).toBe(600);
    expect(r.callersNeeded).toBe(1);
    expect(r.activeCallerIds).toBe(10); // max(MIN_CALLER_ID_POOL=10, ceil(600/150)=4)
    expect(r.rotationCycles).toBe(2);
    expect(r.totalCallerIds).toBe(20);
    expect(r.dialsPerNumber).toBe(60);
    expect(r.dialsCheckOk).toBe(true);
  });

  it("computes staffing", () => {
    const r = calculateAll(base);
    expect(r.callersDiff).toBe(1);
    expect(r.staffingOk).toBe(true);
    expect(r.teamCapacity).toBe(24000);
    expect(r.daysToFinish).toBe(10);
  });

  it("computes SMS capacity", () => {
    const r = calculateAll(base);
    expect(r.textsPerDay).toBe(300);
    expect(r.minSmsNumbers).toBe(1);
    expect(r.campaignsRequired).toBe(1);
    expect(r.activeSmsNumbers).toBe(4);
    expect(r.totalSmsNumbers).toBe(8);
    expect(r.textsPerNumber).toBe(75);
    expect(r.smsCheckOk).toBe(true);
  });

  it("computes email infrastructure", () => {
    const r = calculateAll(base);
    expect(r.emailsPerDay).toBe(200);
    expect(r.inboxesNeeded).toBe(6);
    expect(r.domainsNeeded).toBe(2);
    expect(r.domainCapacity).toBe(350);
    expect(r.emailsPerInbox).toBe(34);
    expect(r.emailCheckOk).toBe(true);
  });

  it("flags a shortfall when staffing is insufficient", () => {
    const r = calculateAll({ ...base, callers: 0 });
    expect(r.staffingOk).toBe(false);
    expect(r.daysToFinish).toBe(999);
  });

  it("dialsPerNumber never exceeds the per-number cap, by construction, at any volume", () => {
    // activeCallerIds is derived as ceil(dialsPerDay / MAX_DIALS_PER_NUMBER) (or the
    // MIN_CALLER_ID_POOL floor, whichever is larger) — either way this makes
    // dialsCheckOk true by definition, matching the original tool's behavior.
    const r = calculateAll({ ...base, totalPhones: 500000 });
    expect(r.dialsPerNumber).toBeLessThanOrEqual(GUARDRAILS.MAX_DIALS_PER_NUMBER);
    expect(r.dialsCheckOk).toBe(true);
  });

  it("returns no schedule when no start date is given", () => {
    expect(calculateAll(base).schedule).toBeNull();
  });

  it("builds a rotation schedule when a start date is given", () => {
    const startDate = new Date(2026, 0, 5); // Monday, Jan 5 2026 (local time)
    const r = calculateAll({ ...base, startDate });
    expect(r.schedule).not.toBeNull();
    expect(r.schedule.campaignEnd.getTime()).toBe(addBusinessDays(startDate, GUARDRAILS.CALLING_DAYS_PER_MONTH).getTime());
    expect(r.schedule.warmupStart.getTime()).toBe(startDate.getTime() - GUARDRAILS.EMAIL_WARMUP_DAYS * 86400000);

    const rows = buildScheduleRows(startDate, r.schedule);
    expect(rows).toHaveLength(6); // 5 base rows + Email Warmup
    expect(rows[0].label).toBe("Email Warmup");
  });
});

describe("addBusinessDays", () => {
  it("skips weekends", () => {
    // Friday, Jan 2 2026 + 1 business day should land on Monday, Jan 5 2026
    const friday = new Date(2026, 0, 2);
    const next = addBusinessDays(friday, 1);
    expect(next.getDay()).toBe(1); // Monday
    expect(next.getDate()).toBe(5);
  });
});
