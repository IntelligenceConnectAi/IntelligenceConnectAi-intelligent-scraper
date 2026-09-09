"""
Pydantic response models — matched to DB rows and views.
"""

from datetime import datetime
from decimal import Decimal
from typing import Dict, List, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, field_validator


class User(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    email: str
    full_name: str | None = None
    is_admin: bool = False
    is_active: bool = True
    platform_role: str = "client"
    created_at: datetime


class Plan(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    price_monthly: Decimal
    leads_per_month: int
    leads_per_day: int
    cities_per_job: int
    keywords_per_job: int
    history_days: int
    concurrent_jobs: int
    email_scraping: bool
    api_access: bool


class CurrentPlanResponse(BaseModel):
    """From user_current_plan view."""
    model_config = ConfigDict(from_attributes=True)

    user_id: UUID
    email: str
    plan_id: str | None = None
    plan_name: str | None = None
    price_monthly: Decimal | None = None
    daily_limit: int | None = None
    monthly_limit: int | None = None
    cities_per_job: int | None = None
    concurrent_jobs: int | None = None
    email_scraping: bool | None = None
    api_access: bool | None = None
    subscription_status: str | None = None
    current_period_end: datetime | None = None
    cancel_at_period_end: bool | None = None


class TodayUsageResponse(BaseModel):
    """From user_today_usage view."""
    model_config = ConfigDict(from_attributes=True)

    user_id: UUID
    email: str
    daily_limit: int | None = None
    leads_used_today: int
    leads_with_web_today: int
    leads_no_web_today: int
    emails_found_today: int
    jobs_run_today: int
    leads_remaining: int


# ─────────────────────────────────────────────────────
# JOB SCHEMAS
# ─────────────────────────────────────────────────────
class CreateJobRequest(BaseModel):
    industry: str
    state: str
    cities: List[str]

    @field_validator("cities")
    @classmethod
    def cities_not_empty(cls, v):
        if not v:
            raise ValueError("At least one city is required")
        return v


class JobCityProgress(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    city: str
    maps_status: str
    maps_leads: Optional[int] = 0


class JobResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    industry: str
    state: str
    cities: List[str]
    status: str
    current_step: Optional[str] = None
    current_city: Optional[str] = None
    cities_done: int = 0
    cities_total: int = 0
    total_raw: int = 0
    total_clean: int = 0
    with_website: int = 0
    no_website: int = 0
    emails_found: int = 0
    emails_attempted: int = 0
    error_message: Optional[str] = None
    created_at: datetime
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    city_progress: List[JobCityProgress] = []


class JobSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    industry: str
    state: str
    cities: List[str]
    status: str
    total_clean: int = 0
    emails_found: int = 0
    created_at: datetime
    completed_at: Optional[datetime] = None


# ─────────────────────────────────────────────────────
# CLIENT-SAFE JOB SCHEMAS (Phase 2 — sanitized presentation layer)
# Never add current_step / current_city / city_progress / cities_done / cities_total /
# total_raw / emails_attempted / error_message to either model below — the whole point
# of this layer is that those fields structurally cannot leak to clients. Detailed
# internal telemetry stays available to Admins via the existing JobResponse/jobs routes.
# ─────────────────────────────────────────────────────
CLIENT_STATUS_MAP = {
    "pending":  "Submitted",
    "running":  "Processing",
    "done":     "Completed",
    "canceled": "Cancelled",
    "failed":   "Failed",
}


def to_client_status(internal_status: str) -> str:
    return CLIENT_STATUS_MAP.get(internal_status, "Processing")


class ClientBusinessRequestSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    industry: str
    state: str
    cities: List[str]
    status: str
    requested_quantity: int
    total_leads: Optional[int] = None
    emails_found: Optional[int] = None
    created_at: datetime
    completed_at: Optional[datetime] = None


class ClientBusinessRequestDetail(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    industry: str
    state: str
    cities: List[str]
    status: str
    requested_quantity: int
    created_at: datetime
    completed_at: Optional[datetime] = None
    message: str
    total_leads: Optional[int] = None
    with_website: Optional[int] = None
    no_website: Optional[int] = None
    emails_found: Optional[int] = None


# ─────────────────────────────────────────────────────
# CLIENT DASHBOARD SCHEMA (Phase 3)
# ─────────────────────────────────────────────────────
class RecentFileSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    name: str
    file_type: str
    created_at: datetime


class ClientDashboardResponse(BaseModel):
    # Plan / period
    plan_name: Optional[str] = None
    monthly_limit: Optional[int] = None
    subscription_status: Optional[str] = None
    package_renewal_date: Optional[datetime] = None
    cancel_at_period_end: Optional[bool] = None
    days_until_reset: Optional[int] = None

    # Usage this period
    leads_used_period: int = 0
    leads_remaining_period: int = 0
    pct_used: int = 0

    # Requests
    active_requests_count: int = 0
    completed_requests_count: int = 0
    cancelled_requests_count: int = 0
    failed_requests_count: int = 0
    leads_processing: int = 0  # same as active_requests_count, relabeled per the doc's KPI list

    # Lifetime aggregates
    total_with_website: int = 0
    total_no_website: int = 0
    total_emails_found: int = 0

    # People Leads (Phase 4) — lifetime delivered sum, and request counts (separate
    # from the business-only active/completed_requests_count above, since those feed
    # BusinessLeads.jsx tab badges and must keep matching `jobs` exactly)
    people_leads_delivered: Optional[int] = None
    people_requests_active: int = 0
    people_requests_completed: int = 0

    # Not backed by any table yet (My Leads is a later phase)
    total_lead_files: Optional[int] = None
    recent_files: List[RecentFileSummary] = []


# ─────────────────────────────────────────────────────
# PEOPLE LEADS SCHEMAS (Phase 4)
# Same sanitization discipline as the CLIENT-SAFE JOB SCHEMAS above: never expose
# internal_status, assigned_admin_id, raw targeting_filters_json, or organization_id
# on the client-facing models.
# ─────────────────────────────────────────────────────
LEAD_TYPES = (
    "property_owners", "absentee_owners", "vacant_property_owners",
    "high_equity_homeowners", "landowners", "other",
)

INTERNAL_PEOPLE_STATUSES = (
    "new", "assigned", "collecting_data", "cleaning_data", "awaiting_upload",
    "uploaded", "quality_review", "revision_required", "approved", "delivered", "cancelled",
)

PEOPLE_CLIENT_STATUS_MAP = {
    "new": "Submitted",
    "assigned": "Processing", "collecting_data": "Processing", "cleaning_data": "Processing",
    "awaiting_upload": "Processing", "uploaded": "Processing", "quality_review": "Processing",
    "approved": "Processing",
    "revision_required": "Needs Information",
    "delivered": "Completed",
    "cancelled": "Cancelled",
}


def to_people_client_status(internal_status: str) -> str:
    return PEOPLE_CLIENT_STATUS_MAP.get(internal_status, "Processing")


class CreatePeopleLeadRequest(BaseModel):
    request_name: str
    lead_type: str
    state: str
    city: Optional[str] = None
    county: Optional[str] = None
    zip_codes: List[str] = []
    requested_quantity: int
    client_instructions: Optional[str] = None
    # Structured business-targeting data from the "tell us about your
    # business" fields (business name/type, audience, filter stacks, full
    # city list) — stored client-side of targeting_filters_json under a
    # "targeting" key so it can't collide with the admin-revision-message
    # scratch key that same jsonb column already uses. See people_leads.py.
    targeting: Optional[Dict] = None

    @field_validator("lead_type")
    @classmethod
    def lead_type_valid(cls, v):
        if v not in LEAD_TYPES:
            raise ValueError(f"lead_type must be one of {LEAD_TYPES}")
        return v

    @field_validator("requested_quantity")
    @classmethod
    def quantity_positive(cls, v):
        if v <= 0:
            raise ValueError("requested_quantity must be positive")
        return v


class RespondPeopleLeadRequest(BaseModel):
    client_instructions: str


class ClientPeopleLeadRequestSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    request_name: str
    lead_type: str
    state: str
    city: Optional[str] = None
    requested_quantity: int
    delivered_quantity: int
    status: str
    created_at: datetime
    completed_at: Optional[datetime] = None
    # Only the client's own submitted targeting sub-object (never the raw
    # jsonb column — that could carry an admin-internal revision-message key).
    targeting: Optional[Dict] = None


class ClientPeopleLeadRequestDetail(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    request_name: str
    lead_type: str
    state: str
    city: Optional[str] = None
    county: Optional[str] = None
    zip_codes: List[str] = []
    requested_quantity: int
    delivered_quantity: int
    client_instructions: Optional[str] = None
    status: str
    created_at: datetime
    completed_at: Optional[datetime] = None
    message: str
    download_url: Optional[str] = None
    targeting: Optional[Dict] = None


# ── Admin-facing (can show internal fields) ──
class AssignRequest(BaseModel):
    admin_user_id: UUID


class AdminPeopleLeadPatch(BaseModel):
    internal_status: str
    admin_notes: Optional[str] = None

    @field_validator("internal_status")
    @classmethod
    def status_valid(cls, v):
        if v not in ("assigned", "collecting_data", "cleaning_data", "awaiting_upload"):
            raise ValueError(
                "PATCH may only set internal_status to assigned/collecting_data/"
                "cleaning_data/awaiting_upload — use the dedicated endpoint for other transitions"
            )
        return v


class ReviewDecisionRequest(BaseModel):
    decision: Literal["approve", "reject"]
    notes: Optional[str] = None


class DeliverRequest(BaseModel):
    delivered_quantity: Optional[int] = None


class RequestRevisionRequest(BaseModel):
    message: str


class AdminPeopleLeadFile(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    original_filename: str
    display_name: Optional[str] = None
    file_type: str
    file_size: int
    total_rows: int
    accepted_rows: int
    rejected_rows: int
    duplicate_rows: int
    email_count: int
    phone_count: int
    uploaded_by: UUID
    approved_by: Optional[UUID] = None
    delivered_at: Optional[datetime] = None
    created_at: datetime


class PeopleLeadFileUploadResponse(AdminPeopleLeadFile):
    pass


class AdminPeopleLeadRequestDetail(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    organization_id: UUID
    requested_by: UUID
    request_name: str
    lead_type: str
    state: str
    city: Optional[str] = None
    county: Optional[str] = None
    zip_codes: List[str] = []
    requested_quantity: int
    delivered_quantity: int
    targeting_filters_json: Dict = {}
    client_instructions: Optional[str] = None
    client_status: str
    internal_status: str
    assigned_admin_id: Optional[UUID] = None
    created_at: datetime
    updated_at: datetime
    completed_at: Optional[datetime] = None
    cancelled_at: Optional[datetime] = None
    files: List[AdminPeopleLeadFile] = []


class AdminPeopleLeadRequestSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    request_name: str
    lead_type: str
    state: str
    requested_quantity: int
    client_status: str
    internal_status: str
    assigned_admin_id: Optional[UUID] = None
    created_at: datetime


# ─────────────────────────────────────────────────────
# LEAD FILES SCHEMAS (Phase 5 — My Leads unified file index, §23.8/§13)
# request_name / original_filename are NOT stored columns on lead_files (§23.8's
# exact list omits them) — both are derived at read time in lead_files.py via a
# JOIN / basename extraction rather than denormalizing onto the table.
# ─────────────────────────────────────────────────────
class ChartSegment(BaseModel):
    """Generic (label, value) pair — the shape every non-time-series chart in this
    phase reduces to; matches DonutChart.jsx's `segments` prop (frontend assigns colors)."""
    label: str
    value: int


class LeadFileSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    source_type: str
    source_id: UUID
    file_category: str
    display_name: str
    request_name: Optional[str] = None
    original_filename: Optional[str] = None
    file_type: str
    file_size: Optional[int] = None
    record_count: int
    website_count: int
    email_count: int
    state: Optional[str] = None
    city: Optional[str] = None
    industry_or_category: Optional[str] = None
    created_at: datetime
    download_count: int
    last_downloaded_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None


class LeadFileDetail(LeadFileSummary):
    pass


class PatchLeadFile(BaseModel):
    display_name: str

    @field_validator("display_name")
    @classmethod
    def not_blank(cls, v):
        v = v.strip()
        if not v:
            raise ValueError("display_name cannot be blank")
        if len(v) > 200:
            raise ValueError("display_name too long (max 200 characters)")
        return v


class LeadFileStatsResponse(BaseModel):
    total_leads: int = 0
    total_files: int = 0
    business_leads: int = 0
    people_leads: int = 0
    businesses_with_website: int = 0
    businesses_without_website: int = 0
    emails_found: int = 0
    files_generated_this_month: int = 0
    email_found_pct: int = 0


class LeadFileChartsResponse(BaseModel):
    business_vs_people: List[ChartSegment] = []
    with_vs_without_website: List[ChartSegment] = []
    leads_by_state: List[ChartSegment] = []
    leads_by_industry: List[ChartSegment] = []


# ─────────────────────────────────────────────────────
# HISTORY SCHEMAS (Phase 5 — §14)
# ─────────────────────────────────────────────────────
class HistoryEntryResponse(BaseModel):
    id: UUID
    source_type: str  # 'business' | 'people'
    request_name: str
    lead_type_or_industry: str
    location: str
    requested_quantity: int
    delivered_quantity: int
    status: str
    created_at: datetime
    completed_at: Optional[datetime] = None


class HistoryStatsResponse(BaseModel):
    total_requests: int = 0
    completed_requests: int = 0
    active_requests: int = 0
    failed_requests: int = 0  # business-only; People Leads has no "Failed" state
    total_leads_generated: int = 0
    total_files_downloaded: int = 0


class HistoryChartsResponse(BaseModel):
    status_distribution: List[ChartSegment] = []
    business_vs_people: List[ChartSegment] = []
    most_requested_locations: List[ChartSegment] = []


# ─────────────────────────────────────────────────────
# TEAM / ORGANIZATION SCHEMAS (Phase 6)
# ─────────────────────────────────────────────────────
ORG_ROLES = ("account_owner", "client_admin", "client_member")
INVITABLE_ROLES = ("client_admin", "client_member")


class OrganizationResponse(BaseModel):
    id: UUID
    name: str
    my_role: str
    max_team_seats: Optional[int] = None
    seats_used: int = 0
    seats_remaining: Optional[int] = None
    created_at: datetime


class PatchOrganizationRequest(BaseModel):
    name: str


class OrganizationMemberResponse(BaseModel):
    id: UUID
    user_id: UUID
    email: str
    full_name: Optional[str] = None
    role: str
    created_at: datetime


class UpdateMemberRoleRequest(BaseModel):
    role: str

    @field_validator("role")
    @classmethod
    def role_invitable(cls, v):
        if v not in INVITABLE_ROLES:
            raise ValueError(f"role must be one of {INVITABLE_ROLES}")
        return v


class InvitationResponse(BaseModel):
    id: UUID
    email: str
    role: str
    status: str
    is_expired: bool = False
    expires_at: datetime
    created_at: datetime


class CreateInvitationRequest(BaseModel):
    email: str
    role: str

    @field_validator("role")
    @classmethod
    def role_invitable(cls, v):
        if v not in INVITABLE_ROLES:
            raise ValueError(f"role must be one of {INVITABLE_ROLES}")
        return v


class CreateInvitationResponse(BaseModel):
    invitation: InvitationResponse
    invite_link: str


class InvitationPreviewResponse(BaseModel):
    valid: bool
    reason: Optional[str] = None
    organization_name: Optional[str] = None
    role: Optional[str] = None
    email: Optional[str] = None


class AcceptInvitationRequest(BaseModel):
    password: str
    full_name: str


# ─────────────────────────────────────────────────────
# NOTIFICATION SCHEMAS (Phase 6, §19/§24.7)
# ─────────────────────────────────────────────────────
NOTIFICATION_CATEGORIES = ("business_updates", "people_updates", "billing_limits", "team", "support")


class NotificationResponse(BaseModel):
    id: UUID
    category: str
    type: str
    title: str
    body: str
    link_section: Optional[str] = None
    link_sub_tab: Optional[str] = None
    link_resource_id: Optional[str] = None
    is_read: bool
    created_at: datetime


class NotificationListResponse(BaseModel):
    items: List[NotificationResponse] = []
    unread_count: int = 0


class NotificationPreferencesResponse(BaseModel):
    muted_categories: List[str] = []
    email_enabled: bool = True


class PatchNotificationPreferencesRequest(BaseModel):
    muted_categories: List[str]
    email_enabled: bool

    @field_validator("muted_categories")
    @classmethod
    def categories_valid(cls, v):
        bad = set(v) - set(NOTIFICATION_CATEGORIES)
        if bad:
            raise ValueError(f"Unknown categories: {bad}")
        return v


# ─────────────────────────────────────────────────────
# BILLING EXPANSION SCHEMAS (Phase 6, §18)
# ─────────────────────────────────────────────────────
class InvoiceResponse(BaseModel):
    id: str
    amount_paid: Decimal
    currency: str
    status: str
    created_at: datetime
    invoice_pdf: Optional[str] = None
    hosted_invoice_url: Optional[str] = None


class PaymentMethodResponse(BaseModel):
    has_payment_method: bool = False
    brand: Optional[str] = None
    last4: Optional[str] = None
    exp_month: Optional[int] = None
    exp_year: Optional[int] = None


# ─────────────────────────────────────────────────────
# INTEGRATIONS SCHEMAS (Phase 6, §16/§23.12)
# ─────────────────────────────────────────────────────
INTEGRATION_KEYS = (
    "gohighlevel", "hubspot", "salesforce", "pipedrive", "zoho_crm",
    "google_sheets", "zapier", "make", "webhooks",
)


class IntegrationInterestResponse(BaseModel):
    integration_key: str
    created_at: datetime


# ─────────────────────────────────────────────────────
# SUPPORT SCHEMAS (Phase 7, §20/§24.8)
# Ticket creation and replies are multipart (Form + optional File) endpoints, matching
# admin_people_leads.py's upload_people_lead_file precedent — fields are validated
# manually in the router (category/linked_resource_type membership checks), not via a
# request-body Pydantic model. Only JSON-body admin actions (assign, patch) get models.
# ─────────────────────────────────────────────────────
SUPPORT_TICKET_CATEGORIES = (
    "business_leads", "people_leads", "billing", "account",
    "file_download", "data_quality", "technical_issue", "other",
)
SUPPORT_TICKET_STATUSES = ("open", "in_progress", "escalated", "resolved", "closed")
SUPPORT_TICKET_PRIORITIES = ("low", "normal", "high", "urgent")
SUPPORT_LINKED_RESOURCE_TYPES = ("business_request", "people_lead_request", "lead_file", "invoice")

_TICKET_CLOSED_BUCKET = {"resolved", "closed"}


def to_ticket_client_bucket(status: str) -> str:
    return "closed" if status in _TICKET_CLOSED_BUCKET else "open"


class SupportTicketAttachment(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    original_filename: str
    file_type: str
    file_size: int
    created_at: datetime


class ClientTicketMessage(BaseModel):
    id: UUID
    sender_is_admin: bool
    body: str
    created_at: datetime
    attachments: List[SupportTicketAttachment] = []


class ClientTicketSummary(BaseModel):
    id: UUID
    subject: str
    category: str
    status: str
    priority: str
    linked_resource_type: Optional[str] = None
    linked_resource_id: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class ClientTicketDetail(ClientTicketSummary):
    messages: List[ClientTicketMessage] = []


class AdminTicketMessage(BaseModel):
    id: UUID
    sender_user_id: UUID
    sender_is_admin: bool
    is_internal_note: bool
    body: str
    created_at: datetime
    attachments: List[SupportTicketAttachment] = []


class AdminTicketSummary(BaseModel):
    id: UUID
    organization_id: UUID
    created_by: UUID
    subject: str
    category: str
    status: str
    priority: str
    assigned_admin_id: Optional[UUID] = None
    linked_resource_type: Optional[str] = None
    linked_resource_id: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    resolved_at: Optional[datetime] = None
    closed_at: Optional[datetime] = None


class AdminTicketDetail(AdminTicketSummary):
    messages: List[AdminTicketMessage] = []


class AssignTicketRequest(BaseModel):
    admin_user_id: UUID


class AdminTicketPatch(BaseModel):
    status: Optional[str] = None
    priority: Optional[str] = None
    linked_resource_type: Optional[str] = None
    linked_resource_id: Optional[str] = None

    @field_validator("status")
    @classmethod
    def status_valid(cls, v):
        if v is not None and v not in SUPPORT_TICKET_STATUSES:
            raise ValueError(f"status must be one of {SUPPORT_TICKET_STATUSES}")
        return v

    @field_validator("priority")
    @classmethod
    def priority_valid(cls, v):
        if v is not None and v not in SUPPORT_TICKET_PRIORITIES:
            raise ValueError(f"priority must be one of {SUPPORT_TICKET_PRIORITIES}")
        return v

    @field_validator("linked_resource_type")
    @classmethod
    def linked_type_valid(cls, v):
        if v is not None and v not in SUPPORT_LINKED_RESOURCE_TYPES:
            raise ValueError(f"linked_resource_type must be one of {SUPPORT_LINKED_RESOURCE_TYPES}")
        return v


# ─────────────────────────────────────────────────────
# ADMIN DASHBOARD SCHEMAS (Phase 8 — Lean MVP)
# ─────────────────────────────────────────────────────
class AdminUserSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    email: str
    full_name: Optional[str] = None
    platform_role: str
    is_active: bool
    permissions: List[str] = []
    created_at: datetime


class AdminClientMember(BaseModel):
    user_id: UUID
    email: str
    full_name: Optional[str] = None
    role: str
    is_active: bool = True


class AdminClientSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    name: str
    owner_user_id: UUID
    owner_email: str
    owner_full_name: Optional[str] = None
    owner_is_active: bool = True
    plan_id: Optional[str] = None
    plan_name: Optional[str] = None
    subscription_status: Optional[str] = None
    seats_used: int = 0
    max_team_seats: Optional[int] = None
    created_at: datetime


class AdminClientDetail(AdminClientSummary):
    members: List[AdminClientMember] = []
    jobs_count: int = 0
    people_requests_count: int = 0
    lead_files_count: int = 0
    support_tickets_count: int = 0


class AdminPlanSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    name: str
    price_monthly: Decimal
    leads_per_month: int
    leads_per_day: int
    is_active: bool


class AdminJobSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    user_id: UUID
    requester_email: str
    organization_id: Optional[UUID] = None
    organization_name: Optional[str] = None
    industry: str
    state: str
    cities: List[str]
    status: str
    current_step: Optional[str] = None
    cities_done: int = 0
    cities_total: int = 0
    total_clean: int = 0
    with_website: int = 0
    no_website: int = 0
    emails_found: int = 0
    error_message: Optional[str] = None
    retry_count: int = 0
    created_at: datetime
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None


class AdminJobDetail(AdminJobSummary):
    city_progress: List[JobCityProgress] = []


class AdminLeadFileSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    organization_id: UUID
    organization_name: str
    user_id: UUID
    user_email: str
    source_type: str
    file_category: str
    display_name: str
    request_name: Optional[str] = None
    file_type: str
    file_size: Optional[int] = None
    record_count: int
    website_count: int
    email_count: int
    state: Optional[str] = None
    city: Optional[str] = None
    industry_or_category: Optional[str] = None
    created_at: datetime
    download_count: int
    last_downloaded_at: Optional[datetime] = None


class AdminLeadFileDetail(AdminLeadFileSummary):
    pass


class AdminAuditLogEntry(BaseModel):
    id: UUID
    actor_user_id: Optional[UUID] = None
    actor_email: Optional[str] = None
    actor_role: Optional[str] = None
    action: str
    resource_type: Optional[str] = None
    resource_id: Optional[str] = None
    previous_value_json: Optional[dict] = None
    new_value_json: Optional[dict] = None
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None
    created_at: datetime


class AdminDashboardResponse(BaseModel):
    total_clients: int = 0
    active_business_jobs: int = 0
    failed_business_jobs: int = 0
    pending_people_requests: int = 0
    open_support_tickets: int = 0
    total_leads_generated: int = 0
    requests_completed_today: int = 0
    active_admins_count: int = 0
    worker_last_seen_at: Optional[datetime] = None
    worker_status: str = "down"  # "healthy" | "degraded" | "down"


class AdminDashboardChartsResponse(BaseModel):
    business_vs_people: List[ChartSegment] = []
    business_job_status: List[ChartSegment] = []
    top_clients_by_leads: List[ChartSegment] = []
    tickets_by_status: List[ChartSegment] = []


# ─────────────────────────────────────────────────────
# CAMPAIGN ORGANIZER — stateless, no DB persistence. See
# app/campaign_organizer_logic.py / app/routers/campaign_organizer.py.
# ─────────────────────────────────────────────────────
class ChannelCounts(BaseModel):
    dialer: int = 0
    sms: int = 0
    email: int = 0


class CampaignDownload(BaseModel):
    group: str          # "marketing" | "properties" | "business"
    label: str
    filename: str
    content_base64: str


class PeopleLeadsProcessResponse(BaseModel):
    total_rows: int
    orig_phone_count: int
    orig_email_count: int
    campaign_name: str
    marketing_counts: Optional[ChannelCounts] = None
    properties_counts: Optional[ChannelCounts] = None
    downloads: List[CampaignDownload] = []


class BusinessLeadsProcessResponse(BaseModel):
    total_rows: int
    campaign_name: str
    download: CampaignDownload
    tickets_by_status: List[ChartSegment] = []
