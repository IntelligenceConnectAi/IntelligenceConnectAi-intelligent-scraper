"""
Phase 6 — in-app notification creation (§19, §27's best-effort hook pattern).
Every call site MUST wrap this in its own try/except so a notification failure
never fails an already-successful operation — same posture as
app/leads_index.py's index_business_job_files/index_people_lead_file. This
function itself does not swallow errors from the notification INSERT;
isolation there is the caller's responsibility (matches every existing hook
call site exactly). The additive email-sending step below is different: it's
layered on top of an already-successful INSERT, so it's isolated internally —
a DB hiccup on the extra "fetch the user's email" lookup must not turn an
otherwise-successful notification write into a caller-visible failure.
"""

import logging
from typing import Optional
from uuid import UUID

import asyncpg

from app.emails import EMAIL_ELIGIBLE_TYPES, render_notification_email, send_email
from app.permissions import get_admin_user_ids_with_permission

log = logging.getLogger(__name__)


async def create_notification(
    conn: asyncpg.Connection,
    *,
    user_id: UUID,
    category: str,
    type: str,
    title: str,
    body: str,
    link_section: Optional[str] = None,
    link_sub_tab: Optional[str] = None,
    link_resource_id: Optional[str] = None,
) -> None:
    prefs = await conn.fetchrow(
        "SELECT muted_categories, email_enabled FROM notification_preferences WHERE user_id = $1",
        user_id,
    )
    muted = prefs["muted_categories"] if prefs else None
    if muted and category in muted:
        return

    await conn.execute(
        """
        INSERT INTO notifications
            (user_id, category, type, title, body, link_section, link_sub_tab, link_resource_id)
        VALUES ($1,$2,$3,$4,$5,$6,$7,$8)
        """,
        user_id, category, type, title, body, link_section, link_sub_tab, link_resource_id,
    )

    email_enabled = prefs["email_enabled"] if prefs else True  # no row yet == column DEFAULT true
    if type in EMAIL_ELIGIBLE_TYPES and email_enabled:
        try:
            email = await conn.fetchval("SELECT email FROM users WHERE id = $1", user_id)
            if email:
                await send_email(
                    to=email, subject=title,
                    html_body=render_notification_email(title=title, body=body),
                )
        except Exception as e:
            log.error(f"create_notification: email send failed for user {user_id} type={type}: {e}", exc_info=True)


async def notify_admins_with_permission(
    conn: asyncpg.Connection,
    *,
    permission_key: str,
    category: str,
    type: str,
    title: str,
    body: str,
    link_section: Optional[str] = None,
    link_sub_tab: Optional[str] = None,
    link_resource_id: Optional[str] = None,
) -> None:
    """Notify every admin/super_admin holding permission_key. Sequential, not
    asyncio.gather — conn is a single asyncpg.Connection and concurrent use of
    one connection from multiple coroutines is unsafe. Admin recipient counts
    are small (a handful), so this is not a real bottleneck."""
    admin_ids = await get_admin_user_ids_with_permission(conn, permission_key)
    for admin_id in admin_ids:
        try:
            await create_notification(
                conn, user_id=admin_id, category=category, type=type, title=title, body=body,
                link_section=link_section, link_sub_tab=link_sub_tab, link_resource_id=link_resource_id,
            )
        except Exception as e:
            log.error(f"notify_admins_with_permission: failed for admin {admin_id}: {e}", exc_info=True)
