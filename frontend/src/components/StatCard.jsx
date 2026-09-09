// KPI tile — shared across Dashboard, My Leads, History, and Admin Overview.
// Upgraded to the dashboard design system's kpi-card styling + animated
// Number Flow values (§9); `icon` is optional so untouched call sites keep
// rendering exactly as before, just without the icon square.
import NumberFlow from "@number-flow/react";

export default function StatCard({ label, value, accent = false, delay = 0, icon: Icon, footnote }) {
  const isNumeric = typeof value === "number" && Number.isFinite(value);

  return (
    <div className={`kpi-card animate-fade-up delay-${delay}`}>
      {accent && (
        <div className="absolute inset-0 bg-gradient-to-br from-[var(--accent-dim)] to-transparent opacity-60 pointer-events-none" />
      )}
      {Icon && (
        <div className="kpi-icon">
          <Icon size={18} strokeWidth={1.8} absoluteStrokeWidth />
        </div>
      )}
      <p className="kpi-label">{label}</p>
      <p className={`kpi-value ${accent ? "accent-text" : ""}`}>
        {isNumeric ? <NumberFlow value={value} /> : value}
      </p>
      {footnote && <p className="kpi-footnote">{footnote}</p>}
    </div>
  );
}
