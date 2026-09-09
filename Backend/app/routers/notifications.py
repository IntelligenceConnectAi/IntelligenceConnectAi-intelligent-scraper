"""
In-app notification center (Phase 6, §19/§24.7). Two routers sharing one file/
concern, mounted at two prefixes in app/main.py — same precedent as auth+register
sharing /auth.
"""

from uuid import UUID

from fastapi import APIRouter, HTTPException, status

from app.deps import CurrentUserDep, DBConn
from app.schemas import (
    NotificationListResponse,
    NotificationPreferencesResponse,
    NotificationResponse,
    PatchNotificationPreferencesRequest,
)

router = APIRouter()
preferences_router = APIRouter()


@router.get("", response_model=NotificationListResponse)
async def list_notifications(user: CurrentUserDep, db: DBConn):
    rows = await db.fetch(
        "SELECT * FROM notifications WHERE user_id = $1 ORDER BY created_at DESC LIMIT 100",
        user.id,
    )
    unread_count = await db.fetchval(
        "SELECT COUNT(*) FROM notifications WHERE user_id = $1 AND is_read = false",
        user.id,
    )
    return NotificationListResponse(
        items=[NotificationResponse(**dict(r)) for r in rows],
        unread_count=unread_count,
    )


@router.patch("/{notification_id}/read", response_model=NotificationResponse)
async def mark_notification_read(notification_id: UUID, user: CurrentUserDep, db: DBConn):
    row = await db.fetchrow(
        "UPDATE notifications SET is_read = true, read_at = NOW() WHERE id = $1 AND user_id = $2 RETURNING *",
        notification_id, user.id,
    )
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Notification not found")
    return NotificationResponse(**dict(row))


@router.post("/read-all")
async def mark_all_read(user: CurrentUserDep, db: DBConn):
    await db.execute(
        "UPDATE notifications SET is_read = true, read_at = NOW() WHERE user_id = $1 AND is_read = false",
        user.id,
    )
    return {"message": "All notifications marked as read"}


@preferences_router.get("", response_model=NotificationPreferencesResponse)
async def get_notification_preferences(user: CurrentUserDep, db: DBConn):
    row = await db.fetchrow(
        "SELECT muted_categories, email_enabled FROM notification_preferences WHERE user_id = $1", user.id
    )
    if not row:
        return NotificationPreferencesResponse(muted_categories=[], email_enabled=True)
    return NotificationPreferencesResponse(
        muted_categories=row["muted_categories"] or [], email_enabled=row["email_enabled"]
    )


@preferences_router.patch("", response_model=NotificationPreferencesResponse)
async def update_notification_preferences(
    body: PatchNotificationPreferencesRequest, user: CurrentUserDep, db: DBConn,
):
    await db.execute(
        """
        INSERT INTO notification_preferences (user_id, muted_categories, email_enabled, updated_at)
        VALUES ($1, $2, $3, NOW())
        ON CONFLICT (user_id) DO UPDATE SET
            muted_categories = EXCLUDED.muted_categories,
            email_enabled = EXCLUDED.email_enabled,
            updated_at = NOW()
        """,
        user.id, body.muted_categories, body.email_enabled,
    )
    return NotificationPreferencesResponse(
        muted_categories=body.muted_categories, email_enabled=body.email_enabled
    )
