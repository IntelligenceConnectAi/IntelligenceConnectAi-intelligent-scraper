"""
Admin-facing People Leads workflow (Phase 4):
  GET    /admin/people-leads/requests                  -> list  (people_leads_admin OR support_admin)
  GET    /admin/people-leads/requests/{id}              -> detail incl. files (same gate)
  PATCH  /admin/people-leads/requests/{id}              -> free-form status narration (people_leads_admin)
  POST   /admin/people-leads/requests/{id}/assign       (people_leads_admin)
  POST   /admin/people-leads/requests/{id}/upload       (people_leads_admin)
  POST   /admin/people-leads/requests/{id}/review       (support_admin)
  POST   /admin/people-leads/requests/{id}/deliver      (people_leads_admin)
  POST   /admin/people-leads/requests/{id}/request-revision  (people_leads_admin)

No dedicated admin frontend exists yet (Phase 8) — these are working API routes,
testable via /docs or curl, same precedent as Phase 1's admin-permission endpoints.

State-machine ownership (which endpoint owns which internal_status transition) is
documented in the Phase 4 plan — PATCH is deliberately restricted to the 4 statuses
with no required side effects; every other transition has a dedicated endpoint.
"""

import io
import json
import logging
import os
from typing import Annotated, Optional
from uuid import UUID

import pandas as pd
from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status

from app.audit import log_audit
from app.deps import DBConn
from app.leads_index import index_people_lead_file
from app.notifications import create_notification
from app.permissions import AdminDep, AdminPermissionsDep, RequireAdminPermission
from app.schemas import (
    AdminPeopleLeadFile,
    AdminPeopleLeadPatch,
    AdminPeopleLeadRequestDetail,
    AdminPeopleLeadRequestSummary,
    AssignRequest,
    DeliverRequest,
    PeopleLeadFileUploadResponse,
    RequestRevisionRequest,
    ReviewDecisionRequest,
    to_people_client_status,
)
from app.security_utils import (
    ALLOWED_UPLOAD_EXTENSIONS,
    MAX_UPLOAD_BYTES,
    UPLOAD_CONTENT_TYPES,
    is_valid_email,
    is_valid_phone,
    normalize_phone,
    safe_filename,
    sanitize_formula_injection,
)
from app.storage import upload_csv

log = logging.getLogger(__name__)
router = APIRouter()


async def RequirePeopleLeadsOrSupport(permissions: AdminPermissionsDep) -> list[str]:
    if not ({"people_leads_admin", "support_admin"} & set(permissions)):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Requires people_leads_admin or support_admin",
        )
    return permissions


def _load_json(value) -> dict:
    if isinstance(value, str):
        return json.loads(value) if value else {}
    return value or {}


async def _fetch_admin_detail(db, request_id: UUID) -> AdminPeopleLeadRequestDetail:
    row = await db.fetchrow("SELECT * FROM people_lead_requests WHERE id = $1", request_id)
    files = await db.fetch(
        "SELECT * FROM people_lead_files WHERE request_id = $1 ORDER BY created_at DESC", request_id
    )
    d = dict(row)
    d["targeting_filters_json"] = _load_json(d.get("targeting_filters_json"))
    return AdminPeopleLeadRequestDetail(**d, files=[AdminPeopleLeadFile(**dict(f)) for f in files])


COLUMN_ALIASES = {
    "name": {"name", "full_name", "fullname", "contact_name"},
    "phone": {"phone", "phone_number", "mobile", "cell", "telephone"},
    "email": {"email", "email_address"},
    "address": {"address", "street_address", "street"},
    "city": {"city"},
    "state": {"state"},
    "zip": {"zip", "zip_code", "zipcode", "postal_code"},
}


def match_columns(columns) -> dict:
    lower_cols = {str(c).strip().lower(): c for c in columns}
    result = {}
    for field, aliases in COLUMN_ALIASES.items():
        for alias in aliases:
            if alias in lower_cols:
                result[field] = lower_cols[alias]
                break
    return result


