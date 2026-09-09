"""
Admin-facing Support Ticket endpoints (Phase 7, §20/§24.8):
  GET    /admin/support/tickets                          -> list, optional filters
  GET    /admin/support/tickets/{id}                      -> detail incl. internal notes
  PATCH  /admin/support/tickets/{id}                      -> status/priority/linked resource
  POST   /admin/support/tickets/{id}/assign
  POST   /admin/support/tickets/{id}/internal-notes       -> never visible to the client
  POST   /admin/support/tickets/{id}/messages             -> client-visible reply, fires
                                                              the one and only support_response
                                                              notification trigger site
  GET    /admin/support/tickets/{id}/attachments/{aid}/download

Every route gated by RequireAdminPermission("support_admin") only — a single
permission owns this whole area per the doc's §4.5 ("Support Admin also owns all
data-quality responsibilities... there is no separate Data Quality Admin"), unlike
Phase 4's dual-gated RequirePeopleLeadsOrSupport (which existed for a Phase-4-specific
reason that doesn't apply here).

No dedicated admin frontend exists yet (Phase 8) — these are working API routes,
testable via /docs or curl, same precedent as Phase 1's admin-permission endpoints
and Phase 4's admin_people_leads.py.
"""

import logging
from datetime import datetime, timezone
from typing import Annotated, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi import status as http_status

from app.audit import log_audit
from app.deps import DBConn
from app.notifications import create_notification
from app.permissions import AdminDep, RequireAdminPermission
from app.schemas import (
    AdminTicketDetail,
    AdminTicketMessage,
    AdminTicketPatch,
    AdminTicketSummary,
    AssignTicketRequest,
    SupportTicketAttachment,
)
from app.security_utils import sanitize_formula_injection
from app.storage import get_signed_url
from app.support_utils import save_ticket_attachment, validate_linked_resource

log = logging.getLogger(__name__)
router = APIRouter()

RequireSupportAdmin = Annotated[list[str], Depends(RequireAdminPermission("support_admin"))]


async def _fetch_admin_detail(db, ticket_id: UUID) -> AdminTicketDetail:
    ticket = await db.fetchrow("SELECT * FROM support_tickets WHERE id = $1", ticket_id)
    message_rows = await db.fetch(
        "SELECT * FROM support_ticket_messages WHERE ticket_id = $1 ORDER BY created_at ASC", ticket_id
    )
    messages = []
    for m in message_rows:
        att_rows = await db.fetch("SELECT * FROM support_ticket_attachments WHERE message_id = $1", m["id"])
        messages.append(AdminTicketMessage(**dict(m), attachments=[SupportTicketAttachment(**dict(a)) for a in att_rows]))
    return AdminTicketDetail(**dict(ticket), messages=messages)


@router.get("", response_model=list[AdminTicketSummary])
async def list_admin_tickets(
    admin: AdminDep,
    permissions: RequireSupportAdmin,
    db: DBConn,
    ticket_status: Optional[str] = None,
    category: Optional[str] = None,
    assigned_admin_id: Optional[UUID] = None,
):
    conditions, params = [], []
    if ticket_status:
        params.append(ticket_status)
        conditions.append(f"status = ${len(params)}")
    if category:
        params.append(category)
        conditions.append(f"category = ${len(params)}")
    if assigned_admin_id:
        params.append(assigned_admin_id)
        conditions.append(f"assigned_admin_id = ${len(params)}")
    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    rows = await db.fetch(f"SELECT * FROM support_tickets {where} ORDER BY created_at DESC LIMIT 200", *params)
    return [AdminTicketSummary(**dict(r)) for r in rows]


@router.get("/{ticket_id}", response_model=AdminTicketDetail)
async def get_admin_ticket(ticket_id: UUID, admin: AdminDep, permissions: RequireSupportAdmin, db: DBConn):
    ticket = await db.fetchrow("SELECT id FROM support_tickets WHERE id = $1", ticket_id)
    if not ticket:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail="Ticket not found")
    return await _fetch_admin_detail(db, ticket_id)


@router.patch("/{ticket_id}", response_model=AdminTicketDetail)
async def patch_ticket(
    ticket_id: UUID,
    body: AdminTicketPatch,
    admin: AdminDep,
    permissions: RequireSupportAdmin,
    db: DBConn,
    request: Request,
):
    ticket = await db.fetchrow("SELECT * FROM support_tickets WHERE id = $1", ticket_id)
    if not ticket:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail="Ticket not found")

    new_status = body.status or ticket["status"]
    new_priority = body.priority or ticket["priority"]
    new_linked_type = ticket["linked_resource_type"]
    new_linked_id = ticket["linked_resource_id"]
    if body.linked_resource_type is not None or body.linked_resource_id is not None:
        new_linked_type = body.linked_resource_type
        new_linked_id = await validate_linked_resource(
            db, resource_type=body.linked_resource_type, resource_id=body.linked_resource_id,
            org_id=ticket["organization_id"],
        )

    resolved_at = ticket["resolved_at"]
    closed_at = ticket["closed_at"]
    if new_status == "resolved" and ticket["status"] != "resolved":
        resolved_at = datetime.now(timezone.utc)
    elif new_status == "closed" and ticket["status"] != "closed":
        closed_at = datetime.now(timezone.utc)
    elif new_status not in ("resolved", "closed"):
        resolved_at = None
        closed_at = None

    await db.execute(
        """
        UPDATE support_tickets
        SET status = $2, priority = $3, linked_resource_type = $4, linked_resource_id = $5,
            resolved_at = $6, closed_at = $7, updated_at = NOW()
        WHERE id = $1
        """,
        ticket_id, new_status, new_priority, new_linked_type, new_linked_id, resolved_at, closed_at,
    )
    await log_audit(
        db, actor_user_id=admin.id, actor_role=admin.platform_role,
        action="support_ticket_patched", resource_type="support_tickets", resource_id=str(ticket_id),
        previous={"status": ticket["status"], "priority": ticket["priority"]},
        new={"status": new_status, "priority": new_priority}, request=request,
    )
    return await _fetch_admin_detail(db, ticket_id)


