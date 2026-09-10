from fastapi import APIRouter, HTTPException

from app.deps import CurrentUserDep, DBConn
from app.schemas import CurrentPlanResponse, TodayUsageResponse


router = APIRouter()

# Company staff (platform admins) scrape without limits — see jobs.py::create_job.
# These sentinels keep the client UI's plan-based gates (max-cities counter,
# "leads remaining" meter) from blocking them. Big finite numbers, not None,
# because the frontend does `plan?.cities_per_job ?? 10`.
_UNLIMITED = 999_999_999
_UNLIMITED_CITIES = 999_999
_UNLIMITED_CONCURRENT = 999


def _is_privileged(user) -> bool:
    return user.platform_role in ("admin", "super_admin")


@router.get("/today", response_model=TodayUsageResponse)
async def get_today_usage(user: CurrentUserDep, db: DBConn) -> TodayUsageResponse:
    """Today's lead/email/job usage for the dashboard meter."""
    row = await db.fetchrow(
        "SELECT * FROM user_today_usage WHERE user_id = $1",
        user.id,
    )
    if row is None:
        raise HTTPException(404, "No usage data — user not found")
    data = dict(row)
    if _is_privileged(user):
        data["daily_limit"] = _UNLIMITED
        data["leads_remaining"] = _UNLIMITED
    return TodayUsageResponse(**data)


@router.get("/plan", response_model=CurrentPlanResponse)
async def get_current_plan(user: CurrentUserDep, db: DBConn) -> CurrentPlanResponse:
    """Current active subscription + plan details for the dashboard."""
    row = await db.fetchrow(
        "SELECT * FROM user_current_plan WHERE user_id = $1",
        user.id,
    )
    if row is None:
        raise HTTPException(404, "No plan data — user not found")
    data = dict(row)
    if _is_privileged(user):
        data["daily_limit"] = _UNLIMITED
        data["monthly_limit"] = _UNLIMITED
        data["cities_per_job"] = _UNLIMITED_CITIES
        data["concurrent_jobs"] = _UNLIMITED_CONCURRENT
    return CurrentPlanResponse(**data)
