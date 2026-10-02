"""
Clients Management Core tier: search/filter, org-wide suspend/reactivate (built on
the existing per-user disable/enable primitive, looped over organization_members),
and admin plan reassignment. See app/routers/admin_clients.py's module docstring
for the design rationale (why suspend loops the whole roster, why reactivate uses
the suspend action's own audit_logs row as its restore snapshot).
"""

from uuid import uuid4

import pytest

from tests.factories import add_member, make_admin, make_client, make_user

pytestmark = pytest.mark.asyncio(loop_scope="session")


async def test_search_filters_clients_by_org_name(client, db_conn, auth_user_pool, make_headers):
    admin_user = auth_user_pool[0]
    await make_admin(db_conn, admin_user, platform_role="admin")

    owner1, owner2 = auth_user_pool[1], auth_user_pool[2]
    tag = uuid4().hex[:8]
    _uid1, org1 = await make_client(db_conn, owner1, org_name=f"Acme-{tag}")
    _uid2, org2 = await make_client(db_conn, owner2, org_name=f"Zenith-{uuid4().hex[:8]}")

    resp = await client.get(f"/admin/clients?q=Acme-{tag}", headers=make_headers(admin_user))
    assert resp.status_code == 200
    ids = {c["id"] for c in resp.json()}
    assert str(org1) in ids
    assert str(org2) not in ids


async def test_active_filter_excludes_suspended_clients(client, db_conn, auth_user_pool, make_headers):
    super_admin = auth_user_pool[0]
    await make_admin(db_conn, super_admin, platform_role="super_admin")

    owner1, owner2 = auth_user_pool[1], auth_user_pool[2]
    _uid1, org1 = await make_client(db_conn, owner1)
    _uid2, org2 = await make_client(db_conn, owner2)

    resp = await client.post(f"/admin/clients/{org2}/suspend", headers=make_headers(super_admin))
    assert resp.status_code == 200

    resp = await client.get("/admin/clients?active=false", headers=make_headers(super_admin))
    ids = {c["id"] for c in resp.json()}
    assert str(org2) in ids
    assert str(org1) not in ids

    resp = await client.get("/admin/clients?active=true", headers=make_headers(super_admin))
    ids = {c["id"] for c in resp.json()}
    assert str(org1) in ids
    assert str(org2) not in ids


async def test_plain_admin_cannot_suspend_or_change_plan(client, db_conn, auth_user_pool, make_headers):
    plain_admin = auth_user_pool[0]
    await make_admin(db_conn, plain_admin, platform_role="admin")

    owner = auth_user_pool[1]
    _uid, org_id = await make_client(db_conn, owner)

    resp = await client.post(f"/admin/clients/{org_id}/suspend", headers=make_headers(plain_admin))
    assert resp.status_code == 403

    resp = await client.patch(
        f"/admin/clients/{org_id}/plan", json={"plan_id": "pro"}, headers=make_headers(plain_admin)
    )
    assert resp.status_code == 403


async def test_suspend_disables_owner_and_active_members_but_not_removed_ones(
    client, db_conn, auth_user_pool, make_headers
):
    super_admin = auth_user_pool[0]
    await make_admin(db_conn, super_admin, platform_role="super_admin")

    owner = auth_user_pool[1]
    owner_id, org_id = await make_client(db_conn, owner)

    member_a = auth_user_pool[2]
    await make_user(db_conn, member_a["id"], member_a["email"], platform_role="client")
    await add_member(db_conn, org_id, member_a["id"])

    member_b = auth_user_pool[3]
    await make_user(db_conn, member_b["id"], member_b["email"], platform_role="client")
    await add_member(db_conn, org_id, member_b["id"])
    await db_conn.execute(
        "UPDATE organization_members SET is_active = false WHERE organization_id = $1 AND user_id = $2",
        org_id, member_b["id"],
    )

    resp = await client.post(f"/admin/clients/{org_id}/suspend", headers=make_headers(super_admin))
    assert resp.status_code == 200

    owner_active = await db_conn.fetchval("SELECT is_active FROM users WHERE id = $1", owner_id)
    a_active = await db_conn.fetchval("SELECT is_active FROM users WHERE id = $1", member_a["id"])
    b_active = await db_conn.fetchval("SELECT is_active FROM users WHERE id = $1", member_b["id"])

    assert owner_active is False
    assert a_active is False
    assert b_active is True  # removed from the org before suspend — untouched


