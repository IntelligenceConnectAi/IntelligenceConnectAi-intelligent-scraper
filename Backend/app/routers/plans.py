from fastapi import APIRouter

from app.deps import DBConn
from app.schemas import Plan


router = APIRouter()


@router.get("", response_model=list[Plan])
async def list_plans(db: DBConn) -> list[Plan]:
    """Public — used by the pricing page (no auth required)."""
    rows = await db.fetch(
        """
        SELECT id, name, price_monthly, leads_per_month, leads_per_day,
               cities_per_job, keywords_per_job, history_days, concurrent_jobs,
               email_scraping, api_access
        FROM plans
        WHERE is_active = TRUE
          AND id != 'enterprise'      -- Hide Enterprise from public listing
        ORDER BY price_monthly
        """
    )
    return [Plan(**dict(r)) for r in rows]
