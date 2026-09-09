"""
Shared user-activation primitive — used by admin.py's single-user disable/enable
and admin_clients.py's org-wide suspend/reactivate (which loops this per member),
so the local-flag + Supabase-ban pairing can't drift into two copies.
"""

import logging
from typing import Optional
from uuid import UUID

import httpx
from fastapi import Request

from app.audit import log_audit
from app.config import settings

log = logging.getLogger(__name__)


def _sb_headers() -> dict:
    return {
        "apikey": settings.supabase_service_role_key,
        "Authorization": f"Bearer {settings.supabase_service_role_key}",
        "Content-Type": "application/json",
    }


async def sb_ban_user(user_id: UUID, ban: bool) -> None:
    """Best-effort Supabase Auth ban/unban — defense in depth on top of the local
    is_active flag, which is what deps.py actually enforces immediately. Never
    raises: a Supabase-side failure must not block the local disable/enable."""
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            await client.put(
                f"{settings.supabase_url}/auth/v1/admin/users/{user_id}",
                headers=_sb_headers(),
                json={"ban_duration": "876000h" if ban else "none"},
            )
    except Exception as e:
        log.warning(f"Supabase ban/unban call failed for {user_id}: {e}")


async def set_user_active(conn, user_id: UUID, active: bool) -> None:
    await conn.execute("UPDATE users SET is_active = $2, updated_at = NOW() WHERE id = $1", user_id, active)
    await sb_ban_user(user_id, not active)


async def suspend_org(
    conn,
    org_id: UUID,
    *,
    actor_user_id: Optional[UUID],
    actor_role: Optional[str],
    request: Optional[Request] = None,
) -> list[UUID]:
    """Disables every active member of org_id and writes the client_org_suspended
    audit row. actor_user_id/actor_role are Optional so a webhook-triggered call
    (no human admin) can pass (None, "system") — reactivate_client's snapshot
    reader (app/routers/admin_clients.py) keys off the action name only, so it
    works unchanged for either kind of caller. Shared between admin_clients.py's
    HTTP route and app/routers/billing.py's refund/dispute webhook handlers."""
    member_ids = [
        r["user_id"]
        for r in await conn.fetch(
            """
            SELECT om.user_id FROM organization_members om JOIN users u ON u.id = om.user_id
            WHERE om.organization_id = $1 AND om.is_active = true AND u.is_active = true
            """,
            org_id,
        )
    ]
    for user_id in member_ids:
        await set_user_active(conn, user_id, False)

    await log_audit(
        conn, actor_user_id=actor_user_id, actor_role=actor_role,
        action="client_org_suspended", resource_type="organizations", resource_id=str(org_id),
        new={"disabled_user_ids": [str(u) for u in member_ids]}, request=request,
    )
    return member_ids
