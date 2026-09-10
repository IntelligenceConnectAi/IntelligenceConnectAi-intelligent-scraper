"""
Client-facing People Leads endpoints (Phase 4):
  POST   /people-leads/requests            -> create + queue
  GET    /people-leads/requests            -> list (org-wide, not just requested_by)
  GET    /people-leads/requests/{id}       -> detail (+ download_url once Completed)
  POST   /people-leads/requests/{id}/cancel
  POST   /people-leads/requests/{id}/respond  -> only valid when status is "Needs Information"

Scoped by organization_id, not requested_by — the doc's client-role definitions
(§5.1-5.3) all say members can "view organization requests", and people_lead_requests
is explicitly organization-scoped in its own schema (§23.6), unlike `jobs` which is
per-user. Every user has exactly one org today (Phase 1), so this is forward-looking
for when Team invites let multiple people share one.

client_status is a REAL STORED COLUMN here (unlike jobs.status, which is mapped to a
client-safe string at read-time) — every internal_status transition in
admin_people_leads.py must set both columns together, or they'll drift.
"""

import json
import logging
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request, status

from app.audit import log_audit
from app.deps import CurrentUserDep, DBConn, get_current_org_id
from app.leads_usage import get_leads_used_period
from app.notifications import create_notification, notify_admins_with_permission
from app.org_access import get_billing_owner_id
from app.schemas import (
    ClientPeopleLeadRequestDetail,
    ClientPeopleLeadRequestSummary,
    CreatePeopleLeadRequest,
    RespondPeopleLeadRequest,
)
from app.security_utils import sanitize_formula_injection
from app.storage import get_signed_url

log = logging.getLogger(__name__)
router = APIRouter()

GENERIC_MESSAGES = {
    "Submitted": (
        "Your request has been submitted successfully. Our data team is preparing your lead list, "
        "and the completed file will be added to your account within 24 hours. We will notify you "
        "as soon as it is ready."
    ),
    "Processing": (
        "Our data team is preparing your lead list, and the completed file will be added to your "
        "account within 24 hours. We will notify you as soon as it is ready."
    ),
    "Needs Information": (
        "We need a bit more information from you to continue processing this request. "
        "Please review the note below and respond."
    ),
    "Completed": "Your request is complete. Your lead file is ready to download.",
    "Cancelled": "This request was cancelled.",
}


def _load_json(value) -> dict:
    if isinstance(value, str):
        return json.loads(value) if value else {}
    return value or {}


def _build_detail(row: dict, download_url: Optional[str] = None) -> ClientPeopleLeadRequestDetail:
    client_status = row["client_status"]
    message = GENERIC_MESSAGES.get(client_status, GENERIC_MESSAGES["Processing"])
    if client_status == "Needs Information":
        note = _load_json(row.get("targeting_filters_json")).get("admin_revision_message")
        if note:
            message = f"{message} {note}"
    return ClientPeopleLeadRequestDetail(
        id=row["id"], request_name=row["request_name"], lead_type=row["lead_type"],
        state=row["state"], city=row["city"], county=row["county"], zip_codes=row["zip_codes"],
        requested_quantity=row["requested_quantity"], delivered_quantity=row["delivered_quantity"],
        client_instructions=row["client_instructions"], status=client_status,
        created_at=row["created_at"], completed_at=row["completed_at"],
        message=message, download_url=download_url,
        targeting=_load_json(row.get("targeting_filters_json")).get("targeting"),
    )


