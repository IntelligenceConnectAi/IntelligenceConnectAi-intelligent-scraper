import { supabase } from "./supabase";

const API_BASE_URL =
  import.meta.env.VITE_API_BASE_URL || "http://127.0.0.1:8000";

async function apiFetch(path, options = {}) {
  const { data: { session } } = await supabase.auth.getSession();
  const token = session?.access_token;

  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(options.headers || {}),
    },
  });

  if (!response.ok) {
    let detail = `HTTP ${response.status}`;
    try {
      const body = await response.json();
      detail = body.detail || detail;
    } catch { /* ignore */ }
    throw new Error(detail);
  }

  return response.json();
}

export const api = {
  // Auth
  me:             ()           => apiFetch("/auth/me"),
  updateProfile:  (data)       => apiFetch("/auth/profile", { method: "PATCH", body: JSON.stringify(data) }),

  // Plans
  plans:          ()           => apiFetch("/plans"),

  // Usage
  usageToday:     ()           => apiFetch("/usage/today"),
  currentPlan:    ()           => apiFetch("/usage/plan"),

  // Jobs
  createJob:      (data)       => apiFetch("/jobs", { method: "POST", body: JSON.stringify(data) }),
  listJobs:       ()           => apiFetch("/jobs"),
  getJob:         (id)         => apiFetch(`/jobs/${id}`),
  cancelJob:      (id)         => apiFetch(`/jobs/${id}/cancel`, { method: "POST" }),
  downloadJob:    (id, type)   => apiFetch(`/jobs/${id}/download/${type}`),

  // Billing
  createCheckout: (price_id)   => apiFetch("/billing/checkout", { method: "POST", body: JSON.stringify({ price_id }) }),
  getBillingPortal: ()         => apiFetch("/billing/portal"),
};