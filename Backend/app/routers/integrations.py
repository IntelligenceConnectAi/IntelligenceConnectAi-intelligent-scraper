"""
Integrations Coming Soon page's Notify Me action (Phase 6, §16/§23.12). No live
CRM connections are built — this only records interest so the card can show
"Notified" on return visits.
"""

from fastapi import APIRouter, HTTPException, status

from app.deps import CurrentUserDep, DBConn, get_current_org_id
from app.schemas import INTEGRATION_KEYS, IntegrationInterestResponse

router = APIRouter()


@router.post("/{integration_key}/notify-me", status_code=status.HTTP_201_CREATED)
async def notify_me(integration_key: str, user: CurrentUserDep, db: DBConn):
    if integration_key not in INTEGRATION_KEYS:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unknown integration")
    org_id = await get_current_org_id(db, user.id)
    await db.execute(
        """
        INSERT INTO integration_interest (organization_id, user_id, integration_key)
        VALUES ($1, $2, $3)
        ON CONFLICT (user_id, integration_key) DO NOTHING
        """,
        org_id, user.id, integration_key,
    )
    return {"message": "You'll be notified when this integration is available."}


@router.get("/notify-me", response_model=list[IntegrationInterestResponse])
async def list_notify_me(user: CurrentUserDep, db: DBConn):
    rows = await db.fetch(
        "SELECT integration_key, created_at FROM integration_interest WHERE user_id = $1",
        user.id,
    )
    return [IntegrationInterestResponse(**dict(r)) for r in rows]