@router.post("", response_model=ClientPeopleLeadRequestDetail, status_code=status.HTTP_201_CREATED)
async def create_people_lead_request(
    body: CreatePeopleLeadRequest, user: CurrentUserDep, db: DBConn, request: Request,
):
    # Non-owner team members have no personal `subscriptions` row (it's strictly
    # one-per-individual) — fall back to the org owner's plan for the existence/
    # limit check. See the Phase 6 plan's "non-owner request submission is
    # intentionally partial" section for why this fix applies here but not to
    # jobs.py's daily-limit gate.
    org_id = await get_current_org_id(db, user.id)
    billing_user_id = await get_billing_owner_id(db, user.id, org_id)

    # Company staff (platform admins) submit People Leads requests without the
    # monthly-lead-limit / subscription gate — matches jobs.py::create_job.
    privileged = user.platform_role in ("admin", "super_admin")

    if not privileged:
        plan_row = await db.fetchrow(
            """
            SELECT p.leads_per_month AS monthly_limit, s.current_period_end
            FROM subscriptions s JOIN plans p ON p.id = s.plan_id
            WHERE s.user_id = $1 AND s.status = 'active'
            """,
            billing_user_id,
        )
        if not plan_row:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="No active subscription. Please subscribe to a plan.",
            )

        monthly_limit = plan_row["monthly_limit"]
        used = await get_leads_used_period(db, user.id, org_id, plan_row["current_period_end"])
        if monthly_limit and used + body.requested_quantity > monthly_limit:
            remaining = max(monthly_limit - used, 0)
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"This request would exceed your monthly lead limit. {remaining} leads remaining this period.",
            )

    instructions = sanitize_formula_injection(body.client_instructions) if body.client_instructions else None
    # Namespaced under "targeting" so it can never collide with the
    # admin_revision_message scratch key the same jsonb column already uses
    # (request_revision writes it via `||`, respond deletes it via `- 'key'` —
    # both non-destructive to sibling keys).
    targeting_payload = {"targeting": body.targeting} if body.targeting else {}

    row = await db.fetchrow(
        """
        INSERT INTO people_lead_requests
            (organization_id, requested_by, request_name, lead_type, state, city, county,
             zip_codes, requested_quantity, client_instructions, targeting_filters_json,
             client_status, internal_status)
        VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11::jsonb,'Submitted','new')
        RETURNING *
        """,
        org_id, user.id, body.request_name.strip(), body.lead_type, body.state.strip(),
        body.city.strip() if body.city else None, body.county.strip() if body.county else None,
        body.zip_codes, body.requested_quantity, instructions, json.dumps(targeting_payload),
    )

    await log_audit(
        db, actor_user_id=user.id, actor_role=user.platform_role,
        action="people_lead_request_created", resource_type="people_lead_requests",
        resource_id=str(row["id"]),
        new={"request_name": row["request_name"], "requested_quantity": row["requested_quantity"]},
        request=request,
    )

    try:
        await create_notification(
            db, user_id=user.id, category="people_updates",
            type="people_request_submitted", title="People Leads request submitted",
            body=f"Your \"{row['request_name']}\" request has been submitted.",
            link_section="get-leads", link_sub_tab="people",
        )
    except Exception as notif_exc:
        log.error(f"Submission notification failed for people lead request {row['id']}: {notif_exc}", exc_info=True)

    # Every people_leads_admin (+ super admins) gets pinged so a new request
    # doesn't just sit unnoticed until someone happens to open the list —
    # mirrors support.py's identical new-ticket pattern.
    try:
        org_name = await db.fetchval("SELECT name FROM organizations WHERE id = $1", org_id)
        await notify_admins_with_permission(
            db, permission_key="people_leads_admin",
            category="people_updates", type="new_people_request",
            title="New People Leads request",
            body=f"{org_name} ({user.email}) submitted a new request: \"{row['request_name']}\" ({row['requested_quantity']} leads).",
            link_section="people-requests", link_resource_id=str(row["id"]),
        )
    except Exception as notif_exc:
        log.error(f"Admin new-request notification failed for people lead request {row['id']}: {notif_exc}", exc_info=True)

    return _build_detail(dict(row))


