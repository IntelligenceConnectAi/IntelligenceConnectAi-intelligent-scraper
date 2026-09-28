"""
Additional-records (lead_topups) billing feature: one-time Stripe checkout
creation/validation, webhook fulfillment, the get_effective_monthly_limit
helper, and its wiring into both People Leads' and Business Leads' monthly
enforcement. Follows test_billing.py's conventions (_sign_webhook/_post_webhook,
make_client, monkeypatch only for real Stripe SDK calls).
"""

import json
import time
import hashlib
import hmac
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest
import stripe

from app.config import settings
from app.leads_usage import get_effective_monthly_limit
from tests.factories import add_member, make_client, make_job, make_lead_topup, make_subscription

pytestmark = pytest.mark.asyncio(loop_scope="session")


def _sign_webhook(payload: bytes) -> str:
    timestamp = int(time.time())
    signed_payload = f"{timestamp}.{payload.decode()}"
    sig = hmac.new(settings.stripe_webhook_secret.encode(), signed_payload.encode(), hashlib.sha256).hexdigest()
    return f"t={timestamp},v1={sig}"


async def _post_webhook(client, event: dict):
    payload = json.dumps(event).encode()
    headers = {"stripe-signature": _sign_webhook(payload), "content-type": "application/json"}
    return await client.post("/billing/webhook", content=payload, headers=headers)


def _topup_checkout_completed_event(event_id: str, *, session_id: str, payment_intent: str = None):
    return {
        "id": event_id,
        "type": "checkout.session.completed",
        "data": {"object": {
            "id": session_id,
            "mode": "payment",
            "payment_intent": payment_intent or f"pi_{uuid4().hex[:16]}",
            "metadata": {"kind": "lead_topup"},
        }},
    }


def _mock_stripe_checkout(monkeypatch):
    """Stripe's real Session object supports both dict and attribute access;
    a SimpleNamespace mirrors the attribute access billing.py actually uses
    (session.id / session.url)."""
    monkeypatch.setattr(
        stripe.checkout.Session, "create",
        staticmethod(lambda **kwargs: SimpleNamespace(id=f"cs_test_{uuid4().hex[:16]}", url="https://checkout.stripe.com/test")),
    )


# ── Checkout creation validation ──

async def test_topup_checkout_rejects_invalid_quantity(client, db_conn, auth_user_pool, make_headers, monkeypatch):
    _mock_stripe_checkout(monkeypatch)
    owner = auth_user_pool[0]
    await make_client(db_conn, owner, plan_id="starter")

    resp = await client.post("/billing/topup/checkout", json={"quantity": 1234}, headers=make_headers(owner))
    assert resp.status_code == 400


async def test_topup_checkout_rejects_quantity_over_plan_limit(client, db_conn, auth_user_pool, make_headers, monkeypatch):
    _mock_stripe_checkout(monkeypatch)
    owner = auth_user_pool[0]
    await make_client(db_conn, owner, plan_id="starter")  # 10,000/mo after the 0012 migration

    resp = await client.post("/billing/topup/checkout", json={"quantity": 25000}, headers=make_headers(owner))
    assert resp.status_code == 400


async def test_topup_checkout_accepts_quantity_exactly_at_plan_limit(client, db_conn, auth_user_pool, make_headers, monkeypatch):
    _mock_stripe_checkout(monkeypatch)
    owner = auth_user_pool[0]
    owner_id, org_id = await make_client(db_conn, owner, plan_id="starter")
    customer_id = f"cus_{uuid4().hex[:16]}"
    await db_conn.execute("UPDATE users SET stripe_customer_id = $2 WHERE id = $1", owner_id, customer_id)
    monkeypatch.setattr(stripe.Customer, "retrieve", staticmethod(lambda cid, **kw: SimpleNamespace(id=cid)))

    resp = await client.post("/billing/topup/checkout", json={"quantity": 10000}, headers=make_headers(owner))
    assert resp.status_code == 200, resp.text
    assert resp.json()["checkout_url"] == "https://checkout.stripe.com/test"

    row = await db_conn.fetchrow(
        "SELECT package_size, amount_paid, status, period_end FROM lead_topups WHERE organization_id = $1", org_id
    )
    assert row["package_size"] == 10000
    assert Decimal(row["amount_paid"]) == Decimal("250.00")
    assert row["status"] == "pending"

    sub_period_end = await db_conn.fetchval("SELECT current_period_end FROM subscriptions WHERE user_id = $1", owner_id)
    assert row["period_end"] == sub_period_end


