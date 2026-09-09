"""
Billing/signup hardening for the GHL-linked Stripe Checkout launch: the
returning-customer registration fix, refund/dispute webhook handling (with the
admin-initiated double-suspend guard), the session_id check-payment fast path,
and the webhook idempotency ledger.

Real Stripe SDK calls that would require a live STRIPE_SECRET_KEY (blank in
local .env) are monkeypatched — flagged per-test below. Everything else
(webhook signature verification, DB state, audit logs, notifications) is
exercised for real, same as every other test in this suite.
"""

import hashlib
import hmac
import json
import time
from decimal import Decimal
from uuid import uuid4

import httpx
import pytest
import stripe

from app.config import settings
from tests.factories import add_member, make_admin, make_client, make_user

pytestmark = pytest.mark.asyncio(loop_scope="session")


def _sign_webhook(payload: bytes) -> str:
    """Mirrors Stripe's own signing scheme — valid even with a blank webhook
    secret (matches this project's local .env), since the HMAC key is just
    whatever STRIPE_WEBHOOK_SECRET is, empty string included."""
    timestamp = int(time.time())
    signed_payload = f"{timestamp}.{payload.decode()}"
    sig = hmac.new(settings.stripe_webhook_secret.encode(), signed_payload.encode(), hashlib.sha256).hexdigest()
    return f"t={timestamp},v1={sig}"


async def _post_webhook(client, event: dict):
    payload = json.dumps(event).encode()
    headers = {"stripe-signature": _sign_webhook(payload), "content-type": "application/json"}
    return await client.post("/billing/webhook", content=payload, headers=headers)


def _charge_event(event_id: str, *, customer: str, refunded: bool, amount_refunded: int, charge_id: str = None):
    return {
        "id": event_id,
        "type": "charge.refunded",
        "data": {"object": {
            "id": charge_id or f"ch_{uuid4().hex[:16]}",
            "customer": customer,
            "refunded": refunded,
            "amount_refunded": amount_refunded,
            "currency": "usd",
        }},
    }


def _dispute_event(event_id: str, *, charge_id: str):
    return {
        "id": event_id,
        "type": "charge.dispute.created",
        "data": {"object": {
            "id": f"dp_{uuid4().hex[:16]}",
            "charge": charge_id,
            "amount": 5000,
            "currency": "usd",
            "reason": "fraudulent",
        }},
    }


# ── FRONTEND_BASE_URL (unit-level — full /billing/checkout needs a live Stripe key) ──

async def test_checkout_url_builder_uses_frontend_base_url_setting(monkeypatch):
    from app.routers.billing import CheckoutRequest, _build_checkout_urls
    monkeypatch.setattr(settings, "frontend_base_url", "https://app.example.com")

    body = CheckoutRequest(price_id="price_x")
    success_url, cancel_url = _build_checkout_urls(body, "")
    assert success_url.startswith("https://app.example.com/signup")
    assert cancel_url.startswith("https://app.example.com")

    success_url2, _ = _build_checkout_urls(body, "customer@example.com")
    assert "customer%40example.com" in success_url2


# ── Registration hardening ──

async def test_check_payment_no_pending_no_account_returns_unpaid(client):
    resp = await client.get(f"/auth/check-payment?email=nobody-{uuid4().hex[:8]}@example.test")
    assert resp.status_code == 200
    body = resp.json()
    assert body["paid"] is False
    assert body["existing_account"] is False


async def test_check_payment_new_customer_with_pending_signup_returns_paid_not_existing(client, db_conn):
    email = f"newcustomer-{uuid4().hex[:8]}@example.test"
    await db_conn.execute(
        "INSERT INTO pending_signups (email, plan_id) VALUES ($1, 'pro')", email,
    )
    resp = await client.get(f"/auth/check-payment?email={email}")
    body = resp.json()
    assert body["paid"] is True
    assert body["plan_id"] == "pro"
    assert body["existing_account"] is False


