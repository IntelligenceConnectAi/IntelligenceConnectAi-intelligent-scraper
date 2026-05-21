from datetime import datetime, timezone

from fastapi import APIRouter
from pydantic import BaseModel

from app.deps import CurrentUserDep, DBConn
from app.schemas import User

router = APIRouter()


class UpdateProfileRequest(BaseModel):
    full_name: str


@router.get("/me", response_model=User)
async def get_me(user: CurrentUserDep, db: DBConn) -> User:
    row = await db.fetchrow(
        "SELECT id, email, full_name, is_admin, is_active, created_at FROM users WHERE id = $1",
        user.id,
    )
    if row is None:
        return User(
            id=user.id, email=user.email, full_name=None,
            is_admin=False, is_active=True,
            created_at=datetime.now(timezone.utc),
        )
    return User(**dict(row))


@router.patch("/profile", response_model=User)
async def update_profile(body: UpdateProfileRequest, user: CurrentUserDep, db: DBConn) -> User:
    row = await db.fetchrow(
        """
        UPDATE users SET full_name = $2, updated_at = NOW()
        WHERE id = $1
        RETURNING id, email, full_name, is_admin, is_active, created_at
        """,
        user.id, body.full_name.strip(),
    )
    return User(**dict(row))