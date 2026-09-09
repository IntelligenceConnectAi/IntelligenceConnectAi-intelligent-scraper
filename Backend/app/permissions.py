"""
Permission guards built on top of CurrentUserDep.

Kept separate from app/deps.py deliberately: org/permission data is only needed by
the new /admin/* routes, not by every authenticated request, so it's loaded lazily
here rather than joined into the hot-path get_current_user() lookup.
"""

from typing import Annotated
from uuid import UUID

import asyncpg
from fastapi import Depends, HTTPException, status

from app.deps import CurrentUser, CurrentUserDep, DBConn


def RequireSuperAdmin(user: CurrentUserDep) -> CurrentUser:
    if user.platform_role != "super_admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Super admin access required")
    return user


def RequireAdmin(user: CurrentUserDep) -> CurrentUser:
    if user.platform_role not in ("admin", "super_admin"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")
    return user


async def get_admin_permissions(
    user: Annotated[CurrentUser, Depends(RequireAdmin)],
    db: DBConn,
) -> list[str]:
    """Permission keys granted to the current admin. Super admins implicitly hold all of them."""
    if user.platform_role == "super_admin":
        return ["operations_admin", "people_leads_admin", "support_admin", "billing_admin"]
    rows = await db.fetch(
        "SELECT permission_key FROM admin_permissions WHERE admin_user_id = $1",
        user.id,
    )
    return [r["permission_key"] for r in rows]


async def get_admin_user_ids_with_permission(db: asyncpg.Connection, permission_key: str) -> list[UUID]:
    """All admin/super_admin users who can act on permission_key — for routing
    notifications, not gating a request. Super admins hold every permission
    implicitly (mirrors get_admin_permissions' own rule). Excludes disabled
    admins, matching get_current_user's is_active enforcement elsewhere."""
    rows = await db.fetch(
        """
        SELECT id FROM users
        WHERE is_active = true
          AND (platform_role = 'super_admin'
               OR (platform_role = 'admin' AND EXISTS (
                     SELECT 1 FROM admin_permissions ap
                     WHERE ap.admin_user_id = users.id AND ap.permission_key = $1
                   )))
        """,
        permission_key,
    )
    return [r["id"] for r in rows]


AdminPermissionsDep = Annotated[list[str], Depends(get_admin_permissions)]
SuperAdminDep = Annotated[CurrentUser, Depends(RequireSuperAdmin)]
AdminDep = Annotated[CurrentUser, Depends(RequireAdmin)]


def RequireAdminPermission(permission_key: str):
    async def _check(permissions: AdminPermissionsDep) -> list[str]:
        if permission_key not in permissions:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Missing required permission: {permission_key}",
            )
        return permissions

    return _check