async def test_check_payment_existing_account_with_new_pending_signup_attaches_plan_and_clears_pending(
    client, db_conn, auth_user_pool,
):
    owner = auth_user_pool[0]
    owner_id, _org_id = await make_client(db_conn, owner, plan_id="starter")
    await db_conn.execute(
        "INSERT INTO pending_signups (email, plan_id) VALUES ($1, 'pro')", owner["email"],
    )

    resp = await client.get(f"/auth/check-payment?email={owner['email']}")
    body = resp.json()
    assert body["paid"] is True
    assert body["plan_id"] == "pro"
    assert body["existing_account"] is True

    row = await db_conn.fetchrow("SELECT plan_id, status FROM subscriptions WHERE user_id = $1", owner_id)
    assert row["plan_id"] == "pro"
    assert row["status"] == "active"
    pending_left = await db_conn.fetchval(
        "SELECT COUNT(*) FROM pending_signups WHERE lower(email) = $1", owner["email"].lower()
    )
    assert pending_left == 0


async def test_check_payment_existing_account_no_pending_reports_existing_without_mutating(client, db_conn, auth_user_pool):
    owner = auth_user_pool[0]
    await make_client(db_conn, owner, plan_id="starter")

    resp = await client.get(f"/auth/check-payment?email={owner['email']}")
    body = resp.json()
    assert body["paid"] is False
    assert body["existing_account"] is True


async def test_register_rejects_when_no_pending_signup(client):
    resp = await client.post(
        "/auth/register",
        json={"email": f"nopending-{uuid4().hex[:8]}@example.test", "password": "Password123!", "full_name": "Nobody"},
    )
    assert resp.status_code == 403


async def test_register_returning_customer_conflict_attaches_plan_instead_of_duplicate_account(
    client, db_conn, auth_user_pool,
):
    owner = auth_user_pool[0]
    owner_id, _org_id = await make_client(db_conn, owner, plan_id="starter")
    await db_conn.execute(
        "INSERT INTO pending_signups (email, plan_id) VALUES ($1, 'elite')", owner["email"],
    )

    resp = await client.post(
        "/auth/register",
        json={"email": owner["email"], "password": "Password123!", "full_name": "Whatever"},
    )
    assert resp.status_code == 409

    row = await db_conn.fetchrow("SELECT plan_id FROM subscriptions WHERE user_id = $1", owner_id)
    assert row["plan_id"] == "elite"
    pending_left = await db_conn.fetchval(
        "SELECT COUNT(*) FROM pending_signups WHERE lower(email) = $1", owner["email"].lower()
    )
    assert pending_left == 0


async def test_register_brand_new_signup_writes_stripe_customer_id_onto_users(client, db_conn):
    """Regression test: a brand-new signup's users row was missing
    stripe_customer_id entirely (only subscriptions.stripe_customer_id got set),
    which silently broke /billing/portal, /billing/invoices, and
    /billing/payment-method for every first-time customer — found via a real
    test-mode purchase, not caught by any prior test since none exercised the
    success path of POST /auth/register (only its 403/409 guard branches)."""
    email = f"newsignup-{uuid4().hex[:8]}@example.test"
    customer_id = f"cus_{uuid4().hex[:16]}"
    await db_conn.execute(
        """
        INSERT INTO pending_signups (email, plan_id, stripe_customer_id, stripe_subscription_id)
        VALUES ($1, 'pro', $2, $3)
        """,
        email, customer_id, f"sub_{uuid4().hex[:16]}",
    )

    resp = await client.post(
        "/auth/register",
        json={"email": email, "password": "Password123!", "full_name": "New Signup"},
    )
    assert resp.status_code == 200
    user_id = resp.json()["user"]["id"]

    try:
        row = await db_conn.fetchrow("SELECT stripe_customer_id FROM users WHERE id = $1", user_id)
        assert row["stripe_customer_id"] == customer_id

        sub_row = await db_conn.fetchrow("SELECT stripe_customer_id FROM subscriptions WHERE user_id = $1", user_id)
        assert sub_row["stripe_customer_id"] == customer_id
    finally:
        # The Supabase Auth user this created is a real side effect outside
        # db_conn's rolled-back transaction — clean it up explicitly, same as
        # auth_user_pool's own teardown in conftest.py.
        async with httpx.AsyncClient(timeout=20) as sb:
            await sb.delete(
                f"{settings.supabase_url}/auth/v1/admin/users/{user_id}",
                headers={
                    "apikey": settings.supabase_service_role_key,
                    "Authorization": f"Bearer {settings.supabase_service_role_key}",
                },
            )


