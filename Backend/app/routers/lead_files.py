"""
My Leads — unified lead-file library (Phase 5, §13/§23.8/§24.4).
Org-scoped list/stats/charts (matches Phase 4's org-wide-visibility precedent),
per-file detail/rename/download. request_name and original_filename are derived
at read time (see schemas.py note) via a JOIN to jobs/people_lead_requests and a
storage_path basename extraction — lead_files itself only stores §23.8's exact
column list.
"""

from datetime import date
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request, status

from app.audit import log_audit
from app.deps import CurrentUserDep, DBConn, get_current_org_id
from app.schemas import (
    ChartSegment,
    LeadFileChartsResponse,
    LeadFileDetail,
    LeadFileStatsResponse,
    LeadFileSummary,
    PatchLeadFile,
)
from app.security_utils import safe_filename, sanitize_formula_injection
from app.storage import get_signed_url

router = APIRouter()

VALID_SOURCE_TYPES = {"business", "people"}
VALID_CATEGORIES = {
    "business_with_website", "business_no_website", "people_leads",
    "business_with_website_email", "business_with_website_no_email",
}

_SELECT_JOINED = """
    SELECT lf.*,
      regexp_replace(lf.storage_path, '^.*/', '') AS original_filename,
      CASE WHEN lf.source_type = 'business' THEN j.industry || ' — ' || j.state
           ELSE plr.request_name END AS request_name,
      (lf.created_at + (COALESCE(p.history_days, 30) || ' days')::interval) AS expires_at
    FROM lead_files lf
    LEFT JOIN jobs j ON lf.source_type = 'business' AND j.id = lf.source_id
    LEFT JOIN people_lead_requests plr ON lf.source_type = 'people' AND plr.id = lf.source_id
    LEFT JOIN subscriptions s ON s.user_id = lf.user_id AND s.status = 'active'
    LEFT JOIN plans p ON p.id = s.plan_id
"""


@router.get("", response_model=list[LeadFileSummary])
async def list_lead_files(
    user: CurrentUserDep, db: DBConn,
    source_type: Optional[str] = None,
    file_category: Optional[str] = None,
    industry_or_category: Optional[str] = None,
    state: Optional[str] = None,
    city: Optional[str] = None,
    file_type: Optional[str] = None,
    downloaded: Optional[bool] = None,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    limit: int = 100,
    offset: int = 0,
):
    org_id = await get_current_org_id(db, user.id)
    if source_type and source_type not in VALID_SOURCE_TYPES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="invalid source_type")
    if file_category and file_category not in VALID_CATEGORIES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="invalid file_category")

    conditions = ["lf.organization_id = $1"]
    params: list = [org_id]

    def add(cond: str, value):
        params.append(value)
        conditions.append(cond.format(n=len(params)))

    if source_type: add("lf.source_type = ${n}", source_type)
    if file_category: add("lf.file_category = ${n}", file_category)
    if industry_or_category: add("lf.industry_or_category = ${n}", industry_or_category)
    if state: add("lf.state = ${n}", state)
    if city: add("lf.city = ${n}", city)
    if file_type: add("lf.file_type = ${n}", file_type)
    if downloaded is not None:
        conditions.append("lf.download_count > 0" if downloaded else "lf.download_count = 0")
    if date_from: add("lf.created_at >= ${n}", date_from)
    if date_to: add("lf.created_at <= ${n}", date_to)

    limit = min(max(limit, 1), 200)
    params.extend([limit, offset])
    sql = f"{_SELECT_JOINED} WHERE {' AND '.join(conditions)} ORDER BY lf.created_at DESC LIMIT ${len(params) - 1} OFFSET ${len(params)}"
    rows = await db.fetch(sql, *params)
    return [LeadFileSummary(**dict(r)) for r in rows]


@router.get("/stats", response_model=LeadFileStatsResponse)
async def get_lead_file_stats(user: CurrentUserDep, db: DBConn):
    org_id = await get_current_org_id(db, user.id)
    d = dict(await db.fetchrow(
        """
        SELECT
          COALESCE(SUM(record_count), 0) AS total_leads,
          COUNT(*) AS total_files,
          COALESCE(SUM(record_count) FILTER (WHERE source_type = 'business'), 0) AS business_leads,
          COALESCE(SUM(record_count) FILTER (WHERE source_type = 'people'), 0) AS people_leads,
          COALESCE(SUM(record_count) FILTER (WHERE file_category = 'business_with_website'), 0) AS businesses_with_website,
          COALESCE(SUM(record_count) FILTER (WHERE file_category = 'business_no_website'), 0) AS businesses_without_website,
          COALESCE(SUM(email_count), 0) AS emails_found,
          COUNT(*) FILTER (WHERE created_at >= date_trunc('month', NOW())) AS files_generated_this_month
        FROM lead_files WHERE organization_id = $1
        """,
        org_id,
    ))
    pct = int(round((d["emails_found"] / d["businesses_with_website"]) * 100)) if d["businesses_with_website"] else 0
    return LeadFileStatsResponse(**d, email_found_pct=pct)


