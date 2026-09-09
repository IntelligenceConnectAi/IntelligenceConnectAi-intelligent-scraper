// Filter-stack card metadata and derived-content helpers, ported verbatim from
// "reference only.html"'s STACK_META / BIZ_STACK_META / icmseQualNote /
// icmseBizStrengthNote / icmseCatChips. These are small and hand-stable
// enough not to need the extraction script.

export const CONSUMER_STACK_META = {
  bal: { tag: "Recommended", name: "Balanced Filter Stack", sub: "Best mix of quality and reach", rec: true },
  best: { tag: "Highest quality", name: "Best-Quality Filter Stack", sub: "Smallest list, highest intent", rec: false },
  max: { tag: "Maximum reach", name: "Maximum-Volume Filter Stack", sub: "Largest list, widest net", rec: false },
};

export const BUSINESS_STACK_META = {
  bal: { tag: "Recommended", name: "Recommended Audience", sub: "Best mix of quality and reach", rec: true },
  best: { tag: "Highest quality", name: "Highest-Quality Audience", sub: "Fewest categories, best fit", rec: false },
  max: { tag: "Maximum reach", name: "Maximum-Reach Audience", sub: "Widest commercial net", rec: false },
};

// Order stacks always render in, matching the reference exactly.
export const STACK_ORDER = ["bal", "best", "max"];

function starDigit(rating) {
  const m = String(rating || "").match(/\((\d)\/5\)/);
  return m ? parseInt(m[1], 10) : null;
}

export function qualNote(qual) {
  const n = starDigit(qual);
  if (n === null) return "";
  if (n >= 5) return "Property data maps almost perfectly onto this buyer.";
  if (n === 4) return "Strong match — filters closely track real buying intent.";
  if (n === 3) return "Reasonable match. Expect to qualify further on contact.";
  if (n === 2) return "Thin match. Treat as a starting list, qualify on the call.";
  return "Weak match. Use alongside other channels rather than alone.";
}

export function strengthNote(strength) {
  const n = starDigit(strength);
  if (n === null) return "";
  if (n >= 5) return "Commercial work is a natural extension of this business.";
  if (n === 4) return "Strong commercial potential with the right accounts.";
  if (n === 3) return "Workable, but expect a longer sales cycle.";
  return "Thin fit. Pursue selectively rather than as your main channel.";
}

export function splitCategoryChips(value) {
  return String(value || "")
    .split("·") // ·
    .map((x) => x.trim())
    .filter(Boolean);
}

export function bizOppClass(opp) {
  if (/STRONG/i.test(opp)) return "strong";
  if (/SECONDARY/i.test(opp)) return "secondary";
  return "limited";
}

export function bizOppLabel(opp) {
  if (/STRONG/i.test(opp)) return "Strong commercial opportunity";
  if (/SECONDARY/i.test(opp)) return "Secondary commercial opportunity";
  return "Limited / situational commercial fit";
}