# ── Refund / dispute webhooks ──

async def test_webhook_charge_refunded_full_suspends_org_and_notifies_owner(client, db_conn, auth_user_pool):
    owner = auth_user_pool[0]
    owner_id, org_id = await make_client(db_conn, owner)
    customer_id = f"cus_{uuid4().hex[:16]}"
    await db_conn.execute("UPDATE users SET stripe_customer_id = $2 WHERE id = $1", owner_id, customer_id)

    resp = await _post_webhook(client, _charge_event(
        f"evt_{uuid4().hex[:16]}", customer=customer_id, refunded=True, amount_refunded=4900,
    ))
    assert resp.status_code == 200

    owner_active = await db_conn.fetchval("SELECT is_active FROM users WHERE id = $1", owner_id)
    assert owner_active is False

    audit_action = await db_conn.fetchval(
        "SELECT action FROM audit_logs WHERE resource_type='organizations' AND resource_id=$1 AND action='charge_refunded'",
        str(org_id),
    )
    assert audit_action == "charge_refunded"

    notif = await db_conn.fetchval(
        "SELECT type FROM notifications WHERE user_id = $1 AND type = 'refund_processed'", owner_id
    )
    assert notif == "refund_processed"


async def test_webhook_charge_refunded_partial_does_not_suspend_but_notifies(client, db_conn, auth_user_pool):
    owner = auth_user_pool[0]
    owner_id, org_id = await make_client(db_conn, owner)
    customer_id = f"cus_{uuid4().hex[:16]}"
    await db_conn.execute("UPDATE users SET stripe_customer_id = $2 WHERE id = $1", owner_id, customer_id)

    resp = await _post_webhook(client, _charge_event(
        f"evt_{uuid4().hex[:16]}", customer=customer_id, refunded=False, amount_refunded=1000,
    ))
    assert resp.status_code == 200

    owner_active = await db_conn.fetchval("SELECT is_active FROM users WHERE id = $1", owner_id)
    assert owner_active is True

    notif = await db_conn.fetchval(
        "SELECT type FROM notifications WHERE user_id = $1 AND type = 'refund_processed'", owner_id
    )
    assert notif == "refund_processed"


async def test_webhook_charge_refunded_admin_initiated_skips_auto_suspend_when_already_handled(
    client, db_conn, auth_user_pool,
):
    from app.audit import log_audit

    owner = auth_user_pool[0]
    owner_id, org_id = await make_client(db_conn, owner)
    customer_id = f"cus_{uuid4().hex[:16]}"
    await db_conn.execute("UPDATE users SET stripe_customer_id = $2 WHERE id = $1", owner_id, customer_id)

    charge_id = f"ch_{uuid4().hex[:16]}"
    # Simulate the admin refund route's synchronous audit write, which chose NOT
    # to suspend (a goodwill refund) — the owner stays active.
    await log_audit(
        db_conn, actor_user_id=owner_id, actor_role="super_admin", action="admin_refund_issued",
        resource_type="organizations", resource_id=str(org_id),
        new={"invoice_id": "in_test", "charge_id": charge_id, "refund_id": "re_test", "amount": "full", "reason": None},
    )

    resp = await _post_webhook(client, _charge_event(
        f"evt_{uuid4().hex[:16]}", customer=customer_id, refunded=True, amount_refunded=4900, charge_id=charge_id,
    ))
    assert resp.status_code == 200

    owner_active = await db_conn.fetchval("SELECT is_active FROM users WHERE id = $1", owner_id)
    assert owner_active is True  # admin's choice not to suspend is respected

    refunded_count = await db_conn.fetchval(
        "SELECT COUNT(*) FROM audit_logs WHERE resource_type='organizations' AND resource_id=$1 AND action='charge_refunded'",
        str(org_id),
    )
    assert refunded_count == 0  # webhook didn't re-log/re-decide


