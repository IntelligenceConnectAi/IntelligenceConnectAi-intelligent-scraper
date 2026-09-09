import { useState } from "react";
import RequestTabs from "./RequestTabs";
import PeopleLeadsOrganizer from "./campaign-organizer/PeopleLeadsOrganizer";
import BusinessLeadsOrganizer from "./campaign-organizer/BusinessLeadsOrganizer";
import GuardrailsReport from "./campaign-organizer/GuardrailsReport";

// Admin shell wrapper — AdminSidebar has no sub-tab mechanism (unlike the
// client sidebar's `children`), so this reuses the existing RequestTabs
// internal-tab pattern already used by PeopleLeads.jsx / SupportPage.jsx.
export default function AdminCampaignOrganizer({ theme }) {
  const [tab, setTab] = useState("people");
  const [lastPeopleRun, setLastPeopleRun] = useState(null);

  const tabs = [
    { id: "people", label: "People Leads" },
    { id: "business", label: "Business Leads" },
    { id: "guardrails", label: "Guardrails Reports" },
  ];

  return (
    <div className="space-y-4 animate-fade-in">
      <RequestTabs tabs={tabs} activeTab={tab} onChange={setTab} />
      {tab === "people" && <PeopleLeadsOrganizer onProcessed={setLastPeopleRun} />}
      {tab === "business" && <BusinessLeadsOrganizer />}
      {tab === "guardrails" && <GuardrailsReport prefill={lastPeopleRun} theme={theme} />}
    </div>
  );
}