async def test_topup_checkout_price_is_flat_quarter_cent_per_record(client, db_conn, auth_user_pool, make_headers, monkeypatch):
    _mock_stripe_checkout(monkeypatch)
    owner = auth_user_pool[0]
    owner_id, org_id = await make_client(db_conn, owner, plan_id="elite")  # 50,000/mo ("Pro") after 0012
    customer_id = f"cus_{uuid4().hex[:16]}"
    await db_conn.execute("UPDATE users SET stripe_customer_id = $2 WHERE id = $1", owner_id, customer_id)
    monkeypatch.setattr(stripe.Customer, "retrieve", staticmethod(lambda cid, **kw: SimpleNamespace(id=cid)))

    resp = await client.post("/billing/topup/checkout", json={"quantity": 2500}, headers=make_headers(owner))
    assert resp.status_code == 200, resp.text
    amount = await db_conn.fetchval("SELECT amount_paid FROM lead_topups WHERE organization_id = $1", org_id)
    assert Decimal(amount) == Decimal("62.50")


async def test_topup_checkout_rejects_enterprise_plan(client, db_conn, auth_user_pool, make_headers, monkeypatch):
    _mock_stripe_checkout(monkeypatch)
    owner = auth_user_pool[0]
    await make_client(db_conn, owner, plan_id="enterprise")

    resp = await client.post("/billing/topup/checkout", json={"quantity": 1000}, headers=make_headers(owner))
    assert resp.status_code == 400


async def test_topup_checkout_rejects_no_active_subscription(client, db_conn, auth_user_pool, make_headers):
    from tests.factories import make_org, make_user
    owner = auth_user_pool[0]
    user_id = await make_user(db_conn, owner["id"], owner["email"])
    await make_org(db_conn, user_id)  # org + account_owner membership, but no subscriptions row

    resp = await client.post("/billing/topup/checkout", json={"quantity": 1000}, headers=make_headers(owner))
    assert resp.status_code == 403


async def test_topup_checkout_rejects_non_owner(client, db_conn, auth_user_pool, make_headers):
    from tests.factories import make_user
    owner = auth_user_pool[0]
    owner_id, org_id = await make_client(db_conn, owner, plan_id="starter")

    member = auth_user_pool[1]
    await make_user(db_conn, member["id"], member["email"])
    await add_member(db_conn, org_id, member["id"], role="client_member")

    resp = await client.post("/billing/topup/checkout", json={"quantity": 1000}, headers=make_headers(member))
    assert resp.status_code == 403


# ── Webhook fulfillment ──

async def test_topup_webhook_marks_paid_and_notifies(client, db_conn, auth_user_pool, make_headers, monkeypatch):
    _mock_stripe_checkout(monkeypatch)
    owner = auth_user_pool[0]
    owner_id, org_id = await make_client(db_conn, owner, plan_id="starter")
    customer_id = f"cus_{uuid4().hex[:16]}"
    await db_conn.execute("UPDATE users SET stripe_customer_id = $2 WHERE id = $1", owner_id, customer_id)
    monkeypatch.setattr(stripe.Customer, "retrieve", staticmethod(lambda cid, **kw: SimpleNamespace(id=cid)))

    checkout_resp = await client.post("/billing/topup/checkout", json={"quantity": 1000}, headers=make_headers(owner))
    assert checkout_resp.status_code == 200
    session_id = await db_conn.fetchval("SELECT stripe_checkout_session_id FROM lead_topups WHERE organization_id = $1", org_id)

    resp = await _post_webhook(client, _topup_checkout_completed_event(f"evt_{uuid4().hex[:16]}", session_id=session_id))
    assert resp.status_code == 200, resp.text

    row = await db_conn.fetchrow("SELECT status, stripe_payment_intent_id FROM lead_topups WHERE stripe_checkout_session_id = $1", session_id)
    assert row["status"] == "paid"
    assert row["stripe_payment_intent_id"] is not None

    notif = await db_conn.fetchval(
        "SELECT type FROM notifications WHERE user_id = $1 AND type = 'topup_purchased'", owner_id
    )
    assert notif == "topup_purchased"