async def test_webhook_dispute_created_always_suspends_regardless_of_amount(
    client, db_conn, auth_user_pool, monkeypatch,
):
    """The one necessarily-monkeypatched Stripe call in this file: dispute payloads
    carry `charge`, not `customer`, so the handler must retrieve the charge from
    Stripe to learn the customer id — unavoidable without a live Stripe key."""
    owner = auth_user_pool[0]
    owner_id, org_id = await make_client(db_conn, owner)
    customer_id = f"cus_{uuid4().hex[:16]}"
    await db_conn.execute("UPDATE users SET stripe_customer_id = $2 WHERE id = $1", owner_id, customer_id)

    charge_id = f"ch_{uuid4().hex[:16]}"
    monkeypatch.setattr(stripe.Charge, "retrieve", staticmethod(lambda cid: {"customer": customer_id}))

    resp = await _post_webhook(client, _dispute_event(f"evt_{uuid4().hex[:16]}", charge_id=charge_id))
    assert resp.status_code == 200

    owner_active = await db_conn.fetchval("SELECT is_active FROM users WHERE id = $1", owner_id)
    assert owner_active is False

    notif = await db_conn.fetchval(
        "SELECT type FROM notifications WHERE user_id = $1 AND type = 'payment_disputed'", owner_id
    )
    assert notif == "payment_disputed"


async def test_webhook_dispute_created_also_notifies_billing_admin(
    client, db_conn, auth_user_pool, monkeypatch,
):
    owner = auth_user_pool[1]
    owner_id, org_id = await make_client(db_conn, owner)
    customer_id = f"cus_{uuid4().hex[:16]}"
    await db_conn.execute("UPDATE users SET stripe_customer_id = $2 WHERE id = $1", owner_id, customer_id)

    billing_admin = auth_user_pool[2]
    await make_admin(db_conn, billing_admin, platform_role="admin", permissions=["billing_admin"])

    charge_id = f"ch_{uuid4().hex[:16]}"
    monkeypatch.setattr(stripe.Charge, "retrieve", staticmethod(lambda cid: {"customer": customer_id}))

    resp = await _post_webhook(client, _dispute_event(f"evt_{uuid4().hex[:16]}", charge_id=charge_id))
    assert resp.status_code == 200

    admin_notif = await db_conn.fetchval(
        "SELECT type FROM notifications WHERE user_id = $1 AND type = 'payment_disputed'", billing_admin["id"]
    )
    assert admin_notif == "payment_disputed"


async def test_webhook_unknown_stripe_customer_is_a_noop_not_an_error(client):
    resp = await _post_webhook(client, _charge_event(
        f"evt_{uuid4().hex[:16]}", customer=f"cus_{uuid4().hex[:16]}", refunded=True, amount_refunded=100,
    ))
    assert resp.status_code == 200