@router.get("", response_model=list[ClientPeopleLeadRequestSummary])
async def list_people_lead_requests(user: CurrentUserDep, db: DBConn):
    org_id = await get_current_org_id(db, user.id)
    rows = await db.fetch(
        "SELECT * FROM people_lead_requests WHERE organization_id = $1 ORDER BY created_at DESC LIMIT 100",
        org_id,
    )
    return [
        ClientPeopleLeadRequestSummary(
            id=r["id"], request_name=r["request_name"], lead_type=r["lead_type"], state=r["state"],
            city=r["city"], requested_quantity=r["requested_quantity"],
            delivered_quantity=r["delivered_quantity"], status=r["client_status"],
            created_at=r["created_at"], completed_at=r["completed_at"],
            targeting=_load_json(r.get("targeting_filters_json")).get("targeting"),
        )
        for r in rows
    ]


@router.get("/{request_id}", response_model=ClientPeopleLeadRequestDetail)
async def get_people_lead_request(request_id: UUID, user: CurrentUserDep, db: DBConn):
    org_id = await get_current_org_id(db, user.id)
    row = await db.fetchrow(
        "SELECT * FROM people_lead_requests WHERE id = $1 AND organization_id = $2",
        request_id, org_id,
    )
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Request not found")

    download_url = None
    if row["client_status"] == "Completed":
        file_row = await db.fetchrow(
            "SELECT storage_path FROM people_lead_files WHERE request_id = $1 ORDER BY created_at DESC LIMIT 1",
            request_id,
        )
        if file_row:
            download_url = await get_signed_url(file_row["storage_path"], expires_in=3600)

    return _build_detail(dict(row), download_url=download_url)


@router.post("/{request_id}/cancel")
async def cancel_people_lead_request(request_id: UUID, user: CurrentUserDep, db: DBConn, request: Request):
    org_id = await get_current_org_id(db, user.id)
    row = await db.fetchrow(
        "SELECT id, internal_status FROM people_lead_requests WHERE id = $1 AND organization_id = $2",
        request_id, org_id,
    )
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Request not found")
    if row["internal_status"] in ("delivered", "cancelled"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot cancel a request with status '{row['internal_status']}'",
        )

    await db.execute(
        """
        UPDATE people_lead_requests
        SET internal_status = 'cancelled', client_status = 'Cancelled', cancelled_at = NOW(), updated_at = NOW()
        WHERE id = $1
        """,
        request_id,
    )
    await log_audit(
        db, actor_user_id=user.id, actor_role=user.platform_role,
        action="people_lead_request_cancelled", resource_type="people_lead_requests",
        resource_id=str(request_id), request=request,
    )
    return {"message": "Request cancelled"}


@router.post("/{request_id}/respond", response_model=ClientPeopleLeadRequestDetail)
async def respond_people_lead_request(
    request_id: UUID, body: RespondPeopleLeadRequest, user: CurrentUserDep, db: DBConn, request: Request,
):
    org_id = await get_current_org_id(db, user.id)
    row = await db.fetchrow(
        "SELECT * FROM people_lead_requests WHERE id = $1 AND organization_id = $2",
        request_id, org_id,
    )
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Request not found")
    if row["internal_status"] != "revision_required":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="This request is not awaiting a response")

    new_instructions = sanitize_formula_injection(body.client_instructions)
    combined = f"{row['client_instructions']}\n\n---\n{new_instructions}" if row["client_instructions"] else new_instructions

    updated = await db.fetchrow(
        """
        UPDATE people_lead_requests
        SET client_instructions = $2, internal_status = 'collecting_data', client_status = 'Processing',
            targeting_filters_json = targeting_filters_json - 'admin_revision_message', updated_at = NOW()
        WHERE id = $1
        RETURNING *
        """,
        request_id, combined,
    )
    await log_audit(
        db, actor_user_id=user.id, actor_role=user.platform_role,
        action="people_lead_request_responded", resource_type="people_lead_requests",
        resource_id=str(request_id), request=request,
    )
    return _build_detail(dict(updated))
