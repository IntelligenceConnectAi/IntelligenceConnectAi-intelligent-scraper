import { useEffect, useState } from "react";
import { api } from "../lib/api";

const INTEGRATIONS = [
  { key: "gohighlevel", name: "GoHighLevel", icon: "◆", description: "Sync completed leads directly into your GoHighLevel pipelines." },
  { key: "hubspot", name: "HubSpot", icon: "◈", description: "Push new leads straight into your HubSpot CRM contacts." },
  { key: "salesforce", name: "Salesforce", icon: "◉", description: "Send delivered leads into Salesforce as new records." },
  { key: "pipedrive", name: "Pipedrive", icon: "◎", description: "Create Pipedrive deals automatically from new leads." },
  { key: "zoho_crm", name: "Zoho CRM", icon: "◐", description: "Sync your lead files with Zoho CRM contacts and deals." },
  { key: "google_sheets", name: "Google Sheets", icon: "▦", description: "Export completed leads directly into a live Google Sheet." },
  { key: "zapier", name: "Zapier", icon: "⚡", description: "Connect leads to thousands of apps through Zapier." },
  { key: "make", name: "Make", icon: "⬡", description: "Automate lead delivery into your Make (Integromat) scenarios." },
  { key: "webhooks", name: "Webhooks", icon: "◫", description: "Receive a webhook the moment a new lead file is ready." },
];

export default function IntegrationsSettings() {
  const [subscribed, setSubscribed] = useState(new Set());
  const [busyKey, setBusyKey] = useState(null);

  useEffect(() => {
    api.listNotifiedIntegrations()
      .then(rows => setSubscribed(new Set(rows.map(r => r.integration_key))))
      .catch(() => {});
  }, []);

  const notifyMe = async (key) => {
    setBusyKey(key);
    try {
      await api.notifyMeIntegration(key);
      setSubscribed(prev => new Set(prev).add(key));
    } catch (e) {
      alert(`Failed: ${e.message}`);
    } finally {
      setBusyKey(null);
    }
  };

  return (
    <div className="space-y-5 animate-fade-in">
      <div className="card p-5">
        <p className="label mb-1">Integrations</p>
        <p className="text-sm" style={{ color: "var(--text-2)" }}>
          CRM and automation integrations are coming soon. You will be able to send completed leads
          directly to your preferred tools without manually uploading files.
        </p>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 gap-4">
        {INTEGRATIONS.map(item => {
          const isSubscribed = subscribed.has(item.key);
          return (
            <div key={item.key} className="card p-5 flex flex-col">
              <div className="flex items-start justify-between mb-3">
                <span className="text-2xl">{item.icon}</span>
                <span className="badge badge-muted">Coming Soon</span>
              </div>
              <p className="font-medium text-sm mb-1.5" style={{ color: "var(--text)" }}>{item.name}</p>
              <p className="text-xs mb-4 flex-1" style={{ color: "var(--text-3)" }}>{item.description}</p>
              <button onClick={() => notifyMe(item.key)} disabled={isSubscribed || busyKey === item.key}
                className={isSubscribed ? "btn-ghost text-xs" : "btn-primary text-xs"}
                style={{ padding: "6px 10px" }}>
                {isSubscribed ? "Notified ✓" : busyKey === item.key ? "…" : "Notify Me"}
              </button>
            </div>
          );
        })}
      </div>
    </div>
  );
}