async def test_reactivate_restores_only_the_suspended_snapshot(client, db_conn, auth_user_pool, make_headers):
    super_admin = auth_user_pool[0]
    await make_admin(db_conn, super_admin, platform_role="super_admin")

    owner = auth_user_pool[1]
    owner_id, org_id = await make_client(db_conn, owner)

    member_a = auth_user_pool[2]
    await make_user(db_conn, member_a["id"], member_a["email"], platform_role="client")
    await add_member(db_conn, org_id, member_a["id"])

    member_b = auth_user_pool[3]
    await make_user(db_conn, member_b["id"], member_b["email"], platform_role="client")
    await add_member(db_conn, org_id, member_b["id"])

    # member_b is individually disabled BEFORE the org-level suspend.
    resp = await client.post(f"/admin/users/{member_b['id']}/disable", headers=make_headers(super_admin))
    assert resp.status_code == 200

    resp = await client.post(f"/admin/clients/{org_id}/suspend", headers=make_headers(super_admin))
    assert resp.status_code == 200

    resp = await client.post(f"/admin/clients/{org_id}/reactivate", headers=make_headers(super_admin))
    assert resp.status_code == 200

    owner_active = await db_conn.fetchval("SELECT is_active FROM users WHERE id = $1", owner_id)
    a_active = await db_conn.fetchval("SELECT is_active FROM users WHERE id = $1", member_a["id"])
    b_active = await db_conn.fetchval("SELECT is_active FROM users WHERE id = $1", member_b["id"])

    assert owner_active is True
    assert a_active is True
    assert b_active is False  # reactivate must not clobber a pre-existing individual disable


async def test_plan_change_updates_subscription_and_defaults_to_active_status(
    client, db_conn, auth_user_pool, make_headers
):
    super_admin = auth_user_pool[0]
    await make_admin(db_conn, super_admin, platform_role="super_admin")

    owner = auth_user_pool[1]
    owner_id, org_id = await make_client(db_conn, owner, plan_id="starter")

    resp = await client.patch(
        f"/admin/clients/{org_id}/plan", json={"plan_id": "pro"}, headers=make_headers(super_admin)
    )
    assert resp.status_code == 200

    row = await db_conn.fetchrow("SELECT plan_id, status FROM subscriptions WHERE user_id = $1", owner_id)
    assert row["plan_id"] == "pro"
    assert row["status"] == "active"

    resp = await client.get(f"/admin/clients/{org_id}", headers=make_headers(super_admin))
    # plan_id="pro" is branded "Growth" since migrations/0012_lead_topups.sql's
    # rename (plans.id stays stable, only the display name changed).
    assert resp.json()["plan_name"] == "Growth"


async def test_plan_change_sets_period_end_for_a_brand_new_subscription_row(
    client, db_conn, auth_user_pool, make_headers,
):
    """Regression test: an org with no subscriptions row at all previously got one
    with current_period_end left NULL forever, which silently broke every feature
    keyed off the billing-period window (People Leads' monthly limit, the
    dashboard's usage display, and the additional-records topup checkout, which
    refuses to purchase against an undefined period)."""
    from tests.factories import make_org
    super_admin = auth_user_pool[0]
    await make_admin(db_conn, super_admin, platform_role="super_admin")

    owner = auth_user_pool[1]
    owner_id = await make_user(db_conn, owner["id"], owner["email"])
    org_id = await make_org(db_conn, owner_id)  # no subscriptions row yet

    resp = await client.patch(
        f"/admin/clients/{org_id}/plan", json={"plan_id": "starter"}, headers=make_headers(super_admin)
    )
    assert resp.status_code == 200

    row = await db_conn.fetchrow("SELECT current_period_end FROM subscriptions WHERE user_id = $1", owner_id)
    assert row["current_period_end"] is not None