def validate_and_dedupe(df: pd.DataFrame, col_map: dict) -> tuple[int, int, int, int, int, int]:
    phone_col = col_map.get("phone")
    email_col = col_map.get("email")
    seen: set = set()
    total = len(df)
    accepted = rejected = duplicate = email_count = phone_count = 0

    for _, row in df.iterrows():
        raw_phone = str(row[phone_col]).strip() if phone_col and pd.notna(row.get(phone_col)) else ""
        raw_email = str(row[email_col]).strip() if email_col and pd.notna(row.get(email_col)) else ""

        phone_ok = bool(raw_phone) and is_valid_phone(raw_phone)
        email_ok = bool(raw_email) and is_valid_email(raw_email)

        if not phone_ok and not email_ok:
            rejected += 1
            continue

        key = (normalize_phone(raw_phone) if phone_ok else "", raw_email.lower() if email_ok else "")
        if key in seen:
            duplicate += 1
            continue
        seen.add(key)
        accepted += 1
        if phone_ok:
            phone_count += 1
        if email_ok:
            email_count += 1

    return total, accepted, rejected, duplicate, email_count, phone_count


@router.get("", response_model=list[AdminPeopleLeadRequestSummary])
async def list_admin_people_lead_requests(
    admin: AdminDep,
    permissions: Annotated[list[str], Depends(RequirePeopleLeadsOrSupport)],
    db: DBConn,
):
    rows = await db.fetch("SELECT * FROM people_lead_requests ORDER BY created_at DESC LIMIT 200")
    return [AdminPeopleLeadRequestSummary(**dict(r)) for r in rows]


@router.get("/{request_id}", response_model=AdminPeopleLeadRequestDetail)
async def get_admin_people_lead_request(
    request_id: UUID,
    admin: AdminDep,
    permissions: Annotated[list[str], Depends(RequirePeopleLeadsOrSupport)],
    db: DBConn,
):
    row = await db.fetchrow("SELECT id FROM people_lead_requests WHERE id = $1", request_id)
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Request not found")
    return await _fetch_admin_detail(db, request_id)


@router.patch("/{request_id}", response_model=AdminPeopleLeadRequestDetail)
async def patch_people_lead_request(
    request_id: UUID,
    body: AdminPeopleLeadPatch,
    admin: AdminDep,
    permissions: Annotated[list[str], Depends(RequireAdminPermission("people_leads_admin"))],
    db: DBConn,
    request: Request,
):
    row = await db.fetchrow("SELECT internal_status FROM people_lead_requests WHERE id = $1", request_id)
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Request not found")

    client_status = to_people_client_status(body.internal_status)
    await db.execute(
        "UPDATE people_lead_requests SET internal_status = $2, client_status = $3, updated_at = NOW() WHERE id = $1",
        request_id, body.internal_status, client_status,
    )
    await log_audit(
        db, actor_user_id=admin.id, actor_role=admin.platform_role,
        action="people_lead_request_patched", resource_type="people_lead_requests",
        resource_id=str(request_id), previous={"internal_status": row["internal_status"]},
        new={"internal_status": body.internal_status, "admin_notes": body.admin_notes}, request=request,
    )
    return await _fetch_admin_detail(db, request_id)


@router.post("/{request_id}/assign", response_model=AdminPeopleLeadRequestDetail)
async def assign_request(
    request_id: UUID,
    body: AssignRequest,
    admin: AdminDep,
    permissions: Annotated[list[str], Depends(RequireAdminPermission("people_leads_admin"))],
    db: DBConn,
    request: Request,
):
    row = await db.fetchrow("SELECT internal_status, request_name FROM people_lead_requests WHERE id = $1", request_id)
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Request not found")
    if row["internal_status"] != "new":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot assign a request with status '{row['internal_status']}'",
        )

    await db.execute(
        """
        UPDATE people_lead_requests
        SET assigned_admin_id = $2, internal_status = 'assigned', client_status = 'Processing', updated_at = NOW()
        WHERE id = $1
        """,
        request_id, body.admin_user_id,
    )
    await log_audit(
        db, actor_user_id=admin.id, actor_role=admin.platform_role,
        action="people_lead_request_assigned", resource_type="people_lead_requests",
        resource_id=str(request_id), new={"assigned_admin_id": str(body.admin_user_id)}, request=request,
    )

    try:
        await create_notification(
            db, user_id=body.admin_user_id, category="people_updates",
            type="people_request_assigned", title="People Leads request assigned to you",
            body=f"\"{row['request_name']}\" was assigned to you by {admin.email}.",
            link_section="people-requests", link_resource_id=str(request_id),
        )
    except Exception as notif_exc:
        log.error(f"Assignment notification failed for people lead request {request_id}: {notif_exc}", exc_info=True)

    return await _fetch_admin_detail(db, request_id)


