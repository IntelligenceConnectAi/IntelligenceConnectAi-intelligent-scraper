"""
Admin Overview (Phase 8 — Lean MVP): platform-wide widgets + a handful of charts,
split into two endpoints matching the more recent lead_files.py/history.py
`/stats`+`/charts` convention (and the doc's own §24.9 split). RequireAdmin bare —
aggregate counts only, not record-level access, matching the existing precedent that
every org member sees the same client dashboard regardless of role.

Only 4 charts, all reusing the existing ChartSegment/DonutChart/BarListChart
primitives — no time-series bucketing infra exists anywhere in this codebase (same
judgment already made in Phases 3/5/6), so revenue-over-time, client-growth, etc. are
explicitly out of scope for this phase.
"""

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter

from app.deps import DBConn
from app.permissions import AdminDep
from app.schemas import AdminDashboardChartsResponse, AdminDashboardResponse, ChartSegment

router = APIRouter()


def _worker_status(last_seen_at) -> str:
    if last_seen_at is None:
        return "down"
    now = datetime.now(timezone.utc)
    age = now - last_seen_at
    if age < timedelta(seconds=15):   # 5x the 3s poll interval — tolerates a couple slow cycles
        return "healthy"
    if age < timedelta(seconds=60):   # covers the ~9s self-heal window with margin
        return "degraded"
    return "down"


@router.get("", response_model=AdminDashboardResponse)
async def get_admin_dashboard(admin: AdminDep, db: DBConn):
    row = await db.fetchrow(
        """
        SELECT
          (SELECT COUNT(*) FROM organizations) AS total_clients,
          (SELECT COUNT(*) FROM jobs WHERE status IN ('pending','running')) AS active_business_jobs,
          (SELECT COUNT(*) FROM jobs WHERE status = 'failed') AS failed_business_jobs,
          (SELECT COUNT(*) FROM people_lead_requests WHERE internal_status = 'new') AS pending_people_requests,
          (SELECT COUNT(*) FROM support_tickets WHERE status NOT IN ('resolved','closed')) AS open_support_tickets,
          ((SELECT COALESCE(SUM(total_clean), 0) FROM jobs WHERE status = 'done') +
           (SELECT COALESCE(SUM(delivered_quantity), 0) FROM people_lead_requests WHERE client_status = 'Completed')
          ) AS total_leads_generated,
          ((SELECT COUNT(*) FROM jobs WHERE completed_at::date = CURRENT_DATE) +
           (SELECT COUNT(*) FROM people_lead_requests WHERE completed_at::date = CURRENT_DATE)
          ) AS requests_completed_today,
          (SELECT COUNT(*) FROM users WHERE platform_role IN ('admin','super_admin') AND is_active = true) AS active_admins_count,
          (SELECT last_beat_at FROM worker_heartbeats WHERE worker_id = 'primary') AS worker_last_seen_at
        """
    )
    data = dict(row)
    data["worker_status"] = _worker_status(data["worker_last_seen_at"])
    return AdminDashboardResponse(**data)


@router.get("/charts", response_model=AdminDashboardChartsResponse)
async def get_admin_dashboard_charts(admin: AdminDep, db: DBConn):
    totals = await db.fetchrow(
        """
        SELECT
          (SELECT COALESCE(SUM(total_clean), 0) FROM jobs WHERE status = 'done') AS business_leads,
          (SELECT COALESCE(SUM(delivered_quantity), 0) FROM people_lead_requests WHERE client_status = 'Completed') AS people_leads
        """
    )
    job_status_rows = await db.fetch("SELECT status AS label, COUNT(*) AS value FROM jobs GROUP BY status")
    ticket_status_rows = await db.fetch("SELECT status AS label, COUNT(*) AS value FROM support_tickets GROUP BY status")
    top_clients_rows = await db.fetch(
        """
        WITH business_by_org AS (
            SELECT om.organization_id, COALESCE(SUM(j.total_clean), 0) AS biz_leads
            FROM jobs j
            JOIN organization_members om ON om.user_id = j.user_id AND om.is_active = true
            WHERE j.status = 'done'
            GROUP BY om.organization_id
        ),
        people_by_org AS (
            SELECT organization_id, COALESCE(SUM(delivered_quantity), 0) AS people_leads
            FROM people_lead_requests WHERE client_status = 'Completed'
            GROUP BY organization_id
        )
        SELECT o.name AS label, (COALESCE(b.biz_leads, 0) + COALESCE(p.people_leads, 0)) AS value
        FROM organizations o
        LEFT JOIN business_by_org b ON b.organization_id = o.id
        LEFT JOIN people_by_org p ON p.organization_id = o.id
        ORDER BY value DESC LIMIT 10
        """
    )

    return AdminDashboardChartsResponse(
        business_vs_people=[
            ChartSegment(label="Business Leads", value=totals["business_leads"]),
            ChartSegment(label="People Leads", value=totals["people_leads"]),
        ],
        business_job_status=[ChartSegment(**dict(r)) for r in job_status_rows],
        top_clients_by_leads=[ChartSegment(**dict(r)) for r in top_clients_rows],
        tickets_by_status=[ChartSegment(**dict(r)) for r in ticket_status_rows],
    )
