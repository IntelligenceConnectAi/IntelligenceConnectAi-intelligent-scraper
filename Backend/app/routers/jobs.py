"""
Job endpoints:
  POST   /jobs                    → create + queue job
  GET    /jobs                    → list user's jobs
  GET    /jobs/{job_id}           → single job + city progress
  POST   /jobs/{job_id}/cancel    → cancel pending job
  GET    /jobs/{job_id}/download/{file_type}  → signed CSV URL
"""

import logging
from uuid import UUID

from fastapi import APIRouter, HTTPException, status

from app.deps import CurrentUserDep, DBConn
from app.notifications import create_notification, notify_admins_with_permission
from app.schemas import CreateJobRequest, JobResponse, JobSummary
from app.security_utils import safe_filename
from app.storage import get_signed_url

log = logging.getLogger(__name__)
router = APIRouter()


# ─────────────────────────────────────────────────────
#  POST /jobs  — create & queue
# ─────────────────────────────────────────────────────
@router.post("", response_model=JobResponse, status_code=status.HTTP_201_CREATED)
async def create_job(body: CreateJobRequest, user: CurrentUserDep, db: DBConn):

    # 1. Load active plan
    plan = await db.fetchrow(
        """
        SELECT p.leads_per_day, p.leads_per_month,
               p.cities_per_job, p.concurrent_jobs, p.email_scraping
        FROM subscriptions s
        JOIN plans p ON p.id = s.plan_id
        WHERE s.user_id = $1 AND s.status = 'active'
        LIMIT 1
        """,
        user.id,
    )
    if not plan:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No active subscription. Please subscribe to a plan.",
        )

    # 2. Cities limit check
    max_cities = plan["cities_per_job"]
    if max_cities and len(body.cities) > max_cities:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Your plan allows max {max_cities} cities per job. You submitted {len(body.cities)}.",
        )

    # 3. Daily lead limit check
    result = await db.fetchrow(
        "SELECT * FROM can_user_scrape($1, $2)",
        user.id,
        len(body.cities) * 60,   # conservative estimate: ~60 leads per city
    )
    if result and not result["allowed"]:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=result["reason"],
        )

    # 4. Concurrent jobs check
    running_count = await db.fetchval(
        """
        SELECT COUNT(*) FROM jobs
        WHERE user_id = $1 AND status IN ('pending', 'running')
        """,
        user.id,
    )
    if running_count >= plan["concurrent_jobs"]:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"You already have {running_count} active job(s). Your plan allows {plan['concurrent_jobs']} concurrent job(s).",
        )

    # 5. Insert job
    job = await db.fetchrow(
        """
        INSERT INTO jobs (
            user_id, industry, state, cities,
            cities_total, status, current_step
        )
        VALUES ($1, $2, $3, $4, $5, 'pending', 'step1_maps')
        RETURNING *
        """,
        user.id,
        body.industry,
        body.state,
        body.cities,
        len(body.cities),
    )

    # 6. Insert job_cities rows (for per-city progress)
    for city in body.cities:
        await db.execute(
            """
            INSERT INTO job_cities (job_id, city, maps_status, status)
            VALUES ($1, $2, 'pending', 'pending')
            """,
            job["id"],
            city,
        )

    # ── Phase 6 hook (§19/§27): best-effort submission notification. No other
    # change in this file — see the Phase 6 plan's design decision on why Business
    # Leads submission stays owner-only (the plan-lookup/can_user_scrape gate above
    # is untouched). ──
    try:
        await create_notification(
            db, user_id=user.id, category="business_updates",
            type="business_request_submitted", title="Business Leads request submitted",
            body=f"Your {body.industry} / {body.state} request has been queued.",
            link_section="get-leads", link_sub_tab="business",
        )
    except Exception as notif_exc:
        log.error(f"Submission notification failed for job {job['id']}: {notif_exc}", exc_info=True)

    # Every operations_admin (+ super admins) gets pinged so a new request
    # doesn't just sit unnoticed — mirrors people_leads.py's identical pattern.
    try:
        await notify_admins_with_permission(
            db, permission_key="operations_admin",
            category="business_updates", type="new_business_request",
            title="New Business Leads request",
            body=f"{user.email} submitted a new request: {body.industry} / {body.state} ({len(body.cities)} cities).",
            link_section="business-requests", link_resource_id=str(job["id"]),
        )
    except Exception as notif_exc:
        log.error(f"Admin new-request notification failed for job {job['id']}: {notif_exc}", exc_info=True)

    return JobResponse(**dict(job), city_progress=[])