@router.post("/{request_id}/upload", response_model=PeopleLeadFileUploadResponse)
async def upload_people_lead_file(
    request_id: UUID,
    admin: AdminDep,
    permissions: Annotated[list[str], Depends(RequireAdminPermission("people_leads_admin"))],
    db: DBConn,
    request: Request,
    file: UploadFile = File(...),
    display_name: Optional[str] = Form(None),
):
    req = await db.fetchrow(
        "SELECT organization_id, internal_status FROM people_lead_requests WHERE id = $1", request_id
    )
    if not req:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Request not found")
    if req["internal_status"] in ("delivered", "cancelled"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot upload to a request with status '{req['internal_status']}'",
        )

    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in ALLOWED_UPLOAD_EXTENSIONS:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Only .csv and .xlsx files are accepted")

    content = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"File exceeds {MAX_UPLOAD_BYTES // (1024 * 1024)}MB limit",
        )

    try:
        df = pd.read_csv(io.BytesIO(content)) if ext == ".csv" else pd.read_excel(io.BytesIO(content), engine="openpyxl")
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Could not parse file — check it is a valid CSV/Excel export",
        )

    col_map = match_columns(df.columns)
    if "phone" not in col_map and "email" not in col_map:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="File must contain at least a phone or email column")

    total, accepted, rejected, duplicate, email_count, phone_count = validate_and_dedupe(df, col_map)

    fname = safe_filename(file.filename)
    storage_path = f"{req['organization_id']}/people-leads/{request_id}/{fname}"
    await upload_csv(storage_path, content, content_type=UPLOAD_CONTENT_TYPES[ext.lstrip(".")])

    safe_display_name = sanitize_formula_injection(display_name) if display_name else None

    file_row = await db.fetchrow(
        """
        INSERT INTO people_lead_files
            (request_id, organization_id, storage_path, original_filename, display_name,
             file_type, file_size, total_rows, accepted_rows, rejected_rows, duplicate_rows,
             email_count, phone_count, uploaded_by)
        VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14)
        RETURNING *
        """,
        request_id, req["organization_id"], storage_path, file.filename, safe_display_name,
        ext.lstrip("."), len(content), total, accepted, rejected, duplicate,
        email_count, phone_count, admin.id,
    )

    await db.execute(
        "UPDATE people_lead_requests SET internal_status = 'quality_review', client_status = 'Processing', updated_at = NOW() WHERE id = $1",
        request_id,
    )
    await log_audit(
        db, actor_user_id=admin.id, actor_role=admin.platform_role,
        action="people_lead_file_uploaded", resource_type="people_lead_files",
        resource_id=str(file_row["id"]),
        new={"total_rows": total, "accepted_rows": accepted, "rejected_rows": rejected, "duplicate_rows": duplicate},
        request=request,
    )
    return PeopleLeadFileUploadResponse(**dict(file_row))


@router.post("/{request_id}/review", response_model=AdminPeopleLeadRequestDetail)
async def review_people_lead_request(
    request_id: UUID,
    body: ReviewDecisionRequest,
    admin: AdminDep,
    permissions: Annotated[list[str], Depends(RequireAdminPermission("support_admin"))],
    db: DBConn,
    request: Request,
):
    row = await db.fetchrow("SELECT internal_status FROM people_lead_requests WHERE id = $1", request_id)
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Request not found")
    if row["internal_status"] != "quality_review":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Request must be in quality_review to review (currently '{row['internal_status']}')",
        )

    if body.decision == "approve":
        new_internal = "approved"
        latest_file = await db.fetchrow(
            "SELECT id FROM people_lead_files WHERE request_id = $1 ORDER BY created_at DESC LIMIT 1", request_id
        )
        if latest_file:
            await db.execute("UPDATE people_lead_files SET approved_by = $2 WHERE id = $1", latest_file["id"], admin.id)
    else:
        new_internal = "cleaning_data"  # kicked back for admin rework — not a client-caused issue

    await db.execute(
        "UPDATE people_lead_requests SET internal_status = $2, client_status = 'Processing', updated_at = NOW() WHERE id = $1",
        request_id, new_internal,
    )
    await log_audit(
        db, actor_user_id=admin.id, actor_role=admin.platform_role,
        action=f"people_lead_review_{body.decision}", resource_type="people_lead_requests",
        resource_id=str(request_id), new={"notes": body.notes}, request=request,
    )
    return await _fetch_admin_detail(db, request_id)


