"""
Client-safe Business Leads status endpoints (Phase 2 — sanitized presentation layer).
Reads the same `jobs` data as app/routers/jobs.py but returns only the unified
client-facing status + safe aggregate fields. Never exposes current_step,
current_city, per-city progress, raw/duplicate counts, emails_attempted, or raw
error messages — see INTELLIGENT_SCRAPER_EXPANSION_KNOWLEDGE(1).md §7 / §34.

Existing /jobs/* routes are untouched and remain the source of truth for
Super Admin/Admin detailed telemetry (Phase 8 territory). Cancel and download
stay on the existing /jobs routes — both already return only safe data.
"""

from uuid import UUID

from fastapi import APIRouter, HTTPException

from app.deps import CurrentUserDep, DBConn
from app.schemas import (
    ClientBusinessRequestDetail,
    ClientBusinessRequestSummary,
    to_client_status,
)

router = APIRouter()

GENERIC_MESSAGES = {
    "Submitted": "Your request has been submitted successfully. We are preparing your lead list securely.",
    "Processing": (
        "Your request has been submitted successfully. We are preparing your lead list securely. "
        "Your completed files will be added to your account when they are ready, and we will notify you "
        "as soon as the request is completed."
    ),
    "Completed": "Your request is complete. Your lead files are ready to download.",
    "Cancelled": "This request was cancelled.",
    "Failed": "We were unable to complete this request. Please contact support or submit a new request.",
}


@router.get("", response_model=list[ClientBusinessRequestSummary])
async def list_client_business_requests(user: CurrentUserDep, db: DBConn):
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
    out = []
    for r in rows:
        d = dict(r)
        client_status = to_client_status(d["status"])
        is_done = d["status"] == "done"
        out.append(ClientBusinessRequestSummary(
            id=d["id"], industry=d["industry"], state=d["state"], cities=d["cities"],
            status=client_status,
            requested_quantity=len(d["cities"]),
            total_leads=d["total_clean"] if is_done else None,
            emails_found=d["emails_found"] if is_done else None,
            created_at=d["created_at"], completed_at=d["completed_at"],
        ))
    return out


@router.get("/{request_id}", response_model=ClientBusinessRequestDetail)
async def get_client_business_request(request_id: UUID, user: CurrentUserDep, db: DBConn):
    job = await db.fetchrow(
        """
        SELECT id, industry, state, cities, status,
               total_clean, with_website, no_website, emails_found,
               created_at, completed_at
        FROM jobs WHERE id = $1 AND user_id = $2
        """,
        request_id, user.id,
    )
    if not job:
        raise HTTPException(status_code=404, detail="Request not found")

    d = dict(job)
    client_status = to_client_status(d["status"])
    is_done = d["status"] == "done"

    return ClientBusinessRequestDetail(
        id=d["id"], industry=d["industry"], state=d["state"], cities=d["cities"],
        status=client_status,
        requested_quantity=len(d["cities"]),
        created_at=d["created_at"], completed_at=d["completed_at"],
        message=GENERIC_MESSAGES[client_status],
        total_leads=d["total_clean"] if is_done else None,
        with_website=d["with_website"] if is_done else None,
        no_website=d["no_website"] if is_done else None,
        emails_found=d["emails_found"] if is_done else None,
    )
