// Generic New Request / Active Requests / Completed Requests tab shell with
// count badges — used by Business Leads now, reusable by People Leads (Phase 4).
export default function RequestTabs({ tabs, activeTab, onChange }) {
  return (
    <div className="flex gap-2 flex-wrap">
      {tabs.map(t => (
        <button
          key={t.id}
          type="button"
          onClick={() => onChange(t.id)}
          className={activeTab === t.id ? "btn-primary" : "btn-ghost"}
          style={{ fontSize: "0.8125rem" }}
        >
          {t.label}
          {t.count != null && <span className="ml-1.5 opacity-70">({t.count})</span>}
        </button>
      ))}
    </div>
  );
}