@router.post("/{request_id}/deliver", response_model=AdminPeopleLeadRequestDetail)
async def deliver_people_lead_request(
    request_id: UUID,
    body: DeliverRequest,
    admin: AdminDep,
    permissions: Annotated[list[str], Depends(RequireAdminPermission("people_leads_admin"))],
    db: DBConn,
    request: Request,
):
    row = await db.fetchrow(
        "SELECT internal_status, requested_by, request_name FROM people_lead_requests WHERE id = $1", request_id
    )
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Request not found")
    if row["internal_status"] != "approved":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Request must be approved before delivery (currently '{row['internal_status']}')",
        )

    latest_file = await db.fetchrow(
        "SELECT id, accepted_rows FROM people_lead_files WHERE request_id = $1 ORDER BY created_at DESC LIMIT 1",
        request_id,
    )
    if not latest_file:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No uploaded file to deliver")

    delivered_quantity = body.delivered_quantity if body.delivered_quantity is not None else latest_file["accepted_rows"]

    await db.execute("UPDATE people_lead_files SET delivered_at = NOW() WHERE id = $1", latest_file["id"])
    await db.execute(
        """
        UPDATE people_lead_requests
        SET delivered_quantity = $2, internal_status = 'delivered', client_status = 'Completed',
            completed_at = NOW(), updated_at = NOW()
        WHERE id = $1
        """,
        request_id, delivered_quantity,
    )
    await log_audit(
        db, actor_user_id=admin.id, actor_role=admin.platform_role,
        action="people_lead_request_delivered", resource_type="people_lead_requests",
        resource_id=str(request_id), new={"delivered_quantity": delivered_quantity}, request=request,
    )

    # ── Phase 5 hook (§27): best-effort indexing into the unified library. ──
    try:
        await index_people_lead_file(db, request_id=request_id)
    except Exception as idx_exc:
        log.error(f"Lead-file indexing failed for people lead request {request_id}: {idx_exc}", exc_info=True)

    # ── Phase 6 hook (§19/§27): single notification also covers "file delivered" —
    # the doc requires deep-linking, not a literal second notification for one event. ──
    try:
        await create_notification(
            db, user_id=row["requested_by"], category="people_updates",
            type="people_request_completed", title="People Leads request completed",
            body=f"Your \"{row['request_name']}\" request is ready — {delivered_quantity} leads delivered.",
            link_section="my-leads",
        )
    except Exception as notif_exc:
        log.error(f"Completion notification failed for people lead request {request_id}: {notif_exc}", exc_info=True)

    return await _fetch_admin_detail(db, request_id)


@router.post("/{request_id}/request-revision", response_model=AdminPeopleLeadRequestDetail)
async def request_revision(
    request_id: UUID,
    body: RequestRevisionRequest,
    admin: AdminDep,
    permissions: Annotated[list[str], Depends(RequireAdminPermission("people_leads_admin"))],
    db: DBConn,
    request: Request,
):
    row = await db.fetchrow(
        "SELECT internal_status, requested_by, request_name FROM people_lead_requests WHERE id = $1", request_id
    )
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Request not found")
    if row["internal_status"] in ("delivered", "cancelled"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot request revision on a request with status '{row['internal_status']}'",
        )

    safe_message = sanitize_formula_injection(body.message)
    await db.execute(
        """
        UPDATE people_lead_requests
        SET internal_status = 'revision_required', client_status = 'Needs Information',
            targeting_filters_json = targeting_filters_json || $2::jsonb, updated_at = NOW()
        WHERE id = $1
        """,
        request_id, json.dumps({"admin_revision_message": safe_message}),
    )
    await log_audit(
        db, actor_user_id=admin.id, actor_role=admin.platform_role,
        action="people_lead_request_revision_requested", resource_type="people_lead_requests",
        resource_id=str(request_id), new={"message": safe_message}, request=request,
    )

    try:
        await create_notification(
            db, user_id=row["requested_by"], category="people_updates",
            type="people_request_needs_info", title="People Leads request needs information",
            body=f"Your \"{row['request_name']}\" request needs more information: {safe_message}",
            link_section="get-leads", link_sub_tab="people",
        )
    except Exception as notif_exc:
        log.error(f"Needs-info notification failed for people lead request {request_id}: {notif_exc}", exc_info=True)

    return await _fetch_admin_detail(db, request_id)
