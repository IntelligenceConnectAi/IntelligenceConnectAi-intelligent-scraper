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


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(security)],
) -> CurrentUser:
    payload = verify_jwt(credentials.credentials)
    user_id = payload.get("sub")
    email = payload.get("email")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token missing 'sub' claim",
        )
    return CurrentUser(id=UUID(user_id), email=email or "")


async def get_db_conn() -> AsyncGenerator[asyncpg.Connection, None]:
    pool = get_pool()
    async with pool.acquire() as conn:
        yield conn


CurrentUserDep = Annotated[CurrentUser, Depends(get_current_user)]
DBConn = Annotated[asyncpg.Connection, Depends(get_db_conn)]