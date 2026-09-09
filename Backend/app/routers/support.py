"""
Client-facing Support Ticket endpoints (Phase 7, §20/§24.8):
  POST   /support/tickets                              -> create + first message
  GET    /support/tickets                               -> list (org-wide), ?bucket=open|closed
  GET    /support/tickets/{id}                          -> detail + client-visible thread
  POST   /support/tickets/{id}/messages                 -> reply (+ optional attachment)
  GET    /support/tickets/{id}/attachments/{aid}/download -> signed URL, generated on click

Org-scoped, not created_by-scoped — matches people_leads.py's precedent (any active
member can see/reply to any ticket in their org). Internal notes are filtered out of
the thread at the SQL level in get_ticket, never fetched then hidden.
"""

import logging
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile, status

from app.audit import log_audit
from app.deps import CurrentUserDep, DBConn, get_current_org_id
from app.notifications import notify_admins_with_permission
from app.schemas import (
    SUPPORT_LINKED_RESOURCE_TYPES,
    SUPPORT_TICKET_CATEGORIES,
    ClientTicketDetail,
    ClientTicketMessage,
    ClientTicketSummary,
    SupportTicketAttachment,
    to_ticket_client_bucket,
)
from app.security_utils import sanitize_formula_injection
from app.storage import get_signed_url
from app.support_utils import save_ticket_attachment, validate_linked_resource

log = logging.getLogger(__name__)
router = APIRouter()


@router.post("", response_model=ClientTicketDetail, status_code=status.HTTP_201_CREATED)
async def create_ticket(
    user: CurrentUserDep,
    db: DBConn,
    request: Request,
    subject: str = Form(...),
    category: str = Form(...),
    body: str = Form(...),
    linked_resource_type: Optional[str] = Form(None),
    linked_resource_id: Optional[str] = Form(None),
    file: Optional[UploadFile] = File(None),
):
    if category not in SUPPORT_TICKET_CATEGORIES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"category must be one of {SUPPORT_TICKET_CATEGORIES}",
        )
    if linked_resource_type and linked_resource_type not in SUPPORT_LINKED_RESOURCE_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"linked_resource_type must be one of {SUPPORT_LINKED_RESOURCE_TYPES}",
        )

    org_id = await get_current_org_id(db, user.id)
    resolved_resource_id = await validate_linked_resource(
        db, resource_type=linked_resource_type, resource_id=linked_resource_id, org_id=org_id
    )

    subject_clean = sanitize_formula_injection(subject.strip()[:200])
    body_clean = sanitize_formula_injection(body.strip())

    async with db.transaction():
        ticket = await db.fetchrow(
            """
            INSERT INTO support_tickets
                (organization_id, created_by, subject, category, linked_resource_type, linked_resource_id)
            VALUES ($1,$2,$3,$4,$5,$6)
            RETURNING *
            """,
            org_id, user.id, subject_clean, category, linked_resource_type, resolved_resource_id,
        )
        message = await db.fetchrow(
            """
            INSERT INTO support_ticket_messages (ticket_id, sender_user_id, sender_is_admin, is_internal_note, body)
            VALUES ($1,$2,false,false,$3)
            RETURNING *
            """,
            ticket["id"], user.id, body_clean,
        )

    org_name = await db.fetchval("SELECT name FROM organizations WHERE id = $1", org_id)
    try:
        await notify_admins_with_permission(
            db, permission_key="support_admin",
            category="support", type="new_support_ticket",
            title="New support ticket",
            body=f"{org_name} ({user.email}) opened a new ticket: \"{subject_clean}\" ({category}).",
            link_section="support", link_resource_id=str(ticket["id"]),
        )
    except Exception as e:
        log.error(f"admin new-ticket notification failed for ticket {ticket['id']}: {e}", exc_info=True)

    attachments = []
    if file is not None:
        attachments.append(await save_ticket_attachment(
            db, ticket_id=ticket["id"], message_id=message["id"], uploaded_by=user.id, org_id=org_id, file=file
        ))

    await log_audit(
        db, actor_user_id=user.id, actor_role=user.platform_role,
        action="support_ticket_created", resource_type="support_tickets", resource_id=str(ticket["id"]),
        new={"subject": subject_clean, "category": category}, request=request,
    )

    return ClientTicketDetail(**dict(ticket), messages=[ClientTicketMessage(**dict(message), attachments=attachments)])