async def test_webhook_replays_same_event_id_are_not_reprocessed(client, db_conn, auth_user_pool):
    owner = auth_user_pool[0]
    owner_id, org_id = await make_client(db_conn, owner)
    customer_id = f"cus_{uuid4().hex[:16]}"
    await db_conn.execute("UPDATE users SET stripe_customer_id = $2 WHERE id = $1", owner_id, customer_id)

    event = _charge_event(f"evt_{uuid4().hex[:16]}", customer=customer_id, refunded=True, amount_refunded=4900)
    resp1 = await _post_webhook(client, event)
    assert resp1.status_code == 200
    resp2 = await _post_webhook(client, event)  # exact same event id
    assert resp2.status_code == 200

    refunded_count = await db_conn.fetchval(
        "SELECT COUNT(*) FROM audit_logs WHERE resource_type='organizations' AND resource_id=$1 AND action='charge_refunded'",
        str(org_id),
    )
    assert refunded_count == 1  # not reprocessed

    status = await db_conn.fetchval("SELECT status FROM stripe_events WHERE id = $1", event["id"])
    assert status == "processed"


async def test_webhook_invalid_signature_rejected(client):
    payload = json.dumps({"id": "evt_bad", "type": "charge.refunded", "data": {"object": {}}}).encode()
    resp = await client.post(
        "/billing/webhook", content=payload,
        headers={"stripe-signature": "t=1,v1=deadbeef", "content-type": "application/json"},
    )
    assert resp.status_code == 400


async def test_webhook_records_failed_status_when_handler_raises(client, db_conn):
    event_id = f"evt_{uuid4().hex[:16]}"
    # customer.subscription.updated with no "items" key raises inside the existing handler
    event = {"id": event_id, "type": "customer.subscription.updated", "data": {"object": {"id": "sub_bad"}}}
    resp = await _post_webhook(client, event)
    assert resp.status_code == 500

    status = await db_conn.fetchval("SELECT status FROM stripe_events WHERE id = $1", event_id)
    assert status == "failed"


# ── Admin refund route ──

async def test_admin_list_client_invoices_requires_admin(client, db_conn, auth_user_pool):
    owner = auth_user_pool[0]
    _owner_id, org_id = await make_client(db_conn, owner)
    from tests.conftest import auth_headers
    resp = await client.get(f"/admin/clients/{org_id}/invoices", headers=auth_headers(owner["id"], owner["email"]))
    assert resp.status_code == 403


async def test_admin_list_client_invoices_empty_when_no_stripe_customer(client, db_conn, auth_user_pool, make_headers):
    admin_user = auth_user_pool[0]
    await make_admin(db_conn, admin_user, platform_role="admin")

    owner = auth_user_pool[1]
    _owner_id, org_id = await make_client(db_conn, owner)

    resp = await client.get(f"/admin/clients/{org_id}/invoices", headers=make_headers(admin_user))
    assert resp.status_code == 200
    assert resp.json() == []


async def test_admin_refund_requires_super_admin(client, db_conn, auth_user_pool, make_headers):
    plain_admin = auth_user_pool[0]
    await make_admin(db_conn, plain_admin, platform_role="admin")

    owner = auth_user_pool[1]
    _owner_id, org_id = await make_client(db_conn, owner)

    resp = await client.post(
        f"/admin/clients/{org_id}/refund", json={"invoice_id": "in_test"}, headers=make_headers(plain_admin)
    )
    assert resp.status_code == 403


async def test_admin_refund_rejects_when_no_stripe_customer(client, db_conn, auth_user_pool, make_headers):
    super_admin = auth_user_pool[0]
    await make_admin(db_conn, super_admin, platform_role="super_admin")

    owner = auth_user_pool[1]
    _owner_id, org_id = await make_client(db_conn, owner)

    resp = await client.post(
        f"/admin/clients/{org_id}/refund", json={"invoice_id": "in_test"}, headers=make_headers(super_admin)
    )
    assert resp.status_code == 400


