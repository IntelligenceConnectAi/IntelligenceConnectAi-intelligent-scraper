"""
Admin role/permission/user-management endpoints (Phase 1 + Phase 8, §24.1):
  GET   /admin/me/permissions              -> caller's own platform_role + permissions + has_client_org
  GET   /admin/users                       -> list/search (RequireAdmin — read, see note below)
  POST  /admin/users                       -> create a new admin/super_admin (RequireSuperAdmin)
  PATCH /admin/users/{id}                  -> rename / change admin<->super_admin tier (RequireSuperAdmin)
  POST  /admin/users/{id}/disable          -> works for any user, not just admins (RequireSuperAdmin)
  POST  /admin/users/{id}/enable
  PATCH /admin/users/{id}/permissions      -> grant/revoke one permission_key (RequireSuperAdmin)

GET /admin/users is deliberately RequireAdmin, not super-admin-only: it's the only way
to populate the People Leads/Support "assign to…" dropdowns (both admin_people_leads.py
and admin_support.py take a bare admin_user_id with no server-side membership check),
and the personas who need those dropdowns (people_leads_admin, support_admin) are not
super admins. Every mutation stays RequireSuperAdmin.
"""

import logging
from typing import Literal, Optional
from uuid import UUID

import httpx
from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel

from app.audit import log_audit
from app.config import settings
from app.deps import DBConn
from app.permissions import AdminDep, AdminPermissionsDep, SuperAdminDep
from app.schemas import AdminUserSummary
from app.user_status import set_user_active

log = logging.getLogger(__name__)
router = APIRouter()

VALID_PERMISSION_KEYS = {"operations_admin", "people_leads_admin", "support_admin", "billing_admin"}


def _sb_headers() -> dict:
    return {
        "apikey": settings.supabase_service_role_key,
        "Authorization": f"Bearer {settings.supabase_service_role_key}",
        "Content-Type": "application/json",
    }


async def _fetch_admin_user_summary(db, user_id: UUID) -> AdminUserSummary:
    row = await db.fetchrow(
        """
        SELECT u.id, u.email, u.full_name, u.platform_role, u.is_active, u.created_at,
               COALESCE(array_agg(ap.permission_key) FILTER (WHERE ap.permission_key IS NOT NULL), '{}') AS permissions
        FROM users u
        LEFT JOIN admin_permissions ap ON ap.admin_user_id = u.id
        WHERE u.id = $1
        GROUP BY u.id
        """,
        user_id,
    )
    return AdminUserSummary(**dict(row))


@router.get("/me/permissions")
async def get_my_permissions(user: AdminDep, permissions: AdminPermissionsDep, db: DBConn):
    has_client_org = await db.fetchval(
        "SELECT EXISTS(SELECT 1 FROM organization_members WHERE user_id = $1 AND is_active = true)",
        user.id,
    )
    return {"platform_role": user.platform_role, "permissions": permissions, "has_client_org": has_client_org}


@router.get("/users", response_model=list[AdminUserSummary])
async def list_admin_users(
    admin: AdminDep,
    db: DBConn,
    role: Optional[str] = None,
    permission: Optional[str] = None,
    q: Optional[str] = None,
    limit: int = 100,
):
    conditions: list[str] = []
    params: list = []

    if q:
        params.append(f"%{q}%")
        conditions.append(f"(u.email ILIKE ${len(params)} OR u.full_name ILIKE ${len(params)})")
        if role:
            params.append(role)
            conditions.append(f"u.platform_role = ${len(params)}")
    elif role:
        params.append(role)
        conditions.append(f"u.platform_role = ${len(params)}")
    else:
        conditions.append("u.platform_role IN ('admin','super_admin')")

    if permission:
        params.append(permission)
        conditions.append(
            f"(u.platform_role = 'super_admin' OR EXISTS ("
            f"SELECT 1 FROM admin_permissions ap2 WHERE ap2.admin_user_id = u.id AND ap2.permission_key = ${len(params)}))"
        )

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    params.append(min(limit, 500))
    rows = await db.fetch(
        f"""
        SELECT u.id, u.email, u.full_name, u.platform_role, u.is_active, u.created_at,
               COALESCE(array_agg(ap.permission_key) FILTER (WHERE ap.permission_key IS NOT NULL), '{{}}') AS permissions
        FROM users u
        LEFT JOIN admin_permissions ap ON ap.admin_user_id = u.id
        {where}
        GROUP BY u.id
        ORDER BY u.created_at DESC
        LIMIT ${len(params)}
        """,
        *params,
    )
    return [AdminUserSummary(**dict(r)) for r in rows]


class CreateAdminUserRequest(BaseModel):
    email: str
    password: str
    full_name: str
    platform_role: Literal["admin", "super_admin"] = "admin"
    permissions: list[str] = []