async def test_plan_change_backfills_null_period_end_without_clobbering_a_real_one(
    client, db_conn, auth_user_pool, make_headers,
):
    from datetime import datetime, timezone
    super_admin = auth_user_pool[0]
    await make_admin(db_conn, super_admin, platform_role="super_admin")

    # Case 1: a subscription already corrupted with a NULL period (simulates the
    # pre-fix bug's existing fallout) gets backfilled, not left NULL.
    broken_owner = auth_user_pool[1]
    broken_owner_id, broken_org_id = await make_client(db_conn, broken_owner, plan_id="starter")
    await db_conn.execute("UPDATE subscriptions SET current_period_end = NULL WHERE user_id = $1", broken_owner_id)

    resp = await client.patch(
        f"/admin/clients/{broken_org_id}/plan", json={"plan_id": "pro"}, headers=make_headers(super_admin)
    )
    assert resp.status_code == 200
    row = await db_conn.fetchrow("SELECT current_period_end FROM subscriptions WHERE user_id = $1", broken_owner_id)
    assert row["current_period_end"] is not None

    # Case 2: an org with a real (e.g. Stripe-sourced) period already set must not
    # have it silently reset by an unrelated manual plan tweak.
    healthy_owner = auth_user_pool[2]
    healthy_owner_id, healthy_org_id = await make_client(db_conn, healthy_owner, plan_id="starter")
    fixed_period_end = datetime(2027, 1, 1, tzinfo=timezone.utc)
    await db_conn.execute(
        "UPDATE subscriptions SET current_period_end = $2 WHERE user_id = $1", healthy_owner_id, fixed_period_end
    )

    resp2 = await client.patch(
        f"/admin/clients/{healthy_org_id}/plan", json={"plan_id": "pro"}, headers=make_headers(super_admin)
    )
    assert resp2.status_code == 200
    row2 = await db_conn.fetchrow("SELECT current_period_end FROM subscriptions WHERE user_id = $1", healthy_owner_id)
    assert row2["current_period_end"] == fixed_period_end


async def test_plan_change_rejects_unknown_plan_id(client, db_conn, auth_user_pool, make_headers):
    super_admin = auth_user_pool[0]
    await make_admin(db_conn, super_admin, platform_role="super_admin")

    owner = auth_user_pool[1]
    _uid, org_id = await make_client(db_conn, owner)

    resp = await client.patch(
        f"/admin/clients/{org_id}/plan", json={"plan_id": "not-a-real-plan"}, headers=make_headers(super_admin)
    )
    assert resp.status_code == 400


async def test_admin_plans_list_includes_non_active_plans(client, db_conn, auth_user_pool, make_headers):
    plain_admin = auth_user_pool[0]
    await make_admin(db_conn, plain_admin, platform_role="admin")

    inactive_id = f"legacy-{uuid4().hex[:8]}"
    await db_conn.execute(
        """
        INSERT INTO plans (id, name, price_monthly, leads_per_month, leads_per_day,
                            cities_per_job, history_days, concurrent_jobs, is_active)
        VALUES ($1, 'Legacy Plan', 99.00, 1000, 33, 5, 30, 5, false)
        """,
        inactive_id,
    )

    resp = await client.get("/admin/clients/plans", headers=make_headers(plain_admin))
    assert resp.status_code == 200
    plan_ids = {p["id"]: p for p in resp.json()}
    assert inactive_id in plan_ids
    assert plan_ids[inactive_id]["is_active"] is False


async def test_suspended_client_owner_login_rejected(client, db_conn, auth_user_pool, make_headers):
    super_admin = auth_user_pool[0]
    await make_admin(db_conn, super_admin, platform_role="super_admin")

    owner = auth_user_pool[1]
    _owner_id, org_id = await make_client(db_conn, owner)

    resp = await client.post(f"/admin/clients/{org_id}/suspend", headers=make_headers(super_admin))
    assert resp.status_code == 200

    resp = await client.get("/auth/me", headers=make_headers(owner))
    assert resp.status_code == 403
    assert "disabled" in resp.json()["detail"].lower()