async def test_admin_refund_success_writes_audit_log_and_suspends_when_flagged(
    client, db_conn, auth_user_pool, make_headers, monkeypatch,
):
    """Monkeypatches stripe.Invoice.retrieve/stripe.Refund.create — unavoidable
    without a live Stripe test account, flagged as the plan's one necessary mock
    for this success path."""
    super_admin = auth_user_pool[0]
    await make_admin(db_conn, super_admin, platform_role="super_admin")

    owner = auth_user_pool[1]
    owner_id, org_id = await make_client(db_conn, owner)
    customer_id = f"cus_{uuid4().hex[:16]}"
    await db_conn.execute("UPDATE users SET stripe_customer_id = $2 WHERE id = $1", owner_id, customer_id)

    charge_id = f"ch_{uuid4().hex[:16]}"
    monkeypatch.setattr(
        stripe.Invoice, "retrieve",
        staticmethod(lambda invoice_id: {"customer": customer_id, "status": "paid", "charge": charge_id}),
    )
    monkeypatch.setattr(stripe.Refund, "create", staticmethod(lambda **kwargs: {"id": "re_test123"}))

    resp = await client.post(
        f"/admin/clients/{org_id}/refund",
        json={"invoice_id": "in_test", "also_suspend": True},
        headers=make_headers(super_admin),
    )
    assert resp.status_code == 200
    assert resp.json()["refund_id"] == "re_test123"

    owner_active = await db_conn.fetchval("SELECT is_active FROM users WHERE id = $1", owner_id)
    assert owner_active is False

    audit_row = await db_conn.fetchrow(
        "SELECT new_value_json FROM audit_logs WHERE resource_type='organizations' AND resource_id=$1 AND action='admin_refund_issued'",
        str(org_id),
    )
    assert audit_row is not None
    assert json.loads(audit_row["new_value_json"])["charge_id"] == charge_id


# ── session_id fast path ──

async def test_check_payment_falls_back_to_pending_signups_when_no_session_id(client, db_conn):
    email = f"nosession-{uuid4().hex[:8]}@example.test"
    await db_conn.execute("INSERT INTO pending_signups (email, plan_id) VALUES ($1, 'starter')", email)
    resp = await client.get(f"/auth/check-payment?email={email}")
    assert resp.json()["paid"] is True


async def test_check_payment_session_id_fast_path_backfills_pending_signup(client, db_conn, monkeypatch):
    monkeypatch.setattr(settings, "stripe_starter_price_id", "price_test_starter")
    monkeypatch.setattr(settings, "stripe_pro_price_id", "price_test_pro")
    monkeypatch.setattr(settings, "stripe_elite_price_id", "price_test_elite")

    email = f"viasession-{uuid4().hex[:8]}@example.test"
    fake_session = {
        "payment_status": "paid",
        "customer_details": {"email": email},
        "customer": f"cus_{uuid4().hex[:16]}",
        "subscription": {
            "id": f"sub_{uuid4().hex[:16]}",
            "items": {"data": [{"price": {"id": "price_test_pro"}}]},
        },
    }
    monkeypatch.setattr(
        stripe.checkout.Session, "retrieve", staticmethod(lambda sid, expand=None: fake_session)
    )

    resp = await client.get(f"/auth/check-payment?session_id=cs_test_{uuid4().hex[:16]}")
    body = resp.json()
    assert body["paid"] is True
    assert body["plan_id"] == "pro"
    assert body["email"] == email

    pending = await db_conn.fetchrow("SELECT plan_id FROM pending_signups WHERE lower(email) = $1", email)
    assert pending["plan_id"] == "pro"


async def test_check_payment_session_id_verify_failure_falls_back_gracefully(client, monkeypatch):
    def _raise(*args, **kwargs):
        raise stripe.error.InvalidRequestError("no such session", param=None)
    monkeypatch.setattr(stripe.checkout.Session, "retrieve", staticmethod(_raise))

    resp = await client.get(f"/auth/check-payment?session_id=cs_bad_{uuid4().hex[:16]}")
    assert resp.status_code == 200
    assert resp.json()["paid"] is False
