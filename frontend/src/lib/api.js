import { supabase } from "./supabase";

const API_BASE_URL =
  import.meta.env.VITE_API_BASE_URL || "http://127.0.0.1:8000";

function qs(params = {}) {
  const parts = Object.entries(params)
    .filter(([, v]) => v !== undefined && v !== null && v !== "")
    .map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(v)}`);
  return parts.length ? `?${parts.join("&")}` : "";
}

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

// Multipart upload — apiFetch always sets Content-Type: application/json and
// JSON.stringify's the body, which breaks multipart parsing server-side. This omits
// Content-Type entirely so the browser sets the multipart boundary itself.
async function apiUpload(path, formData, method = "POST") {
  const { data: { session } } = await supabase.auth.getSession();
  const token = session?.access_token;

  const response = await fetch(`${API_BASE_URL}${path}`, {
    method,
    headers: token ? { Authorization: `Bearer ${token}` } : {},
    body: formData,
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
  createTopupCheckout: (quantity, successUrl, cancelUrl) =>
    apiFetch("/billing/topup/checkout", {
      method: "POST",
      body: JSON.stringify({ quantity, success_url: successUrl, cancel_url: cancelUrl }),
    }),
  getBillingPortal: ()         => apiFetch("/billing/portal"),

  // Client-safe Business Requests (Phase 2 — sanitized presentation layer)
  listBusinessRequests: ()     => apiFetch("/client/business-requests"),
  getBusinessRequest:   (id)   => apiFetch(`/client/business-requests/${id}`),

  // Client Dashboard (Phase 3)
  clientDashboard:      ()     => apiFetch("/dashboard/client"),

  // People Leads (Phase 4)
  createPeopleLeadRequest:  (data) => apiFetch("/people-leads/requests", { method: "POST", body: JSON.stringify(data) }),
  listPeopleLeadRequests:   ()     => apiFetch("/people-leads/requests"),
  getPeopleLeadRequest:     (id)   => apiFetch(`/people-leads/requests/${id}`),
  cancelPeopleLeadRequest:  (id)   => apiFetch(`/people-leads/requests/${id}/cancel`, { method: "POST" }),
  respondPeopleLeadRequest: (id, data) => apiFetch(`/people-leads/requests/${id}/respond`, { method: "POST", body: JSON.stringify(data) }),

  // Lead Files (Phase 5 — My Leads)
  listLeadFiles:    (params) => apiFetch(`/lead-files${qs(params)}`),
  getLeadFile:      (id)     => apiFetch(`/lead-files/${id}`),
  downloadLeadFile: (id)     => apiFetch(`/lead-files/${id}/download`),
  renameLeadFile:   (id, display_name) => apiFetch(`/lead-files/${id}`, { method: "PATCH", body: JSON.stringify({ display_name }) }),
  leadFileStats:    ()       => apiFetch("/lead-files/stats"),
  leadFileCharts:   ()       => apiFetch("/lead-files/charts"),

  // History (Phase 5)
  listHistory:   (params) => apiFetch(`/history${qs(params)}`),
  historyStats:  ()       => apiFetch("/history/stats"),
  historyCharts: ()       => apiFetch("/history/charts"),

  // Team / Organization (Phase 6)
  getOrganization:     ()          => apiFetch("/organization"),
  updateOrganization:  (name)      => apiFetch("/organization", { method: "PATCH", body: JSON.stringify({ name }) }),
  listMembers:         ()          => apiFetch("/organization/members"),
  listInvitations:     ()          => apiFetch("/organization/invitations"),
  createInvitation:    (email, role) => apiFetch("/organization/invitations", { method: "POST", body: JSON.stringify({ email, role }) }),
  resendInvitation:    (id)        => apiFetch(`/organization/invitations/${id}/resend`, { method: "POST" }),
  cancelInvitation:    (id)        => apiFetch(`/organization/invitations/${id}`, { method: "DELETE" }),
  updateMemberRole:    (id, role)  => apiFetch(`/organization/members/${id}`, { method: "PATCH", body: JSON.stringify({ role }) }),
  removeMember:        (id)        => apiFetch(`/organization/members/${id}`, { method: "DELETE" }),

  // Invitation preview/accept (public — used by AcceptInvitation.jsx, not authenticated)
  previewInvitation: (token)       => apiFetch(`/auth/invitations/${token}`),
  acceptInvitation:  (token, data) => apiFetch(`/auth/invitations/${token}/accept`, { method: "POST", body: JSON.stringify(data) }),

  // Notifications (Phase 6)
  listNotifications:   ()       => apiFetch("/notifications"),
  markNotificationRead: (id)    => apiFetch(`/notifications/${id}/read`, { method: "PATCH" }),
  markAllNotificationsRead: ()  => apiFetch("/notifications/read-all", { method: "POST" }),
  getNotificationPreferences: () => apiFetch("/notification-preferences"),
  updateNotificationPreferences: ({ muted_categories, email_enabled }) =>
    apiFetch("/notification-preferences", { method: "PATCH", body: JSON.stringify({ muted_categories, email_enabled }) }),

  // Billing expansion (Phase 6)
  billingInvoices:      () => apiFetch("/billing/invoices"),
  billingPaymentMethod: () => apiFetch("/billing/payment-method"),

  // Integrations (Phase 6)
  notifyMeIntegration: (key) => apiFetch(`/integrations/${key}/notify-me`, { method: "POST" }),
  listNotifiedIntegrations: () => apiFetch("/integrations/notify-me"),

  // Support (Phase 7) — create/reply are multipart (subject/category/body/
  // linked_resource_type/linked_resource_id/file as FormData entries).
  createTicket: (formData) => apiUpload("/support/tickets", formData),
  listTickets: (bucket) => apiFetch(`/support/tickets${qs({ bucket })}`),
  getTicket: (id) => apiFetch(`/support/tickets/${id}`),
  replyToTicket: (id, formData) => apiUpload(`/support/tickets/${id}/messages`, formData),
  downloadTicketAttachment: (ticketId, attachmentId) =>
    apiFetch(`/support/tickets/${ticketId}/attachments/${attachmentId}/download`),

  // ── Admin (Phase 8 — Lean MVP) ──────────────────────────────

  // Admin users / permissions
  adminMyPermissions:  ()               => apiFetch("/admin/me/permissions"),
  adminListUsers:      (params)         => apiFetch(`/admin/users${qs(params)}`),
  adminCreateUser:     (data)           => apiFetch("/admin/users", { method: "POST", body: JSON.stringify(data) }),
  adminUpdateUser:     (id, data)       => apiFetch(`/admin/users/${id}`, { method: "PATCH", body: JSON.stringify(data) }),
  adminDisableUser:    (id)             => apiFetch(`/admin/users/${id}/disable`, { method: "POST" }),
  adminEnableUser:     (id)             => apiFetch(`/admin/users/${id}/enable`, { method: "POST" }),
  adminUpdatePermission: (id, permission_key, action) =>
    apiFetch(`/admin/users/${id}/permissions`, { method: "PATCH", body: JSON.stringify({ permission_key, action }) }),

  // Admin clients
  adminListClients:      (params) => apiFetch(`/admin/clients${qs(params)}`),
  adminGetClient:        (id)     => apiFetch(`/admin/clients/${id}`),
  adminListPlans:        ()       => apiFetch("/admin/clients/plans"),
  adminSuspendClient:    (id)     => apiFetch(`/admin/clients/${id}/suspend`, { method: "POST" }),
  adminReactivateClient: (id)     => apiFetch(`/admin/clients/${id}/reactivate`, { method: "POST" }),
  adminUpdateClientPlan: (id, data) =>
    apiFetch(`/admin/clients/${id}/plan`, { method: "PATCH", body: JSON.stringify(data) }),
  adminListClientInvoices: (id)     => apiFetch(`/admin/clients/${id}/invoices`),
  adminRefundClient:       (id, data) =>
    apiFetch(`/admin/clients/${id}/refund`, { method: "POST", body: JSON.stringify(data) }),

  // Admin dashboard
  adminDashboard:       () => apiFetch("/admin/dashboard"),
  adminDashboardCharts: () => apiFetch("/admin/dashboard/charts"),

  // Admin business requests (jobs)
  adminListJobs:  (params) => apiFetch(`/admin/jobs${qs(params)}`),
  adminGetJob:    (id)     => apiFetch(`/admin/jobs/${id}`),
  adminRetryJob:  (id)     => apiFetch(`/admin/jobs/${id}/retry`, { method: "POST" }),
  adminCancelJob: (id)     => apiFetch(`/admin/jobs/${id}/cancel`, { method: "POST" }),

  // Admin People Leads (Phase 4 backend, first frontend consumer)
  adminListPeopleLeadRequests: () => apiFetch("/admin/people-leads/requests"),
  adminGetPeopleLeadRequest:   (id) => apiFetch(`/admin/people-leads/requests/${id}`),
  adminPatchPeopleLeadRequest: (id, data) => apiFetch(`/admin/people-leads/requests/${id}`, { method: "PATCH", body: JSON.stringify(data) }),
  adminAssignPeopleLeadRequest: (id, admin_user_id) =>
    apiFetch(`/admin/people-leads/requests/${id}/assign`, { method: "POST", body: JSON.stringify({ admin_user_id }) }),
  adminUploadPeopleLeadFile: (id, formData) => apiUpload(`/admin/people-leads/requests/${id}/upload`, formData),
  adminReviewPeopleLeadRequest: (id, decision, notes) =>
    apiFetch(`/admin/people-leads/requests/${id}/review`, { method: "POST", body: JSON.stringify({ decision, notes }) }),
  adminDeliverPeopleLeadRequest: (id, delivered_quantity) =>
    apiFetch(`/admin/people-leads/requests/${id}/deliver`, { method: "POST", body: JSON.stringify({ delivered_quantity }) }),
  adminRequestPeopleLeadRevision: (id, message) =>
    apiFetch(`/admin/people-leads/requests/${id}/request-revision`, { method: "POST", body: JSON.stringify({ message }) }),

  // Admin lead files
  adminListLeadFiles: ()   => apiFetch("/admin/lead-files"),
  adminGetLeadFile:   (id) => apiFetch(`/admin/lead-files/${id}`),
  adminDownloadLeadFile: (id) => apiFetch(`/admin/lead-files/${id}/download`),

  // Admin Support (Phase 7 backend, first frontend consumer)
  adminListTickets: (params) => apiFetch(`/admin/support/tickets${qs(params)}`),
  adminGetTicket:   (id)     => apiFetch(`/admin/support/tickets/${id}`),
  adminPatchTicket: (id, data) => apiFetch(`/admin/support/tickets/${id}`, { method: "PATCH", body: JSON.stringify(data) }),
  adminAssignTicket: (id, admin_user_id) =>
    apiFetch(`/admin/support/tickets/${id}/assign`, { method: "POST", body: JSON.stringify({ admin_user_id }) }),
  adminAddInternalNote: (id, formData) => apiUpload(`/admin/support/tickets/${id}/internal-notes`, formData),
  adminReplyTicket:     (id, formData) => apiUpload(`/admin/support/tickets/${id}/messages`, formData),
  adminDownloadTicketAttachment: (ticketId, attachmentId) =>
    apiFetch(`/admin/support/tickets/${ticketId}/attachments/${attachmentId}/download`),

  // Admin audit logs
  adminListAuditLogs: (params) => apiFetch(`/admin/audit-logs${qs(params)}`),

  // Campaign Organizer (stateless — no DB persistence)
  processPeopleLeadsCampaign:   (formData) => apiUpload("/campaign-organizer/people-leads/process", formData),
  processBusinessLeadsCampaign: (formData) => apiUpload("/campaign-organizer/business-leads/process", formData),
};