@router.post("/{ticket_id}/assign", response_model=AdminTicketDetail)
async def assign_ticket(
    ticket_id: UUID,
    body: AssignTicketRequest,
    admin: AdminDep,
    permissions: RequireSupportAdmin,
    db: DBConn,
    request: Request,
):
    ticket = await db.fetchrow("SELECT id FROM support_tickets WHERE id = $1", ticket_id)
    if not ticket:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail="Ticket not found")

    await db.execute(
        "UPDATE support_tickets SET assigned_admin_id = $2, updated_at = NOW() WHERE id = $1",
        ticket_id, body.admin_user_id,
    )
    await log_audit(
        db, actor_user_id=admin.id, actor_role=admin.platform_role,
        action="support_ticket_assigned", resource_type="support_tickets", resource_id=str(ticket_id),
        new={"assigned_admin_id": str(body.admin_user_id)}, request=request,
    )
    return await _fetch_admin_detail(db, ticket_id)


@router.post("/{ticket_id}/internal-notes", response_model=AdminTicketMessage, status_code=http_status.HTTP_201_CREATED)
async def add_internal_note(
    ticket_id: UUID,
    admin: AdminDep,
    permissions: RequireSupportAdmin,
    db: DBConn,
    body: str = Form(...),
    file: Optional[UploadFile] = File(None),
):
    ticket = await db.fetchrow("SELECT organization_id FROM support_tickets WHERE id = $1", ticket_id)
    if not ticket:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail="Ticket not found")

    message = await db.fetchrow(
        """
        INSERT INTO support_ticket_messages (ticket_id, sender_user_id, sender_is_admin, is_internal_note, body)
        VALUES ($1,$2,true,true,$3)
        RETURNING *
        """,
        ticket_id, admin.id, sanitize_formula_injection(body.strip()),
    )
    attachments = []
    if file is not None:
        attachments.append(await save_ticket_attachment(
            db, ticket_id=ticket_id, message_id=message["id"], uploaded_by=admin.id,
            org_id=ticket["organization_id"], file=file,
        ))
    return AdminTicketMessage(**dict(message), attachments=attachments)


@router.post("/{ticket_id}/messages", response_model=AdminTicketMessage, status_code=http_status.HTTP_201_CREATED)
async def admin_reply_to_ticket(
    ticket_id: UUID,
    admin: AdminDep,
    permissions: RequireSupportAdmin,
    db: DBConn,
    body: str = Form(...),
    file: Optional[UploadFile] = File(None),
):
    ticket = await db.fetchrow(
        "SELECT organization_id, created_by, subject FROM support_tickets WHERE id = $1", ticket_id
    )
    if not ticket:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail="Ticket not found")

    message = await db.fetchrow(
        """
        INSERT INTO support_ticket_messages (ticket_id, sender_user_id, sender_is_admin, is_internal_note, body)
        VALUES ($1,$2,true,false,$3)
        RETURNING *
        """,
        ticket_id, admin.id, sanitize_formula_injection(body.strip()),
    )
    await db.execute("UPDATE support_tickets SET updated_at = NOW() WHERE id = $1", ticket_id)

    attachments = []
    if file is not None:
        attachments.append(await save_ticket_attachment(
            db, ticket_id=ticket_id, message_id=message["id"], uploaded_by=admin.id,
            org_id=ticket["organization_id"], file=file,
        ))

    # First and only trigger site for "support_response" (Phase 6 added the type
    # with no trigger yet). Isolated try/except — never able to fail the reply itself.
    try:
        await create_notification(
            db, user_id=ticket["created_by"], category="support", type="support_response",
            title="New reply to your support ticket",
            body=f"Support replied to \"{ticket['subject']}\".",
            link_section="support",
        )
    except Exception as notif_exc:
        log.error(f"Support-response notification failed for ticket {ticket_id}: {notif_exc}", exc_info=True)

    return AdminTicketMessage(**dict(message), attachments=attachments)


@router.get("/{ticket_id}/attachments/{attachment_id}/download")
async def download_admin_attachment(
    ticket_id: UUID, attachment_id: UUID, admin: AdminDep, permissions: RequireSupportAdmin, db: DBConn,
):
    row = await db.fetchrow(
        "SELECT storage_path FROM support_ticket_attachments WHERE id = $1 AND ticket_id = $2",
        attachment_id, ticket_id,
    )
    if not row:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail="Attachment not found")

    signed_url = await get_signed_url(row["storage_path"], expires_in=3600)
    return {"url": signed_url, "expires_in": 3600}
