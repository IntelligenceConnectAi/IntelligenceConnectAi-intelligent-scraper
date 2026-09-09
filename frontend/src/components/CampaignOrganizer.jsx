import { useState } from "react";
import PeopleLeadsOrganizer from "./campaign-organizer/PeopleLeadsOrganizer";
import BusinessLeadsOrganizer from "./campaign-organizer/BusinessLeadsOrganizer";
import GuardrailsReport from "./campaign-organizer/GuardrailsReport";

// Client shell wrapper — subTab-dispatch, exactly mirrors Settings.jsx.
export default function CampaignOrganizer({ subTab, theme }) {
  const [lastPeopleRun, setLastPeopleRun] = useState(null);

  if (subTab === "business") return <BusinessLeadsOrganizer />;
  if (subTab === "guardrails") return <GuardrailsReport prefill={lastPeopleRun} theme={theme} />;
  return <PeopleLeadsOrganizer onProcessed={setLastPeopleRun} />;
}
