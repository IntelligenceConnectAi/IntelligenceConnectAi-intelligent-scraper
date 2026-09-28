"""
Client dashboard aggregation (Phase 3, extended in Phase 4 with People Leads):
  GET /dashboard/client -> plan/period info, usage this billing period, request
  counts, and lifetime aggregates — all in one atomic query per user, computed
  directly from `jobs` (the worker reliably updates total_clean/with_website/
  no_website/emails_found on every completion) and, since Phase 4, delivered
  People Leads quantities. `/usage/today` and `/usage/plan` are untouched and
  unrelated to this endpoint.
"""

from fastapi import APIRouter

from app.deps import CurrentUserDep, DBConn, get_current_org_id
from app.leads_usage import days_until, get_effective_monthly_limit, get_leads_used_period
from app.schemas import ClientDashboardResponse, RecentFileSummary

router = APIRouter()


@router.get("", response_model=ClientDashboardResponse)
async def get_client_dashboard(user: CurrentUserDep, db: DBConn):
    plan_row = await db.fetchrow(
        """
        SELECT p.name AS plan_name, p.leads_per_month AS monthly_limit,
               s.status AS subscription_status, s.current_period_end,
               s.cancel_at_period_end, p.history_days
        FROM subscriptions s
        JOIN plans p ON p.id = s.plan_id
        WHERE s.user_id = $1 AND s.status = 'active'
        """,
        user.id,
    )

    monthly_limit = plan_row["monthly_limit"] if plan_row else None
    current_period_end = plan_row["current_period_end"] if plan_row else None
    history_days = plan_row["history_days"] if plan_row else 30
    org_id = await get_current_org_id(db, user.id)

    # Business leads (jobs.total_clean, by user_id) + delivered People Leads
    # (people_lead_requests.delivered_quantity, by org_id) — same helper the
    # People Leads create-request limit check uses, so the two can't disagree.
    effective_monthly_limit = await get_effective_monthly_limit(db, org_id, monthly_limit, current_period_end)
    leads_used_period = await get_leads_used_period(db, user.id, org_id, current_period_end)
    leads_remaining_period = max(effective_monthly_limit - leads_used_period, 0)
    pct_used = min(int(round((leads_used_period / effective_monthly_limit) * 100)), 100) if effective_monthly_limit else 0

    # Request counts — same window client_business.py's list endpoint uses, so the
    # dashboard KPIs and the Business Leads tab badges never disagree.
    status_counts = await db.fetch(
        """
        SELECT status, COUNT(*) AS cnt FROM jobs
        WHERE user_id = $1 AND created_at > NOW() - INTERVAL '1 day' * $2
        GROUP BY status
        """,
        user.id, history_days,
    )
    active_count = sum(r["cnt"] for r in status_counts if r["status"] in ("pending", "running"))
    completed_count = sum(r["cnt"] for r in status_counts if r["status"] == "done")
    cancelled_count = sum(r["cnt"] for r in status_counts if r["status"] == "canceled")
    failed_count = sum(r["cnt"] for r in status_counts if r["status"] == "failed")

    lifetime = await db.fetchrow(
        """
        SELECT COALESCE(SUM(with_website), 0) AS total_with_website,
               COALESCE(SUM(no_website), 0) AS total_no_website,
               COALESCE(SUM(emails_found), 0) AS total_emails_found
        FROM jobs WHERE user_id = $1 AND status = 'done'
        """,
        user.id,
    )

    # People Leads (Phase 4) — org-scoped, unlike the business counts above.
    people_counts = await db.fetchrow(
        """
        SELECT
            COUNT(*) FILTER (WHERE client_status IN ('Submitted','Processing','Needs Information')) AS active,
            COUNT(*) FILTER (WHERE client_status = 'Completed') AS completed,
            COALESCE(SUM(delivered_quantity) FILTER (WHERE client_status = 'Completed'), 0) AS delivered
        FROM people_lead_requests WHERE organization_id = $1
        """,
        org_id,
    )

    days_until_reset = days_until(current_period_end)

    # Phase 5 — lead_files now exists, so these are real instead of always-null.
    total_lead_files = await db.fetchval(
        "SELECT COUNT(*) FROM lead_files WHERE organization_id = $1", org_id
    )
    recent_file_rows = await db.fetch(
        "SELECT id, display_name AS name, file_type, created_at FROM lead_files "
        "WHERE organization_id = $1 ORDER BY created_at DESC LIMIT 5",
        org_id,
    )

    return ClientDashboardResponse(
        plan_name=plan_row["plan_name"] if plan_row else None,
        monthly_limit=monthly_limit,
        effective_monthly_limit=effective_monthly_limit if plan_row else None,
        subscription_status=plan_row["subscription_status"] if plan_row else None,
        package_renewal_date=current_period_end,
        cancel_at_period_end=plan_row["cancel_at_period_end"] if plan_row else None,
        days_until_reset=days_until_reset,
        leads_used_period=leads_used_period,
        leads_remaining_period=leads_remaining_period,
        pct_used=pct_used,
        active_requests_count=active_count,
        completed_requests_count=completed_count,
        cancelled_requests_count=cancelled_count,
        failed_requests_count=failed_count,
        leads_processing=active_count,
        total_with_website=lifetime["total_with_website"],
        total_no_website=lifetime["total_no_website"],
        total_emails_found=lifetime["total_emails_found"],
        people_leads_delivered=people_counts["delivered"],
        people_requests_active=people_counts["active"],
        people_requests_completed=people_counts["completed"],
        total_lead_files=total_lead_files,
        recent_files=[RecentFileSummary(**dict(r)) for r in recent_file_rows],
    )
