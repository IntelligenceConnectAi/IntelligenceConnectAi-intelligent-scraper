"""
Representative RBAC gating tests — not exhaustive (100+ routes exist across 8
phases). One route per gate type: missing/garbage/expired token, RequireAdmin,
RequireSuperAdmin, RequireAdminPermission, RequireOrgRole, and the Phase 8
is_active-disabled check (the single highest-value test in this file).
"""

import jwt
import pytest

from app.config import settings
from app.permissions import get_admin_user_ids_with_permission
from tests.factories import add_member, grant_permission, make_admin, make_client, make_people_lead_request, make_user

pytestmark = pytest.mark.asyncio(loop_scope="session")


async def test_no_token_returns_403(client):
    resp = await client.get("/admin/users")
    assert resp.status_code == 403


async def test_garbage_token_returns_401(client):
    resp = await client.get("/admin/users", headers={"Authorization": "Bearer garbage.not.a.jwt"})
    assert resp.status_code == 401


async def test_expired_token_returns_401(client, auth_user_pool):
    user = auth_user_pool[0]
    payload = {
        "sub": str(user["id"]), "email": user["email"], "aud": "authenticated",
        "role": "authenticated", "iat": 1, "exp": 2,
    }
    token = jwt.encode(payload, settings.supabase_jwt_secret, algorithm="HS256")
    resp = await client.get("/admin/users", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 401


async def test_client_role_cannot_list_admin_users(client, db_conn, auth_user_pool, make_headers):
    user = auth_user_pool[1]
    await make_client(db_conn, user)
    resp = await client.get("/admin/users", headers=make_headers(user))
    assert resp.status_code == 403


async def test_plain_admin_cannot_create_admin_user(client, db_conn, auth_user_pool, make_headers):
    user = auth_user_pool[2]
    await make_admin(db_conn, user, platform_role="admin")
    resp = await client.post(
        "/admin/users",
        json={"email": "new-admin@example.test", "password": "Password123!", "full_name": "New Admin"},
        headers=make_headers(user),
    )
    assert resp.status_code == 403


async def test_admin_without_matching_permission_cannot_assign_people_lead(client, db_conn, auth_user_pool, make_headers):
    admin_user = auth_user_pool[3]
    await make_admin(db_conn, admin_user, platform_role="admin", permissions=["support_admin"])

    owner = auth_user_pool[4]
    owner_id, org_id = await make_client(db_conn, owner)
    request_id = await make_people_lead_request(db_conn, org_id, owner_id)

    resp = await client.post(
        f"/admin/people-leads/requests/{request_id}/assign",
        json={"admin_user_id": str(admin_user["id"])},
        headers=make_headers(admin_user),
    )
    assert resp.status_code == 403


async def test_disabled_user_rejected_immediately(client, db_conn, auth_user_pool, make_headers):
    """The Phase 8 fix: a disabled account's still-valid JWT is rejected on the very
    next request, not just on next login."""
    user = auth_user_pool[5]
    await make_user(db_conn, user["id"], user["email"], platform_role="client", is_active=False)

    resp = await client.get("/auth/me", headers=make_headers(user))
    assert resp.status_code == 403
    assert "disabled" in resp.json()["detail"].lower()


async def test_client_member_cannot_rename_organization(client, db_conn, auth_user_pool, make_headers):
    owner = auth_user_pool[6]
    _owner_id, org_id = await make_client(db_conn, owner)

    member = auth_user_pool[7]
    await make_user(db_conn, member["id"], member["email"], platform_role="client")
    await add_member(db_conn, org_id, member["id"], role="client_member")

    resp = await client.patch("/organization", json={"name": "Hacked"}, headers=make_headers(member))
    assert resp.status_code == 403


# ── get_admin_user_ids_with_permission (admin-notification routing) ──

async def test_admin_permission_routing_includes_super_admin_implicitly(db_conn, auth_user_pool):
    super_admin = auth_user_pool[0]
    await make_admin(db_conn, super_admin, platform_role="super_admin")

    ids = {str(i) for i in await get_admin_user_ids_with_permission(db_conn, "billing_admin")}
    assert super_admin["id"] in ids


async def test_admin_permission_routing_includes_matching_holder_excludes_others(db_conn, auth_user_pool):
    holder = auth_user_pool[1]
    await make_admin(db_conn, holder, platform_role="admin", permissions=["support_admin"])

    non_holder = auth_user_pool[2]
    await make_admin(db_conn, non_holder, platform_role="admin", permissions=["billing_admin"])

    client_user = auth_user_pool[3]
    await make_client(db_conn, client_user)

    ids = {str(i) for i in await get_admin_user_ids_with_permission(db_conn, "support_admin")}
    assert holder["id"] in ids
    assert non_holder["id"] not in ids
    assert client_user["id"] not in ids


async def test_admin_permission_routing_excludes_disabled_admin(db_conn, auth_user_pool):
    disabled_admin = auth_user_pool[4]
    await make_user(db_conn, disabled_admin["id"], disabled_admin["email"], platform_role="admin", is_active=False)
    await grant_permission(db_conn, disabled_admin["id"], "operations_admin")

    ids = {str(i) for i in await get_admin_user_ids_with_permission(db_conn, "operations_admin")}
    assert disabled_admin["id"] not in ids
