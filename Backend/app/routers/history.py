"""
History — combined Business + People Leads request timeline (Phase 5, §14/§24.6).
GET /history UNIONs jobs (user-scoped, per client_business.py's existing precedent)
and people_lead_requests (org-scoped, per people_leads.py's existing precedent) —
that scoping asymmetry is inherited from Phase 3/4, not new here.
"""

from fastapi import APIRouter

from app.deps import CurrentUserDep, DBConn, get_current_org_id
from app.schemas import (
    ChartSegment,
    HistoryChartsResponse,
    HistoryEntryResponse,
    HistoryStatsResponse,
    to_client_status,
)

router = APIRouter()


@router.get("", response_model=list[HistoryEntryResponse])
async def list_history(user: CurrentUserDep, db: DBConn, limit: int = 100, offset: int = 0):
    org_id = await get_current_org_id(db, user.id)
    limit = min(max(limit, 1), 200)
    rows = await db.fetch(
        """
        WITH combined AS (
          SELECT j.id, 'business'::text AS source_type,
                 (j.industry || ' — ' || j.state) AS request_name,
                 j.industry AS lead_type_or_industry,
                 (array_to_string(j.cities, ', ') || ', ' || j.state) AS location,
                 cardinality(j.cities) AS requested_quantity,
                 COALESCE(j.total_clean, 0) AS delivered_quantity,
                 j.status AS raw_status, j.created_at, j.completed_at
          FROM jobs j WHERE j.user_id = $1
          UNION ALL
          SELECT p.id, 'people'::text AS source_type,
                 p.request_name, p.lead_type AS lead_type_or_industry,
                 (COALESCE(p.city || ', ', '') || p.state) AS location,
                 p.requested_quantity, p.delivered_quantity,
                 p.client_status AS raw_status, p.created_at, p.completed_at
          FROM people_lead_requests p WHERE p.organization_id = $2
        )
        SELECT * FROM combined ORDER BY created_at DESC LIMIT $3 OFFSET $4
        """,
        user.id, org_id, limit, offset,
    )
    out = []
    for r in rows:
        d = dict(r)
        # jobs.status needs the existing CLIENT_STATUS_MAP; people_lead_requests.client_status
        # is already client-safe. Mapped here in Python so CLIENT_STATUS_MAP (schemas.py)
        # stays the single source of truth, not duplicated as a SQL CASE.
        status = to_client_status(d["raw_status"]) if d["source_type"] == "business" else d["raw_status"]
        del d["raw_status"]
        out.append(HistoryEntryResponse(status=status, **d))
    return out


@router.get("/stats", response_model=HistoryStatsResponse)
async def get_history_stats(user: CurrentUserDep, db: DBConn):
    org_id = await get_current_org_id(db, user.id)
    biz = await db.fetchrow(
        """
        SELECT COUNT(*) AS total,
               COUNT(*) FILTER (WHERE status = 'done') AS completed,
               COUNT(*) FILTER (WHERE status IN ('pending','running')) AS active,
               COUNT(*) FILTER (WHERE status = 'failed') AS failed,
               COALESCE(SUM(total_clean) FILTER (WHERE status = 'done'), 0) AS leads_generated
        FROM jobs WHERE user_id = $1
        """, user.id,
    )
    ppl = await db.fetchrow(
        """
        SELECT COUNT(*) AS total,
               COUNT(*) FILTER (WHERE client_status = 'Completed') AS completed,
               COUNT(*) FILTER (WHERE client_status IN ('Submitted','Processing','Needs Information')) AS active,
               COALESCE(SUM(delivered_quantity) FILTER (WHERE client_status = 'Completed'), 0) AS leads_generated
        FROM people_lead_requests WHERE organization_id = $1
        """, org_id,
    )
    downloads = await db.fetchval(
        "SELECT COALESCE(SUM(download_count), 0) FROM lead_files WHERE organization_id = $1", org_id,
    )
    return HistoryStatsResponse(
        total_requests=biz["total"] + ppl["total"],
        completed_requests=biz["completed"] + ppl["completed"],
        active_requests=biz["active"] + ppl["active"],
        failed_requests=biz["failed"],
        total_leads_generated=biz["leads_generated"] + ppl["leads_generated"],
        total_files_downloaded=downloads,
    )


@router.get("/charts", response_model=HistoryChartsResponse)
async def get_history_charts(user: CurrentUserDep, db: DBConn):
    org_id = await get_current_org_id(db, user.id)
    biz_status = await db.fetch("SELECT status, COUNT(*) AS cnt FROM jobs WHERE user_id = $1 GROUP BY status", user.id)
    ppl_status = await db.fetch("SELECT client_status AS status, COUNT(*) AS cnt FROM people_lead_requests WHERE organization_id = $1 GROUP BY client_status", org_id)
    status_counts: dict = {}
    for r in biz_status:
        label = to_client_status(r["status"])
        status_counts[label] = status_counts.get(label, 0) + r["cnt"]
    for r in ppl_status:
        status_counts[r["status"]] = status_counts.get(r["status"], 0) + r["cnt"]

    biz_count = await db.fetchval("SELECT COUNT(*) FROM jobs WHERE user_id = $1", user.id)
    ppl_count = await db.fetchval("SELECT COUNT(*) FROM people_lead_requests WHERE organization_id = $1", org_id)

    biz_locs = await db.fetch("SELECT state AS label, COUNT(*) AS value FROM jobs WHERE user_id = $1 GROUP BY state", user.id)
    ppl_locs = await db.fetch("SELECT state AS label, COUNT(*) AS value FROM people_lead_requests WHERE organization_id = $1 GROUP BY state", org_id)
    loc_counts: dict = {}
    for r in list(biz_locs) + list(ppl_locs):
        loc_counts[r["label"]] = loc_counts.get(r["label"], 0) + r["value"]
    top_locations = sorted(loc_counts.items(), key=lambda kv: -kv[1])[:10]

    return HistoryChartsResponse(
        status_distribution=[ChartSegment(label=k, value=v) for k, v in status_counts.items()],
        business_vs_people=[ChartSegment(label="Business", value=biz_count), ChartSegment(label="People", value=ppl_count)],
        most_requested_locations=[ChartSegment(label=k, value=v) for k, v in top_locations],
    )
