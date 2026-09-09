from dataclasses import dataclass
from typing import Annotated, AsyncGenerator
from uuid import UUID

import asyncpg
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.auth import verify_jwt
from app.db import get_pool

security = HTTPBearer(auto_error=True)


@dataclass
class CurrentUser:
    id: UUID
    email: str
    platform_role: str = "client"


async def get_db_conn() -> AsyncGenerator[asyncpg.Connection, None]:
    pool = get_pool()
    async with pool.acquire() as conn:
        yield conn


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(security)],
    conn: Annotated[asyncpg.Connection, Depends(get_db_conn)],
) -> CurrentUser:
    payload = verify_jwt(credentials.credentials)
    user_id = payload.get("sub")
    email = payload.get("email")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token missing 'sub' claim",
        )
    # Single indexed lookup — kept deliberately cheap since this runs on every
    # authenticated request (including the 3s job-progress poll). Org/permission
    # data is loaded separately, lazily, only by routes that need it (see app/permissions.py).
    row = await conn.fetchrow(
        "SELECT platform_role, is_active FROM users WHERE id = $1", UUID(user_id)
    )
    # Phase 8: enforces admin-disable/client-suspension immediately (same request),
    # not just on next login — without this, a disabled account's still-valid JWT
    # would keep working on every route until natural token expiry.
    if row is not None and not row["is_active"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This account has been disabled. Contact your administrator.",
        )
    platform_role = row["platform_role"] if row is not None else None
    return CurrentUser(id=UUID(user_id), email=email or "", platform_role=platform_role or "client")


CurrentUserDep = Annotated[CurrentUser, Depends(get_current_user)]
DBConn = Annotated[asyncpg.Connection, Depends(get_db_conn)]


async def get_current_org_id(conn: asyncpg.Connection, user_id: UUID) -> UUID:
    """The organization the user is an active member of. Every user has exactly one
    (Phase 1 backfill + register.py's signup hook) until Team invites let a user
    belong to more than one — first real consumer is app/routers/people_leads.py."""
    org_id = await conn.fetchval(
        "SELECT organization_id FROM organization_members WHERE user_id = $1 AND is_active = true LIMIT 1",
        user_id,
    )
    if not org_id:
        # Was a data-integrity impossibility before Team existed (Phase 6) — every
        # user got exactly one org at signup/backfill. DELETE /organization/members/{id}
        # (soft-remove) now makes this reachable for real, so it's a clean 403, not a 500.
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No active organization — you may have been removed. Contact your account owner.",
        )
    return org_id