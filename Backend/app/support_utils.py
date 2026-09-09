"""
Shared support-ticket helpers (Phase 7) — used by both app/routers/support.py
(client) and app/routers/admin_support.py, since attachment saving and
resource-link ownership validation are identical for either actor, just sourced
from a different organization_id (the caller's own org for clients, the ticket's
own org for admins, who aren't org members themselves).
"""

import os
from typing import Optional
from uuid import UUID

from fastapi import HTTPException, UploadFile, status

from app.schemas import SupportTicketAttachment
from app.security_utils import (
    TICKET_ATTACHMENT_CONTENT_TYPES,
    TICKET_ATTACHMENT_EXTENSIONS,
    TICKET_ATTACHMENT_MAX_BYTES,
    safe_filename,
    sanitize_formula_injection,
)
from app.storage import upload_csv


def parse_resource_uuid(resource_id: str) -> UUID:
    try:
        return UUID(resource_id)
    except (ValueError, AttributeError, TypeError):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid linked resource id")


async def validate_linked_resource(
    db, *, resource_type: Optional[str], resource_id: Optional[str], org_id: UUID
) -> Optional[str]:
    """Returns the (possibly sanitized) resource_id to store, or raises 404/400.
    `invoice` is trusted free text — there's no local invoices table (Stripe invoices
    are fetched live by stripe_customer_id in billing.py, never persisted), so it's
    sanitized + length-capped rather than ownership-checked."""
    if not resource_type or not resource_id:
        return None
    if resource_type == "invoice":
        return sanitize_formula_injection(resource_id.strip()[:200])

    rid = parse_resource_uuid(resource_id)
    if resource_type == "business_request":
        exists = await db.fetchval(
            """
            SELECT 1 FROM jobs j
            JOIN organization_members om ON om.user_id = j.user_id AND om.is_active = true
            WHERE j.id = $1 AND om.organization_id = $2
            """,
            rid, org_id,
        )
    elif resource_type == "people_lead_request":
        exists = await db.fetchval(
            "SELECT 1 FROM people_lead_requests WHERE id = $1 AND organization_id = $2", rid, org_id
        )
    elif resource_type == "lead_file":
        exists = await db.fetchval(
            "SELECT 1 FROM lead_files WHERE id = $1 AND organization_id = $2", rid, org_id
        )
    else:
        exists = None

    if not exists:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Linked {resource_type} not found in your organization",
        )
    return str(rid)


async def save_ticket_attachment(
    db, *, ticket_id: UUID, message_id: UUID, uploaded_by: UUID, org_id: UUID, file: UploadFile
) -> SupportTicketAttachment:
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in TICKET_ATTACHMENT_EXTENSIONS:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unsupported attachment file type")

    content = await file.read(TICKET_ATTACHMENT_MAX_BYTES + 1)
    if len(content) > TICKET_ATTACHMENT_MAX_BYTES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Attachment exceeds {TICKET_ATTACHMENT_MAX_BYTES // (1024 * 1024)}MB limit",
        )

    fname = safe_filename(file.filename)
    storage_path = f"{org_id}/support/{ticket_id}/{message_id}/{fname}"
    await upload_csv(
        storage_path, content,
        content_type=TICKET_ATTACHMENT_CONTENT_TYPES.get(ext.lstrip("."), "application/octet-stream"),
    )

    row = await db.fetchrow(
        """
        INSERT INTO support_ticket_attachments
            (ticket_id, message_id, storage_path, original_filename, file_type, file_size, uploaded_by)
        VALUES ($1,$2,$3,$4,$5,$6,$7)
        RETURNING *
        """,
        ticket_id, message_id, storage_path, file.filename, ext.lstrip("."), len(content), uploaded_by,
    )
    return SupportTicketAttachment(**dict(row))