@router.get("", response_model=list[ClientTicketSummary])
async def list_tickets(user: CurrentUserDep, db: DBConn, bucket: Optional[str] = None):
    org_id = await get_current_org_id(db, user.id)
    rows = await db.fetch(
        "SELECT * FROM support_tickets WHERE organization_id = $1 ORDER BY created_at DESC LIMIT 200",
        org_id,
    )
    tickets = [ClientTicketSummary(**dict(r)) for r in rows]
    if bucket in ("open", "closed"):
        tickets = [t for t in tickets if to_ticket_client_bucket(t.status) == bucket]
    return tickets


@router.get("/{ticket_id}", response_model=ClientTicketDetail)
async def get_ticket(ticket_id: UUID, user: CurrentUserDep, db: DBConn):
    org_id = await get_current_org_id(db, user.id)
    ticket = await db.fetchrow(
        "SELECT * FROM support_tickets WHERE id = $1 AND organization_id = $2", ticket_id, org_id
    )
    if not ticket:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ticket not found")

    message_rows = await db.fetch(
        "SELECT * FROM support_ticket_messages WHERE ticket_id = $1 AND is_internal_note = false ORDER BY created_at ASC",
        ticket_id,
    )
    messages = []
    for m in message_rows:
        att_rows = await db.fetch("SELECT * FROM support_ticket_attachments WHERE message_id = $1", m["id"])
        messages.append(ClientTicketMessage(**dict(m), attachments=[SupportTicketAttachment(**dict(a)) for a in att_rows]))

    return ClientTicketDetail(**dict(ticket), messages=messages)


@router.post("/{ticket_id}/messages", response_model=ClientTicketMessage, status_code=status.HTTP_201_CREATED)
async def reply_to_ticket(
    ticket_id: UUID,
    user: CurrentUserDep,
    db: DBConn,
    body: str = Form(...),
    file: Optional[UploadFile] = File(None),
):
    org_id = await get_current_org_id(db, user.id)
    ticket = await db.fetchrow(
        "SELECT id, status FROM support_tickets WHERE id = $1 AND organization_id = $2", ticket_id, org_id
    )
    if not ticket:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ticket not found")
    if ticket["status"] == "closed":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This ticket is closed. Please open a new ticket.",
        )

    message = await db.fetchrow(
        """
        INSERT INTO support_ticket_messages (ticket_id, sender_user_id, sender_is_admin, is_internal_note, body)
        VALUES ($1,$2,false,false,$3)
        RETURNING *
        """,
        ticket_id, user.id, sanitize_formula_injection(body.strip()),
    )
    await db.execute("UPDATE support_tickets SET updated_at = NOW() WHERE id = $1", ticket_id)

    attachments = []
    if file is not None:
        attachments.append(await save_ticket_attachment(
            db, ticket_id=ticket_id, message_id=message["id"], uploaded_by=user.id, org_id=org_id, file=file
        ))

    return ClientTicketMessage(**dict(message), attachments=attachments)


@router.get("/{ticket_id}/attachments/{attachment_id}/download")
async def download_attachment(ticket_id: UUID, attachment_id: UUID, user: CurrentUserDep, db: DBConn):
    org_id = await get_current_org_id(db, user.id)
    row = await db.fetchrow(
        """
        SELECT a.storage_path FROM support_ticket_attachments a
        JOIN support_tickets t ON t.id = a.ticket_id
        WHERE a.id = $1 AND a.ticket_id = $2 AND t.organization_id = $3
        """,
        attachment_id, ticket_id, org_id,
    )
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Attachment not found")

    signed_url = await get_signed_url(row["storage_path"], expires_in=3600)
    return {"url": signed_url, "expires_in": 3600}
