"""
Admin "Business Requests" monitoring (Phase 8 — Lean MVP, judgment-call routes not in
the doc's literal §24 list, but §28's audit requirements explicitly list "Job retry"
and "Job cancellation" as admin actions, confirming the capability is expected):
  GET  /admin/jobs              -> list across all clients
  GET  /admin/jobs/{id}         -> detail incl. city progress
  POST /admin/jobs/{id}/retry   -> resets a failed/canceled job back to pending
  POST /admin/jobs/{id}/cancel  -> admin-side cancel, any status pending/running

jobs.py itself is untouched — this sits alongside it exactly like admin_people_leads.py
sits alongside people_leads.py. Gated by RequireAdminPermission("operations_admin"),
which had zero real consumers since Phase 1 — this is its first one.
"""

import logging
from typing import Annotated, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.audit import log_audit
from app.deps import DBConn
from app.jobs_reset import reset_job_to_pending
from app.notifications import create_notification
from app.permissions import AdminDep, RequireAdminPermission
from app.schemas import AdminJobDetail, AdminJobSummary, JobCityProgress

log = logging.getLogger(__name__)
router = APIRouter()

RequireOperationsAdmin = Annotated[list[str], Depends(RequireAdminPermission("operations_admin"))]

_LIST_SELECT = """
    SELECT j.id, j.user_id, u.email AS requester_email,
           o.id AS organization_id, o.name AS organization_name,
           j.industry, j.state, j.cities, j.status, j.current_step,
           j.cities_done, j.cities_total, j.total_clean, j.with_website, j.no_website,
           j.emails_found, j.error_message, j.retry_count, j.created_at, j.started_at, j.completed_at
    FROM jobs j
    JOIN users u ON u.id = j.user_id
    LEFT JOIN LATERAL (
        SELECT org.id, org.name FROM organization_members om
        JOIN organizations org ON org.id = om.organization_id
        WHERE om.user_id = j.user_id AND om.is_active = true
        ORDER BY om.created_at ASC LIMIT 1
    ) o ON true
"""


async def _fetch_admin_job_detail(db, job_id: UUID) -> AdminJobDetail:
    row = await db.fetchrow(f"{_LIST_SELECT} WHERE j.id = $1", job_id)
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    city_rows = await db.fetch(
        "SELECT city, maps_status, maps_leads FROM job_cities WHERE job_id = $1 ORDER BY id", job_id
    )
    return AdminJobDetail(**dict(row), city_progress=[JobCityProgress(**dict(c)) for c in city_rows])


@router.get("", response_model=list[AdminJobSummary])
async def list_admin_jobs(admin: AdminDep, permissions: RequireOperationsAdmin, db: DBConn, job_status: Optional[str] = None):
    if job_status:
        rows = await db.fetch(f"{_LIST_SELECT} WHERE j.status = $1 ORDER BY j.created_at DESC LIMIT 200", job_status)
    else:
        rows = await db.fetch(f"{_LIST_SELECT} ORDER BY j.created_at DESC LIMIT 200")
    return [AdminJobSummary(**dict(r)) for r in rows]


@router.get("/{job_id}", response_model=AdminJobDetail)
async def get_admin_job(job_id: UUID, admin: AdminDep, permissions: RequireOperationsAdmin, db: DBConn):
    return await _fetch_admin_job_detail(db, job_id)


@router.post("/{job_id}/retry", response_model=AdminJobDetail)
async def retry_job(job_id: UUID, admin: AdminDep, permissions: RequireOperationsAdmin, db: DBConn, request: Request):
    job = await db.fetchrow("SELECT status FROM jobs WHERE id = $1", job_id)
    if not job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    if job["status"] not in ("failed", "canceled"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot retry a job with status '{job['status']}'",
        )

    async with db.transaction():
        # bump_retry_count=False — a human explicitly asking for a fresh attempt
        # shouldn't inherit an exhausted auto-retry budget from earlier watchdog
        # recoveries (see app/jobs_reset.py).
        await reset_job_to_pending(db, job_id, bump_retry_count=False)

    await log_audit(
        db, actor_user_id=admin.id, actor_role=admin.platform_role,
        action="business_job_retried", resource_type="jobs", resource_id=str(job_id), request=request,
    )
    return await _fetch_admin_job_detail(db, job_id)


@router.post("/{job_id}/cancel", response_model=AdminJobDetail)
async def cancel_job(job_id: UUID, admin: AdminDep, permissions: RequireOperationsAdmin, db: DBConn, request: Request):
    job = await db.fetchrow("SELECT status, user_id, industry, state FROM jobs WHERE id = $1", job_id)
    if not job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    if job["status"] not in ("pending", "running"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot cancel a job with status '{job['status']}'",
        )

    await db.execute("UPDATE jobs SET status = 'canceled', updated_at = NOW() WHERE id = $1", job_id)
    await log_audit(
        db, actor_user_id=admin.id, actor_role=admin.platform_role,
        action="business_job_cancelled", resource_type="jobs", resource_id=str(job_id), request=request,
    )

    try:
        await create_notification(
            db, user_id=job["user_id"], category="business_updates", type="business_request_cancelled",
            title="Business Leads request cancelled",
            body=f"Your {job['industry']} / {job['state']} request was cancelled by our team.",
            link_section="history",
        )
    except Exception as notif_exc:
        log.error(f"Cancellation notification failed for job {job_id}: {notif_exc}", exc_info=True)

    return await _fetch_admin_job_detail(db, job_id)
