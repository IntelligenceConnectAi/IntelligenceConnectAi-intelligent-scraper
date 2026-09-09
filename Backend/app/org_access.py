"""
Org-role guards for Team/Billing, built on top of CurrentUserDep — same "loaded
lazily, not in the hot path" rationale as app/permissions.py (org membership/role
data is only needed by Team and billing-mutation routes, not every authenticated
request).
"""

from typing import Annotated, Optional
from uuid import UUID

import asyncpg
from fastapi import Depends, HTTPException, status

from app.deps import CurrentUser, CurrentUserDep, DBConn


async def get_my_membership(user: CurrentUserDep, db: DBConn) -> asyncpg.Record:
    row = await db.fetchrow(
        "SELECT id, organization_id, user_id, role FROM organization_members WHERE user_id = $1 AND is_active = true LIMIT 1",
        user.id,
    )
    if not row:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No active organization — you may have been removed. Contact your account owner.",
        )
    return row


MyMembershipDep = Annotated[asyncpg.Record, Depends(get_my_membership)]


def RequireOrgRole(*roles: str):
    async def _check(membership: MyMembershipDep) -> asyncpg.Record:
        if membership["role"] not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Requires one of: {', '.join(roles)}",
            )
        return membership

    return _check


async def get_billing_owner_id(conn: asyncpg.Connection, user_id: UUID, org_id: UUID) -> UUID:
    """Resolves which user's `subscriptions` row governs a plan-existence check for
    the acting user. `subscriptions` is PRIMARY KEY(user_id) — strictly one per
    individual — so a non-owner team member has no personal row. Falls back to the
    organization's owner. Used ONLY for People Leads' plan-existence gate (see the
    Phase 6 plan's "non-owner request submission is intentionally partial" section) —
    NOT for jobs.py, where the daily-limit DB function (can_user_scrape) would need
    the same fallback threaded into daily_usage too, which isn't safe to do without
    an organization_id column on jobs/daily_usage (a larger, deferred change)."""
    has_own = await conn.fetchval("SELECT 1 FROM subscriptions WHERE user_id = $1", user_id)
    if has_own:
        return user_id
    owner_id: Optional[UUID] = await conn.fetchval(
        "SELECT owner_user_id FROM organizations WHERE id = $1", org_id
    )
    return owner_id or user_id