async def test_topup_webhook_redelivery_is_noop(client, db_conn, auth_user_pool, make_headers, monkeypatch):
    _mock_stripe_checkout(monkeypatch)
    owner = auth_user_pool[0]
    owner_id, org_id = await make_client(db_conn, owner, plan_id="starter")
    customer_id = f"cus_{uuid4().hex[:16]}"
    await db_conn.execute("UPDATE users SET stripe_customer_id = $2 WHERE id = $1", owner_id, customer_id)
    monkeypatch.setattr(stripe.Customer, "retrieve", staticmethod(lambda cid, **kw: SimpleNamespace(id=cid)))

    await client.post("/billing/topup/checkout", json={"quantity": 1000}, headers=make_headers(owner))
    session_id = await db_conn.fetchval("SELECT stripe_checkout_session_id FROM lead_topups WHERE organization_id = $1", org_id)

    event = _topup_checkout_completed_event(f"evt_{uuid4().hex[:16]}", session_id=session_id)
    resp1 = await _post_webhook(client, event)
    assert resp1.status_code == 200
    resp2 = await _post_webhook(client, event)  # exact same event id — idempotency ledger
    assert resp2.status_code == 200

    notif_count = await db_conn.fetchval(
        "SELECT COUNT(*) FROM notifications WHERE user_id = $1 AND type = 'topup_purchased'", owner_id
    )
    assert notif_count == 1


async def test_topup_webhook_unknown_session_is_noop_not_error(client):
    resp = await _post_webhook(client, _topup_checkout_completed_event(f"evt_{uuid4().hex[:16]}", session_id=f"cs_unknown_{uuid4().hex[:16]}"))
    assert resp.status_code == 200


async def test_subscription_mode_checkout_completed_still_routes_through_existing_logic(client, db_conn, auth_user_pool):
    """Regression guard: a subscription-mode checkout.session.completed (no
    metadata.kind) must not be swallowed by the new lead_topup branch."""
    owner = auth_user_pool[0]
    owner_id, _org_id = await make_client(db_conn, owner, plan_id="starter")

    event = {
        "id": f"evt_{uuid4().hex[:16]}",
        "type": "checkout.session.completed",
        "data": {"object": {
            "id": f"cs_{uuid4().hex[:16]}",
            "subscription": None,  # no subscription id -> existing handler just warns+returns
            "metadata": {},
        }},
    }
    resp = await _post_webhook(client, event)
    assert resp.status_code == 200  # existing "no subscription" warning path, not an error


# ── get_effective_monthly_limit ──

async def test_effective_limit_with_no_topups_returns_plan_limit(db_conn, auth_user_pool):
    owner = auth_user_pool[0]
    owner_id, org_id = await make_client(db_conn, owner, plan_id="starter")
    period_end = await db_conn.fetchval("SELECT current_period_end FROM subscriptions WHERE user_id = $1", owner_id)

    limit = await get_effective_monthly_limit(db_conn, org_id, 10000, period_end)
    assert limit == 10000


async def test_effective_limit_counts_active_paid_topup(db_conn, auth_user_pool):
    owner = auth_user_pool[0]
    owner_id, org_id = await make_client(db_conn, owner, plan_id="starter")
    period_end = await db_conn.fetchval("SELECT current_period_end FROM subscriptions WHERE user_id = $1", owner_id)
    await make_lead_topup(db_conn, org_id, owner_id, package_size=5000, status="paid", period_end=period_end)

    limit = await get_effective_monthly_limit(db_conn, org_id, 10000, period_end)
    assert limit == 15000


async def test_effective_limit_excludes_pending_and_failed_topups(db_conn, auth_user_pool):
    owner = auth_user_pool[0]
    owner_id, org_id = await make_client(db_conn, owner, plan_id="starter")
    period_end = await db_conn.fetchval("SELECT current_period_end FROM subscriptions WHERE user_id = $1", owner_id)
    await make_lead_topup(db_conn, org_id, owner_id, package_size=5000, status="pending", period_end=period_end)
    await make_lead_topup(db_conn, org_id, owner_id, package_size=5000, status="failed", period_end=period_end)

    limit = await get_effective_monthly_limit(db_conn, org_id, 10000, period_end)
    assert limit == 10000


async def test_effective_limit_excludes_topup_from_a_prior_period(db_conn, auth_user_pool):
    """The core 'must not carry forward forever' guarantee: a topup stamped with
    an earlier period_end (as if bought before a renewal already rolled the
    subscription to a new period) must not count against the current period."""
    from datetime import timedelta
    owner = auth_user_pool[0]
    owner_id, org_id = await make_client(db_conn, owner, plan_id="starter")
    current_period_end = await db_conn.fetchval("SELECT current_period_end FROM subscriptions WHERE user_id = $1", owner_id)
    prior_period_end = current_period_end - timedelta(days=30)
    await make_lead_topup(db_conn, org_id, owner_id, package_size=5000, status="paid", period_end=prior_period_end)

    limit = await get_effective_monthly_limit(db_conn, org_id, 10000, current_period_end)
    assert limit == 10000  # the prior-period topup does not carry forward


