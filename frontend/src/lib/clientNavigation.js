// Exact client sidebar hierarchy/order/icons per
// INTELLIGENT_SCRAPER_UI_STYLING_REQUIREMENTS.md §1, §3, §14.
// Keys match the activeSection/activeSubTab values ClientApp.jsx already uses
// (no router in this app — navigation is plain state).
import {
  House,
  MapPinCheckInside,
  Files,
  ClipboardList,
  Settings,
  Link,
  UsersRound,
  CreditCard,
  Bell,
  Headphones,
  Megaphone,
  Building2,
  Gauge,
} from "lucide-react";

export const NAV_ICON_PROPS = {
  size: 18,
  strokeWidth: 1.8,
  absoluteStrokeWidth: true,
};

export const clientNavigation = [
  {
    key: "dashboard",
    label: "Dashboard",
    icon: House,
  },
  {
    key: "get-leads",
    label: "Get the Leads",
    icon: MapPinCheckInside,
    children: [
      { key: "people", label: "People Leads", indicator: "people" },
      { key: "business", label: "Business Leads", indicator: "business" },
    ],
  },
  {
    key: "campaign-organizer",
    label: "Campaign Organizer",
    icon: Megaphone,
    children: [
      { key: "people", label: "People Leads", icon: UsersRound },
      { key: "business", label: "Business Leads", icon: Building2 },
      { key: "guardrails", label: "Guardrails Reports", icon: Gauge },
    ],
  },
  {
    key: "my-leads",
    label: "My Leads",
    icon: Files,
    dividerBefore: true,
  },
  {
    key: "history",
    label: "History",
    icon: ClipboardList,
  },
  {
    key: "settings",
    label: "Settings",
    icon: Settings,
    children: [
      { key: "integrations", label: "Integrations", icon: Link },
      { key: "team", label: "Team", icon: UsersRound },
      { key: "billing", label: "Billing", icon: CreditCard },
      { key: "notifications", label: "Notifications", icon: Bell },
    ],
  },
  {
    key: "support",
    label: "Support",
    icon: Headphones,
    dividerBefore: true,
  },
];