@router.post("/users", response_model=AdminUserSummary, status_code=status.HTTP_201_CREATED)
async def create_admin_user(body: CreateAdminUserRequest, admin: SuperAdminDep, db: DBConn, request: Request):
    bad_perms = set(body.permissions) - VALID_PERMISSION_KEYS
    if bad_perms:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Unknown permission keys: {sorted(bad_perms)}")

    email = body.email.strip().lower()
    password = body.password.strip()
    if len(password) < 8:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Password must be at least 8 characters")

    async with httpx.AsyncClient(timeout=20) as client:
        res = await client.post(
            f"{settings.supabase_url}/auth/v1/admin/users",
            headers=_sb_headers(),
            json={
                "email": email, "password": password, "email_confirm": True,
                "user_metadata": {"full_name": body.full_name.strip()},
            },
        )
        data = res.json()

    if res.status_code not in (200, 201):
        error = data.get("msg") or data.get("message") or "User creation failed"
        log.error(f"Supabase admin user creation failed: {data}")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=error)

    new_user_id = data["id"]

    # Deliberately no organizations row — new admins are staff, not clients.
    async with db.transaction():
        await db.execute(
            """
            INSERT INTO users (id, email, full_name, is_admin, is_active, platform_role)
            VALUES ($1,$2,$3,true,true,$4)
            ON CONFLICT (id) DO UPDATE SET
                full_name = EXCLUDED.full_name, platform_role = EXCLUDED.platform_role, updated_at = NOW()
            """,
            new_user_id, email, body.full_name.strip(), body.platform_role,
        )
        for perm in body.permissions:
            await db.execute(
                """
                INSERT INTO admin_permissions (admin_user_id, permission_key, granted_by)
                VALUES ($1,$2,$3)
                ON CONFLICT (admin_user_id, permission_key) DO NOTHING
                """,
                new_user_id, perm, admin.id,
            )

    await log_audit(
        db, actor_user_id=admin.id, actor_role=admin.platform_role,
        action="admin_user_created", resource_type="users", resource_id=str(new_user_id),
        new={"email": email, "platform_role": body.platform_role, "permissions": body.permissions},
        request=request,
    )
    return await _fetch_admin_user_summary(db, new_user_id)


class UpdateAdminUserRequest(BaseModel):
    full_name: Optional[str] = None
    platform_role: Optional[Literal["admin", "super_admin"]] = None


@router.patch("/users/{user_id}", response_model=AdminUserSummary)
async def update_admin_user(
    user_id: UUID, body: UpdateAdminUserRequest, admin: SuperAdminDep, db: DBConn, request: Request,
):
    target = await db.fetchrow("SELECT platform_role, full_name FROM users WHERE id = $1", user_id)
    if not target:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    if body.platform_role is not None:
        if target["platform_role"] not in ("admin", "super_admin"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Can only change role between admin and super_admin, not for client accounts",
            )
        if user_id == admin.id and body.platform_role != admin.platform_role:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot change your own role")

    new_name = body.full_name.strip() if body.full_name else target["full_name"]
    new_role = body.platform_role or target["platform_role"]

    await db.execute(
        "UPDATE users SET full_name = $2, platform_role = $3, updated_at = NOW() WHERE id = $1",
        user_id, new_name, new_role,
    )
    await log_audit(
        db, actor_user_id=admin.id, actor_role=admin.platform_role,
        action="admin_user_updated", resource_type="users", resource_id=str(user_id),
        previous={"full_name": target["full_name"], "platform_role": target["platform_role"]},
        new={"full_name": new_name, "platform_role": new_role}, request=request,
    )
    return await _fetch_admin_user_summary(db, user_id)


@router.post("/users/{user_id}/disable")
async def disable_user(user_id: UUID, admin: SuperAdminDep, db: DBConn, request: Request):
    if user_id == admin.id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot disable your own account")
    target = await db.fetchrow("SELECT platform_role FROM users WHERE id = $1", user_id)
    if not target:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    await set_user_active(db, user_id, False)

    action = "admin_user_disabled" if target["platform_role"] != "client" else "client_user_disabled"
    await log_audit(
        db, actor_user_id=admin.id, actor_role=admin.platform_role,
        action=action, resource_type="users", resource_id=str(user_id), request=request,
    )
    return {"message": "User disabled"}


@router.post("/users/{user_id}/enable")
async def enable_user(user_id: UUID, admin: SuperAdminDep, db: DBConn, request: Request):
    target = await db.fetchrow("SELECT platform_role FROM users WHERE id = $1", user_id)
    if not target:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    await set_user_active(db, user_id, True)

    action = "admin_user_enabled" if target["platform_role"] != "client" else "client_user_enabled"
    await log_audit(
        db, actor_user_id=admin.id, actor_role=admin.platform_role,
        action=action, resource_type="users", resource_id=str(user_id), request=request,
    )
    return {"message": "User enabled"}


class UpdatePermissionRequest(BaseModel):
    permission_key: str
    action: Literal["grant", "revoke"]


@router.patch("/users/{user_id}/permissions")
async def update_user_permission(
    user_id: UUID,
    body: UpdatePermissionRequest,
    admin: SuperAdminDep,
    db: DBConn,
    request: Request,
):
    if body.permission_key not in VALID_PERMISSION_KEYS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"permission_key must be one of {sorted(VALID_PERMISSION_KEYS)}",
        )

    target = await db.fetchrow(
        "SELECT id, platform_role FROM users WHERE id = $1", user_id
    )
    if not target:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    if body.action == "grant":
        await db.execute(
            """
            INSERT INTO admin_permissions (admin_user_id, permission_key, granted_by)
            VALUES ($1, $2, $3)
            ON CONFLICT (admin_user_id, permission_key) DO NOTHING
            """,
            user_id, body.permission_key, admin.id,
        )
        # Granting a permission implies admin platform access — promote if still 'client'.
        if target["platform_role"] == "client":
            await db.execute(
                "UPDATE users SET platform_role = 'admin', updated_at = NOW() WHERE id = $1",
                user_id,
            )
    else:
        await db.execute(
            "DELETE FROM admin_permissions WHERE admin_user_id = $1 AND permission_key = $2",
            user_id, body.permission_key,
        )

    await log_audit(
        db,
        actor_user_id=admin.id,
        actor_role=admin.platform_role,
        action=f"permission_{body.action}",
        resource_type="admin_permissions",
        resource_id=str(user_id),
        new={"permission_key": body.permission_key, "action": body.action},
        request=request,
    )

    return await _fetch_admin_user_summary(db, user_id)