@router.get("/charts", response_model=LeadFileChartsResponse)
async def get_lead_file_charts(user: CurrentUserDep, db: DBConn):
    org_id = await get_current_org_id(db, user.id)
    splits = await db.fetchrow(
        """
        SELECT
          COALESCE(SUM(record_count) FILTER (WHERE source_type = 'business'), 0) AS business_leads,
          COALESCE(SUM(record_count) FILTER (WHERE source_type = 'people'), 0) AS people_leads,
          COALESCE(SUM(record_count) FILTER (WHERE file_category = 'business_with_website'), 0) AS with_website,
          COALESCE(SUM(record_count) FILTER (WHERE file_category = 'business_no_website'), 0) AS no_website
        FROM lead_files WHERE organization_id = $1
        """, org_id,
    )
    by_state = await db.fetch(
        "SELECT state AS label, SUM(record_count) AS value FROM lead_files WHERE organization_id = $1 AND state IS NOT NULL GROUP BY state ORDER BY value DESC LIMIT 10",
        org_id,
    )
    by_industry = await db.fetch(
        "SELECT industry_or_category AS label, SUM(record_count) AS value FROM lead_files WHERE organization_id = $1 AND industry_or_category IS NOT NULL GROUP BY industry_or_category ORDER BY value DESC LIMIT 10",
        org_id,
    )
    return LeadFileChartsResponse(
        business_vs_people=[ChartSegment(label="Business Leads", value=splits["business_leads"]),
                             ChartSegment(label="People Leads", value=splits["people_leads"])],
        with_vs_without_website=[ChartSegment(label="With Website", value=splits["with_website"]),
                                  ChartSegment(label="Without Website", value=splits["no_website"])],
        leads_by_state=[ChartSegment(**dict(r)) for r in by_state],
        leads_by_industry=[ChartSegment(**dict(r)) for r in by_industry],
    )


@router.get("/{lead_file_id}", response_model=LeadFileDetail)
async def get_lead_file(lead_file_id: UUID, user: CurrentUserDep, db: DBConn):
    org_id = await get_current_org_id(db, user.id)
    row = await db.fetchrow(f"{_SELECT_JOINED} WHERE lf.id = $1 AND lf.organization_id = $2", lead_file_id, org_id)
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lead file not found")
    return LeadFileDetail(**dict(row))


@router.get("/{lead_file_id}/download")
async def download_lead_file(lead_file_id: UUID, user: CurrentUserDep, db: DBConn):
    org_id = await get_current_org_id(db, user.id)
    row = await db.fetchrow(
        "SELECT storage_path, display_name, file_type FROM lead_files WHERE id = $1 AND organization_id = $2",
        lead_file_id, org_id,
    )
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lead file not found")
    filename = safe_filename(f"{row['display_name']}.{row['file_type']}")
    signed_url = await get_signed_url(row["storage_path"], expires_in=3600, download_filename=filename)
    await db.execute(
        "UPDATE lead_files SET download_count = download_count + 1, last_downloaded_at = NOW() WHERE id = $1",
        lead_file_id,
    )
    return {"url": signed_url, "expires_in": 3600}


@router.patch("/{lead_file_id}", response_model=LeadFileDetail)
async def rename_lead_file(lead_file_id: UUID, body: PatchLeadFile, user: CurrentUserDep, db: DBConn, request: Request):
    org_id = await get_current_org_id(db, user.id)
    row = await db.fetchrow("SELECT id FROM lead_files WHERE id = $1 AND organization_id = $2", lead_file_id, org_id)
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lead file not found")
    safe_name = sanitize_formula_injection(body.display_name)
    await db.execute("UPDATE lead_files SET display_name = $2 WHERE id = $1", lead_file_id, safe_name)
    await log_audit(
        db, actor_user_id=user.id, actor_role=user.platform_role,
        action="lead_file_renamed", resource_type="lead_files",
        resource_id=str(lead_file_id), new={"display_name": safe_name}, request=request,
    )
    return await get_lead_file(lead_file_id, user, db)
