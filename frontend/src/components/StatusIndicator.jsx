// Simplified status indicator per UI styling requirements §27 — only ever
// shows Submitted / Processing / Needs Information / Completed, never
// progress percentages, current city, or any other scraping-internal detail.
// Cancelled/Failed are real terminal states the doc doesn't cover; they keep
// a matching icon treatment so completed/history lists still read clearly.
import { Send, LoaderCircle, CircleHelp, CircleCheckBig, CircleX, Ban } from "lucide-react";

const SUBMITTED_COLOR = { business: "var(--business-secondary)", people: "var(--people-secondary)" };

const STATUS_CONFIG = {
  Submitted: { icon: Send, label: "Submitted" },
  Processing: { icon: LoaderCircle, label: "Processing", color: "var(--brand-purple-bright)", spin: true },
  "Needs Information": { icon: CircleHelp, label: "Needs Information", color: "var(--warning)" },
  Completed: { icon: CircleCheckBig, label: "Completed", color: "var(--success)" },
  Cancelled: { icon: Ban, label: "Cancelled", color: "var(--text-muted)" },
  Failed: { icon: CircleX, label: "Failed", color: "var(--danger-2)" },
};

export default function StatusIndicator({ status, variant = "business" }) {
  const config = STATUS_CONFIG[status] || STATUS_CONFIG.Submitted;
  const Icon = config.icon;
  const color = status === "Submitted" ? (SUBMITTED_COLOR[variant] || SUBMITTED_COLOR.business) : config.color;

  // color-mix(), not the old hex-alpha-suffix trick (`${color}55`) — that
  // only works on literal 6-digit hex, and `color` is now a var() string.
  return (
    <span className="status-indicator" style={{
      color,
      borderColor: `color-mix(in srgb, ${color} 33%, transparent)`,
      background: `color-mix(in srgb, ${color} 10%, transparent)`,
    }}>
      <Icon size={14} strokeWidth={2.1} className={config.spin ? "status-processing-icon" : undefined} />
      {config.label}
    </span>
  );
}
