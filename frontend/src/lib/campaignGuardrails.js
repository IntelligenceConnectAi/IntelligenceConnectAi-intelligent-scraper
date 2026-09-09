// Campaign Organizer — capacity guardrails calculator, ported directly from
// the team's existing standalone Streamlit tool (`clean (1).py`). Pure
// arithmetic, no file I/O, so this runs entirely client-side rather than
// round-tripping to the backend. Limits are fixed constants by design (not
// user-editable — matches the original tool's behavior).

export const GUARDRAILS = {
  MAX_DIALS_PER_NUMBER: 150,
  DIALS_PER_CALLER: 600,
  MIN_CALLER_ID_POOL: 10,
  ROTATION_CALLING_DAYS: 10,
  CALLING_DAYS_PER_MONTH: 20,

  MAX_SMS_PER_NUMBER: 500,
  SMS_NUMBERS_PER_CAMPAIGN: 4,
  MAX_SMS_PER_CAMPAIGN: 2000,

  MAX_INBOXES_PER_DOMAIN: 5,
  MAX_EMAILS_PER_INBOX: 35,
  DOMAIN_DAILY_CAPACITY: 175,
  EMAIL_WARMUP_DAYS: 30,
  EMAIL_ROTATION_DAYS: 20,
};

const DAY_MS = 24 * 60 * 60 * 1000;

export function addBusinessDays(startDate, days) {
  let current = new Date(startDate.getTime());
  let added = 0;
  while (added < days) {
    current = new Date(current.getTime() + DAY_MS);
    const day = current.getDay(); // 0 = Sun, 6 = Sat
    if (day !== 0 && day !== 6) added += 1;
  }
  return current;
}

export function calculateAll({ totalPhones, totalSms, totalEmails, callers, startDate }) {
  const G = GUARDRAILS;

  // Cold calling
  const dialsPerDay = Math.ceil(totalPhones / G.CALLING_DAYS_PER_MONTH);
  const callersNeeded = Math.ceil(dialsPerDay / G.DIALS_PER_CALLER);
  const activeCallerIds = Math.max(G.MIN_CALLER_ID_POOL, Math.ceil(dialsPerDay / G.MAX_DIALS_PER_NUMBER));
  const rotationCycles = Math.floor(G.CALLING_DAYS_PER_MONTH / G.ROTATION_CALLING_DAYS);
  const totalCallerIds = activeCallerIds * rotationCycles;
  const dialsPerNumber = activeCallerIds > 0 ? Math.ceil(dialsPerDay / activeCallerIds) : 0;
  const dialsCheckOk = dialsPerNumber <= G.MAX_DIALS_PER_NUMBER;

  // Staffing
  const callersDiff = callers - callersNeeded;
  const staffingOk = callers >= callersNeeded;
  const teamCapacity = callers * G.DIALS_PER_CALLER * G.CALLING_DAYS_PER_MONTH;
  const daysToFinish = callers > 0 ? Math.ceil(totalPhones / (callers * G.DIALS_PER_CALLER)) : 999;

  // SMS
  const textsPerDay = Math.ceil(totalSms / G.CALLING_DAYS_PER_MONTH);
  const minSmsNumbers = Math.ceil(textsPerDay / G.MAX_SMS_PER_NUMBER);
  const campaignsRequired = Math.ceil(textsPerDay / G.MAX_SMS_PER_CAMPAIGN);
  const activeSmsNumbers = Math.max(minSmsNumbers, campaignsRequired * G.SMS_NUMBERS_PER_CAMPAIGN);
  const totalSmsNumbers = activeSmsNumbers * rotationCycles;
  const textsPerNumber = activeSmsNumbers > 0 ? Math.ceil(textsPerDay / activeSmsNumbers) : 0;
  const smsCheckOk = textsPerNumber <= G.MAX_SMS_PER_NUMBER;

  // Email
  const emailsPerDay = Math.ceil(totalEmails / G.CALLING_DAYS_PER_MONTH);
  const inboxesNeeded = Math.ceil(emailsPerDay / G.MAX_EMAILS_PER_INBOX);
  const domainsNeeded = Math.ceil(inboxesNeeded / G.MAX_INBOXES_PER_DOMAIN);
  const domainCapacity = domainsNeeded * G.DOMAIN_DAILY_CAPACITY;
  const emailsPerInbox = inboxesNeeded > 0 ? Math.ceil(emailsPerDay / inboxesNeeded) : 0;
  const emailCheckOk = emailsPerInbox <= G.MAX_EMAILS_PER_INBOX;

  // Rotation schedule (only if a start date was given)
  let schedule = null;
  if (startDate) {
    const rotateOut1 = addBusinessDays(startDate, G.ROTATION_CALLING_DAYS);
    const rotateOut2 = addBusinessDays(startDate, G.ROTATION_CALLING_DAYS * 2);
    schedule = {
      campaignEnd: addBusinessDays(startDate, G.CALLING_DAYS_PER_MONTH),
      rotateOut1,
      rotateOut2,
      warmupStart: new Date(startDate.getTime() - G.EMAIL_WARMUP_DAYS * DAY_MS),
      emailRotate: addBusinessDays(startDate, G.EMAIL_ROTATION_DAYS),
    };
  }

  return {
    dialsPerDay, callersNeeded, activeCallerIds, rotationCycles, totalCallerIds, dialsPerNumber, dialsCheckOk,
    callersDiff, staffingOk, teamCapacity, daysToFinish,
    textsPerDay, minSmsNumbers, campaignsRequired, activeSmsNumbers, totalSmsNumbers, textsPerNumber, smsCheckOk,
    emailsPerDay, inboxesNeeded, domainsNeeded, domainCapacity, emailsPerInbox, emailCheckOk,
    schedule,
  };
}

// Rotation-schedule timeline rows, exact original event list (5 rows, +1 if
// a start date/schedule was given) — feeds RotationScheduleTimeline's `rows` prop.
export function buildScheduleRows(startDate, schedule) {
  if (!startDate || !schedule) return [];
  const rows = [
    { label: "Caller IDs", start: startDate, end: schedule.rotateOut1 },
    { label: "Caller IDs (cyc 2)", start: schedule.rotateOut1, end: schedule.rotateOut2 },
    { label: "SMS Numbers", start: startDate, end: schedule.rotateOut1 },
    { label: "SMS Numbers (cyc 2)", start: schedule.rotateOut1, end: schedule.rotateOut2 },
    { label: "Email Inboxes", start: startDate, end: schedule.emailRotate },
  ];
  if (schedule.warmupStart) {
    rows.unshift({ label: "Email Warmup", start: schedule.warmupStart, end: startDate });
  }
  return rows;
}