# ─────────────────────────────────────────────────────
#  GET /jobs  — list user's jobs
# ─────────────────────────────────────────────────────
@router.get("", response_model=list[JobSummary])
async def list_jobs(user: CurrentUserDep, db: DBConn):
    # Respect plan history_retention_days
    rows = await db.fetch(
        """
        SELECT j.id, j.industry, j.state, j.cities, j.status,
               j.total_clean, j.emails_found, j.created_at, j.completed_at
        FROM jobs j
        JOIN subscriptions s ON s.user_id = j.user_id AND s.status = 'active'
        JOIN plans p ON p.id = s.plan_id
        WHERE j.user_id = $1
          AND j.created_at > NOW() - INTERVAL '1 day' * p.history_days
        ORDER BY j.created_at DESC
        LIMIT 100
        """,
        user.id,
    )
    return [JobSummary(**dict(r)) for r in rows]


# ─────────────────────────────────────────────────────
#  GET /jobs/{job_id}  — single job with city progress
# ─────────────────────────────────────────────────────
@router.get("/{job_id}", response_model=JobResponse)
async def get_job(job_id: UUID, user: CurrentUserDep, db: DBConn):
    job = await db.fetchrow(
        "SELECT * FROM jobs WHERE id = $1 AND user_id = $2",
        job_id,
        user.id,
    )
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    cities = await db.fetch(
        "SELECT city, maps_status, maps_leads FROM job_cities WHERE job_id = $1 ORDER BY id",
        job_id,
    )

    return JobResponse(
        **dict(job),
        city_progress=[dict(c) for c in cities],
    )


# ─────────────────────────────────────────────────────
#  POST /jobs/{job_id}/cancel
# ─────────────────────────────────────────────────────
@router.post("/{job_id}/cancel")
async def cancel_job(job_id: UUID, user: CurrentUserDep, db: DBConn):
    job = await db.fetchrow(
        "SELECT id, status FROM jobs WHERE id = $1 AND user_id = $2",
        job_id,
        user.id,
    )
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job["status"] not in ("pending", "running"):
        raise HTTPException(status_code=400, detail=f"Cannot cancel a job with status '{job['status']}'")

    await db.execute(
        "UPDATE jobs SET status = 'canceled', updated_at = NOW() WHERE id = $1",
        job_id,
    )

    try:
        await create_notification(
            db, user_id=user.id, category="business_updates",
            type="business_request_cancelled", title="Business Leads request cancelled",
            body="Your Business Leads request was cancelled.",
            link_section="history",
        )
    except Exception as notif_exc:
        log.error(f"Cancellation notification failed for job {job_id}: {notif_exc}", exc_info=True)

    return {"message": "Job canceled"}


# ─────────────────────────────────────────────────────
#  GET /jobs/{job_id}/download/{file_type}
#  file_type: "with_website" or "no_website"
# ─────────────────────────────────────────────────────
@router.get("/{job_id}/download/{file_type}")
async def download_job(
    job_id: UUID,
    file_type: str,
    user: CurrentUserDep,
    db: DBConn,
):
    if file_type not in ("with_website", "no_website"):
        raise HTTPException(status_code=400, detail="file_type must be 'with_website' or 'no_website'")

    job = await db.fetchrow(
        "SELECT status, industry, state, with_web_csv, no_web_csv FROM jobs WHERE id = $1 AND user_id = $2",
        job_id,
        user.id,
    )
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job["status"] != "done":
        raise HTTPException(status_code=400, detail="Job not completed yet")

    path = job["with_web_csv"] if file_type == "with_website" else job["no_web_csv"]
    if not path:
        raise HTTPException(status_code=404, detail="File not available for this job")

    suffix = "with_website" if file_type == "with_website" else "without_website"
    filename = safe_filename(f"{job['industry']}_{job['state']}_{suffix}.csv")
    signed_url = await get_signed_url(path, expires_in=3600, download_filename=filename)
    return {"url": signed_url, "expires_in": 3600}