# ── People Leads integration ──

async def test_people_leads_request_429s_without_topup_succeeds_with_one(client, db_conn, auth_user_pool, make_headers):
    owner = auth_user_pool[0]
    owner_id, org_id = await make_client(db_conn, owner, plan_id="starter")  # 10,000/mo
    period_end = await db_conn.fetchval("SELECT current_period_end FROM subscriptions WHERE user_id = $1", owner_id)

    # Without a topup, a request for 10,001 exceeds the 10,000/mo base limit.
    resp = await client.post(
        "/people-leads/requests",
        json={"request_name": "Big ask", "lead_type": "property_owners", "state": "FL", "requested_quantity": 10001},
        headers=make_headers(owner),
    )
    assert resp.status_code == 429

    await make_lead_topup(db_conn, org_id, owner_id, package_size=5000, status="paid", period_end=period_end)

    resp2 = await client.post(
        "/people-leads/requests",
        json={"request_name": "Big ask", "lead_type": "property_owners", "state": "FL", "requested_quantity": 10001},
        headers=make_headers(owner),
    )
    assert resp2.status_code == 201, resp2.text


# ── Business Leads integration ──

async def test_business_leads_job_429s_without_topup_succeeds_with_one(client, db_conn, auth_user_pool, make_headers):
    owner = auth_user_pool[0]
    owner_id, org_id = await make_client(db_conn, owner, plan_id="elite")  # 50,000/mo ("Pro"), 1,667/day after 0012
    period_end = await db_conn.fetchval("SELECT current_period_end FROM subscriptions WHERE user_id = $1", owner_id)

    # Pre-existing usage this period, close to the monthly ceiling but each
    # individual job estimate (60/city) stays under the daily cap on its own.
    await make_job(db_conn, owner_id, status="done", total_clean=49500)

    cities = [f"City{i}" for i in range(20)]  # 20*60=1,200 estimated leads: fits under the 1,667/day cap alone
    resp = await client.post("/jobs", json={"industry": "plumbers", "state": "FL", "cities": cities}, headers=make_headers(owner))
    assert resp.status_code == 429
    assert "monthly" in resp.json()["detail"].lower()

    await make_lead_topup(db_conn, org_id, owner_id, package_size=5000, status="paid", period_end=period_end)

    resp2 = await client.post("/jobs", json={"industry": "plumbers", "state": "FL", "cities": cities}, headers=make_headers(owner))
    assert resp2.status_code == 201, resp2.text


async def test_business_leads_daily_cap_still_blocks_independently_of_monthly_topup(client, db_conn, auth_user_pool, make_headers):
    """Regression guard: the new monthly check must not loosen the pre-existing
    daily cap. A request that fits comfortably under the (topped-up) monthly
    ceiling but exceeds the daily one must still 429 — on the daily-cap message,
    not the monthly one."""
    owner = auth_user_pool[0]
    owner_id, org_id = await make_client(db_conn, owner, plan_id="starter")  # 333/day, 10,000/mo after 0012
    period_end = await db_conn.fetchval("SELECT current_period_end FROM subscriptions WHERE user_id = $1", owner_id)
    await make_lead_topup(db_conn, org_id, owner_id, package_size=50000, status="paid", period_end=period_end)  # huge monthly headroom

    cities = [f"City{i}" for i in range(10)]  # 10*60=600 estimated leads > 333/day cap
    resp = await client.post("/jobs", json={"industry": "plumbers", "state": "FL", "cities": cities}, headers=make_headers(owner))
    assert resp.status_code == 429
    assert "daily" in resp.json()["detail"].lower()


# ── Dashboard ──

async def test_dashboard_reports_effective_monthly_limit(client, db_conn, auth_user_pool, make_headers):
    owner = auth_user_pool[0]
    owner_id, org_id = await make_client(db_conn, owner, plan_id="starter")
    period_end = await db_conn.fetchval("SELECT current_period_end FROM subscriptions WHERE user_id = $1", owner_id)
    await make_lead_topup(db_conn, org_id, owner_id, package_size=2500, status="paid", period_end=period_end)

    resp = await client.get("/dashboard/client", headers=make_headers(owner))
    assert resp.status_code == 200
    body = resp.json()
    assert body["monthly_limit"] == 10000
    assert body["effective_monthly_limit"] == 12500
