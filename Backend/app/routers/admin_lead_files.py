"""
Admin "Lead Files" oversight (Phase 8 — Lean MVP): read-only list/detail across all
clients, plus a download route. lead_files.py itself is untouched — this owns its own
private admin-scoped SELECT rather than importing lead_files.py's (matching the
established convention that each admin router owns its own private helpers, e.g.
admin_people_leads.py and admin_support.py each define separate _fetch_admin_detail
functions rather than sharing one). Gated by operations_admin, same as admin_jobs.py.

The download route was originally scoped out as "read-only list/detail" but is cheap
(mirrors lead_files.py's own get_signed_url pattern exactly) and closes a real gap:
without it, a support_admin resolving a "this file looks wrong" ticket has no way to
actually open the file.
"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from app.deps import DBConn
from app.permissions import AdminDep, RequireAdminPermission
from app.schemas import AdminLeadFileDetail, AdminLeadFileSummary
from app.security_utils import safe_filename
from app.storage import get_signed_url

router = APIRouter()

RequireOperationsAdmin = Annotated[list[str], Depends(RequireAdminPermission("operations_admin"))]

_ADMIN_SELECT_JOINED = """
    SELECT lf.*,
      CASE WHEN lf.source_type = 'business' THEN j.industry || ' — ' || j.state
           ELSE plr.request_name END AS request_name,
      o.name AS organization_name,
      u.email AS user_email
    FROM lead_files lf
    JOIN organizations o ON o.id = lf.organization_id
    JOIN users u ON u.id = lf.user_id
    LEFT JOIN jobs j ON lf.source_type = 'business' AND j.id = lf.source_id
    LEFT JOIN people_lead_requests plr ON lf.source_type = 'people' AND plr.id = lf.source_id
"""


@router.get("", response_model=list[AdminLeadFileSummary])
async def list_admin_lead_files(admin: AdminDep, permissions: RequireOperationsAdmin, db: DBConn):
    rows = await db.fetch(f"{_ADMIN_SELECT_JOINED} ORDER BY lf.created_at DESC LIMIT 200")
    return [AdminLeadFileSummary(**dict(r)) for r in rows]


@router.get("/{lead_file_id}", response_model=AdminLeadFileDetail)
async def get_admin_lead_file(lead_file_id: UUID, admin: AdminDep, permissions: RequireOperationsAdmin, db: DBConn):
    row = await db.fetchrow(f"{_ADMIN_SELECT_JOINED} WHERE lf.id = $1", lead_file_id)
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lead file not found")
    return AdminLeadFileDetail(**dict(row))


@router.get("/{lead_file_id}/download")
async def download_admin_lead_file(lead_file_id: UUID, admin: AdminDep, permissions: RequireOperationsAdmin, db: DBConn):
    row = await db.fetchrow("SELECT storage_path, display_name, file_type FROM lead_files WHERE id = $1", lead_file_id)
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lead file not found")
    filename = safe_filename(f"{row['display_name']}.{row['file_type']}")
    signed_url = await get_signed_url(row["storage_path"], expires_in=3600, download_filename=filename)
    return {"url": signed_url, "expires_in": 3600}
