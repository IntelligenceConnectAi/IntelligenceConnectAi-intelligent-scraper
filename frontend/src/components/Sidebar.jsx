// Client left-side navigation — exact hierarchy, icons, colors, active/hover
// states, and responsive (desktop/tablet/mobile-drawer) behavior per
// INTELLIGENT_SCRAPER_UI_STYLING_REQUIREMENTS.md §1, §4, §7-§13.
// No router in this app — navigation stays driven by activeSection/activeSubTab
// state passed down from ClientApp.jsx; only the visual layer changed here.
import { useEffect, useState } from "react";
import { UsersRound, Link2, ChevronDown, ChevronUp } from "lucide-react";
import { clientNavigation, NAV_ICON_PROPS } from "../lib/clientNavigation";

function LeadDot({ indicator }) {
  return <span className={`lead-dot lead-dot--${indicator}`} aria-hidden="true" />;
}

function NavItem({ item, activeSection, activeSubTab, isExpanded, onToggleExpand, onSelect }) {
  const isGroup = !!item.children;
  const isActiveSection = activeSection === item.key;
  const Icon = item.icon;
  const submenuId = `subnav-${item.key}`;

  if (!isGroup) {
    return (
      <button
        type="button"
        className={`sidebar-nav-item ${isActiveSection ? "is-active" : ""}`}
        onClick={() => onSelect(item.key, null)}
      >
        <Icon className="sidebar-nav-icon" {...NAV_ICON_PROPS} />
        <span>{item.label}</span>
      </button>
    );
  }

  return (
    <div>
      <button
        type="button"
        className={`sidebar-nav-item ${isActiveSection ? "is-active" : ""}`}
        aria-expanded={isExpanded}
        aria-controls={submenuId}
        onClick={() => onToggleExpand(item.key)}
      >
        <Icon className="sidebar-nav-icon" {...NAV_ICON_PROPS} />
        <span style={{ flex: 1 }}>{item.label}</span>
        {isExpanded
          ? <ChevronUp size={15} strokeWidth={2} absoluteStrokeWidth />
          : <ChevronDown size={15} strokeWidth={2} absoluteStrokeWidth />}
      </button>

      <div
        id={submenuId}
        style={{
          display: "grid",
          gridTemplateRows: isExpanded ? "1fr" : "0fr",
          transition: "grid-template-rows 220ms ease",
          overflow: "hidden",
        }}
      >
        <div style={{ minHeight: 0, overflow: "hidden" }}>
          <div className="sidebar-subnav">
            {item.children.map(child => {
              const isChildActive = isActiveSection && activeSubTab === child.key;
              const ChildIcon = child.icon;
              return (
                <button
                  key={child.key}
                  type="button"
                  className={`sidebar-subnav-item ${isChildActive ? "is-active" : ""}`}
                  onClick={() => onSelect(item.key, child.key)}
                >
                  {child.indicator
                    ? <LeadDot indicator={child.indicator} />
                    : ChildIcon
                      ? <ChildIcon size={16} strokeWidth={1.8} absoluteStrokeWidth />
                      : null}
                  <span>{child.label}</span>
                </button>
              );
            })}
          </div>
        </div>
      </div>
    </div>
  );
}

export default function Sidebar({ activeSection, activeSubTab, onNavigate, mobileOpen, onCloseMobile, orgName }) {
  const [expanded, setExpanded] = useState(() => {
    const initial = new Set();
    clientNavigation.forEach(item => {
      if (item.children && item.key === activeSection) initial.add(item.key);
    });
    return initial;
  });

  const toggleExpand = (key) => {
    setExpanded(prev => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key); else next.add(key);
      return next;
    });
  };

  const handleSelect = (sectionKey, subKey) => {
    // The selected child keeps its parent expanded — never collapse on navigate.
    if (subKey) setExpanded(prev => new Set(prev).add(sectionKey));
    onNavigate(sectionKey, subKey);
    onCloseMobile?.();
  };

  useEffect(() => {
    if (!mobileOpen) return;
    const onKey = (e) => { if (e.key === "Escape") onCloseMobile?.(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [mobileOpen, onCloseMobile]);

  const renderNav = () => (
    <>
      <div className="sidebar-brand">
        <div className="sidebar-brand-icon">
          <UsersRound size={36} strokeWidth={1.9} />
          <Link2 className="sidebar-brand-link" size={14} strokeWidth={2.2} />
        </div>
        <span
          className="sidebar-brand-title"
          title={orgName || undefined}
          style={{ maxWidth: "100%", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", padding: "0 12px" }}
        >
          {orgName || "Client Navigation"}
        </span>
      </div>

      <nav className="flex-1 overflow-y-auto" style={{ paddingBottom: 8, paddingTop: 4 }}>
        {clientNavigation.map(item => (
          <div key={item.key} className={item.dividerBefore ? "sidebar-section-divider" : undefined}>
            <NavItem
              item={item}
              activeSection={activeSection}
              activeSubTab={activeSubTab}
              isExpanded={expanded.has(item.key)}
              onToggleExpand={toggleExpand}
              onSelect={handleSelect}
            />
          </div>
        ))}
      </nav>
    </>
  );

  return (
    <>
      {/* Desktop / tablet — fixed sidebar */}
      <aside className="client-sidebar hidden md:flex flex-col">
        {renderNav()}
      </aside>

      {/* Mobile — off-canvas drawer */}
      {mobileOpen && (
        <div className="sidebar-mobile-backdrop md:hidden" onClick={onCloseMobile}>
          <aside
            className="client-sidebar client-sidebar--mobile flex flex-col"
            role="dialog"
            aria-modal="true"
            aria-label="Client navigation"
            onClick={(e) => e.stopPropagation()}
          >
            {renderNav()}
          </aside>
        </div>
      )}
    </>
  );
}
