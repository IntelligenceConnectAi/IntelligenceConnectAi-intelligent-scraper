from fastapi import APIRouter, HTTPException

from app.deps import CurrentUserDep, DBConn
from app.schemas import CurrentPlanResponse, TodayUsageResponse


router = APIRouter()


@router.get("/today", response_model=TodayUsageResponse)
async def get_today_usage(user: CurrentUserDep, db: DBConn) -> TodayUsageResponse:
    """Today's lead/email/job usage for the dashboard meter."""
    row = await db.fetchrow(
        "SELECT * FROM user_today_usage WHERE user_id = $1",
        user.id,
    )
    if row is None:
        raise HTTPException(404, "No usage data — user not found")
    return TodayUsageResponse(**dict(row))


@router.get("/plan", response_model=CurrentPlanResponse)
async def get_current_plan(user: CurrentUserDep, db: DBConn) -> CurrentPlanResponse:
    """Current active subscription + plan details for the dashboard."""
    row = await db.fetchrow(
        "SELECT * FROM user_current_plan WHERE user_id = $1",
        user.id,
    )
    if row is None:
        raise HTTPException(404, "No plan data — user not found")
    return CurrentPlanResponse(**dict(row))
