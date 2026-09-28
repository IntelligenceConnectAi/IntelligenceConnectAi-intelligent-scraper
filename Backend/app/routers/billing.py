import json
import logging
import time
import urllib.parse
from decimal import Decimal
from typing import Annotated, Optional

import httpx
import stripe
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from app.audit import log_audit
from app.config import settings
from app.deps import CurrentUserDep, DBConn, get_current_org_id
from app.leads_usage import compute_period_window
from app.notifications import create_notification, notify_admins_with_permission
from app.org_access import RequireOrgRole
from app.schemas import InvoiceResponse, PaymentMethodResponse
from app.stripe_helpers import list_stripe_invoices
from app.user_status import suspend_org

log = logging.getLogger(__name__)
router = APIRouter()

stripe.api_key = settings.stripe_secret_key

PRICE_TO_PLAN: dict[str, str] = settings.stripe_price_to_plan

# Additional-records top-ups: flat $0.025/record, sold in fixed package sizes.
# A plan may only buy a package up to 100% of its own leads_per_month (enforced
# in create_topup_checkout, not hardcoded per package here).
ALLOWED_TOPUP_SIZES = {1000, 2500, 5000, 10000, 25000, 50000}
PRICE_PER_RECORD = Decimal("0.025")


def _sb_headers() -> dict:
    return {
        "apikey": settings.supabase_service_role_key,
        "Authorization": f"Bearer {settings.supabase_service_role_key}",
        "Content-Type": "application/json",
    }


class CheckoutRequest(BaseModel):
    price_id: str
    success_url: Optional[str] = None
    cancel_url: Optional[str] = None
    customer_email: str = ""


def _build_checkout_urls(body: "CheckoutRequest", user_email: str) -> tuple[str, str]:
    success_url = body.success_url or f"{settings.frontend_base_url}/signup?checkout=success"
    cancel_url = body.cancel_url or f"{settings.frontend_base_url}?checkout=canceled"
    if user_email:
        success_url = f"{settings.frontend_base_url}/signup?email={urllib.parse.quote(user_email)}&checkout=success"
    return success_url, cancel_url


async def _get_or_create_stripe_customer(db, user) -> str:
    """Shared by create_checkout and create_topup_checkout. Verifies an existing
    stripe_customer_id still resolves in Stripe (a test-mode reset or manual
    deletion on Stripe's side would otherwise leave a dangling id), creating a
    fresh customer if needed."""
    row = await db.fetchrow(
        "SELECT stripe_customer_id FROM users WHERE id = $1", user.id
    )
    customer_id = row["stripe_customer_id"] if row else None

    if customer_id:
        try:
            stripe.Customer.retrieve(customer_id)
        except stripe.error.InvalidRequestError:
            log.warning(f"Stripe customer {customer_id} not found — creating new one")
            customer_id = None
            await db.execute(
                "UPDATE users SET stripe_customer_id = NULL WHERE id = $1", user.id
            )

    if not customer_id:
        customer = stripe.Customer.create(
            email=user.email,
            metadata={"supabase_user_id": str(user.id)},
        )
        customer_id = customer.id
        await db.execute(
            "UPDATE users SET stripe_customer_id = $2 WHERE id = $1",
            user.id, customer_id,
        )
    return customer_id


@router.post("/checkout")
async def create_checkout(
    body: CheckoutRequest, user: CurrentUserDep, db: DBConn,
    _membership: Annotated[dict, Depends(RequireOrgRole("account_owner"))],
):
    if body.price_id not in PRICE_TO_PLAN:
        raise HTTPException(status_code=400, detail="Invalid price ID")

    customer_id = await _get_or_create_stripe_customer(db, user)

    success_url, cancel_url = _build_checkout_urls(body, user.email)

    session = stripe.checkout.Session.create(
        customer=customer_id,
        payment_method_types=["card"],
        line_items=[{"price": body.price_id, "quantity": 1}],
        mode="subscription",
        success_url=success_url,
        cancel_url=cancel_url,
        metadata={"supabase_user_id": str(user.id)},
    )
    return {"checkout_url": session.url}


class TopupCheckoutRequest(BaseModel):
    quantity: int
    success_url: Optional[str] = None
    cancel_url: Optional[str] = None


@router.post("/topup/checkout")
async def create_topup_checkout(
    body: TopupCheckoutRequest, user: CurrentUserDep, db: DBConn,
    _membership: Annotated[dict, Depends(RequireOrgRole("account_owner"))],
):
    """One-time (mode='payment') Stripe Checkout for additional-records top-ups —
    distinct from create_checkout's mode='subscription' flow above. Gated to the
    account owner because the charge lands on users.stripe_customer_id, which is
    only ever set on the owner (see _org_id_for_stripe_customer's docstring)."""
    plan_row = await db.fetchrow(
        """
        SELECT p.id AS plan_id, p.leads_per_month, s.current_period_end
        FROM subscriptions s JOIN plans p ON p.id = s.plan_id
        WHERE s.user_id = $1 AND s.status = 'active'
        """,
        user.id,
    )
    if not plan_row:
        raise HTTPException(status_code=403, detail="No active subscription. Please subscribe to a plan.")
    if not plan_row["current_period_end"]:
        raise HTTPException(status_code=400, detail="Your subscription is missing billing period information. Please contact support.")
    if plan_row["plan_id"] == "enterprise":
        raise HTTPException(status_code=400, detail="Enterprise plans are custom — contact sales for additional capacity.")
    if body.quantity not in ALLOWED_TOPUP_SIZES:
        raise HTTPException(status_code=400, detail=f"Quantity must be one of: {sorted(ALLOWED_TOPUP_SIZES)}")
    # Compared against the plan's static limit, never an already-boosted effective
    # limit — otherwise topups could chain to unlock ever-larger topups.
    if body.quantity > (plan_row["leads_per_month"] or 0):
        raise HTTPException(
            status_code=400,
            detail=f"Your plan allows topups up to {plan_row['leads_per_month']:,} records at a time.",
        )

    org_id = await get_current_org_id(db, user.id)
    customer_id = await _get_or_create_stripe_customer(db, user)
    period_start, period_end = compute_period_window(plan_row["current_period_end"])
    amount = body.quantity * PRICE_PER_RECORD

    success_url = body.success_url or f"{settings.frontend_base_url}/?topup=success"
    cancel_url = body.cancel_url or f"{settings.frontend_base_url}/?topup=canceled"

    session = stripe.checkout.Session.create(
        customer=customer_id,
        payment_method_types=["card"],
        line_items=[{
            "price_data": {
                "currency": "usd",
                "product_data": {"name": f"+{body.quantity:,} additional records"},
                "unit_amount": int(amount * 100),
            },
            "quantity": 1,
        }],
        mode="payment",
        # mode="payment" produces no Stripe Invoice by default (invoices are a
        # subscription/invoice-item construct) — without this, a real charge would
        # never show up in GET /billing/invoices despite the customer paying for it.
        invoice_creation={"enabled": True},
        success_url=success_url,
        cancel_url=cancel_url,
        metadata={
            "kind": "lead_topup",
            "supabase_user_id": str(user.id),
            "organization_id": str(org_id),
            "package_size": str(body.quantity),
        },
    )

    await db.execute(
        """
        INSERT INTO lead_topups
            (organization_id, purchased_by_user_id, plan_id, package_size, amount_paid,
             stripe_checkout_session_id, status, period_start, period_end)
        VALUES ($1, $2, $3, $4, $5, $6, 'pending', $7, $8)
        """,
        org_id, user.id, plan_row["plan_id"], body.quantity, amount,
        session.id, period_start, period_end,
    )

    return {"checkout_url": session.url}


@router.get("/portal")
async def customer_portal(
    user: CurrentUserDep, db: DBConn,
    _membership: Annotated[dict, Depends(RequireOrgRole("account_owner"))],
):
    row = await db.fetchrow(
        "SELECT stripe_customer_id FROM users WHERE id = $1", user.id
    )
    customer_id = row["stripe_customer_id"] if row else None
    if not customer_id:
        raise HTTPException(status_code=404, detail="No billing account found.")

    session = stripe.billing_portal.Session.create(
        customer=customer_id,
        return_url=settings.frontend_base_url,
    )
    return {"portal_url": session.url}


@router.get("/invoices", response_model=list[InvoiceResponse])
async def list_invoices(user: CurrentUserDep, db: DBConn):
    """Read-only, any active org member may view (self-scoped by the caller's own
    stripe_customer_id — a non-owner has none yet, see the Phase 6 plan's stated
    Billing-visibility limitation, so this simply returns an empty list for them)."""
    row = await db.fetchrow("SELECT stripe_customer_id FROM users WHERE id = $1", user.id)
    customer_id = row["stripe_customer_id"] if row else None
    if not customer_id:
        return []
    return await list_stripe_invoices(customer_id)


@router.get("/payment-method", response_model=PaymentMethodResponse)
async def get_payment_method(user: CurrentUserDep, db: DBConn):
    """A standard subscription Checkout attaches the card to the customer but
    does NOT set customer.invoice_settings.default_payment_method — confirmed
    via real test-mode testing, where a card was genuinely attached
    (visible via PaymentMethod.list) yet the customer-level default stayed
    null. The subscription's own default_payment_method is checked first
    (what Stripe actually bills against), then the customer-level default,
    then the most recently attached card as a last resort — covers every
    real case seen so far rather than just the one Stripe happens to
    auto-populate."""
    row = await db.fetchrow(
        """
        SELECT u.stripe_customer_id, s.stripe_subscription_id
        FROM users u
        LEFT JOIN subscriptions s ON s.user_id = u.id
        WHERE u.id = $1
        """,
        user.id,
    )
    customer_id = row["stripe_customer_id"] if row else None
    subscription_id = row["stripe_subscription_id"] if row else None
    if not customer_id:
        return PaymentMethodResponse(has_payment_method=False)

    card = None
    try:
        if subscription_id:
            sub = stripe.Subscription.retrieve(subscription_id, expand=["default_payment_method"])
            pm = sub.get("default_payment_method")
            if isinstance(pm, dict) and "card" in pm:
                card = pm["card"]

        if not card:
            customer = stripe.Customer.retrieve(customer_id, expand=["invoice_settings.default_payment_method"])
            pm = (customer.get("invoice_settings") or {}).get("default_payment_method")
            if isinstance(pm, dict) and "card" in pm:
                card = pm["card"]

        if not card:
            pms = stripe.PaymentMethod.list(customer=customer_id, type="card", limit=1)
            if pms["data"]:
                card = pms["data"][0]["card"]
    except stripe.error.StripeError as e:
        log.error(f"Stripe payment-method lookup failed for {customer_id}: {e}")
        return PaymentMethodResponse(has_payment_method=False)

    if not card:
        return PaymentMethodResponse(has_payment_method=False)
    return PaymentMethodResponse(
        has_payment_method=True,
        brand=card.get("brand"), last4=card.get("last4"),
        exp_month=card.get("exp_month"), exp_year=card.get("exp_year"),
    )


@router.post("/webhook")
async def stripe_webhook(request: Request, db: DBConn):
    payload    = await request.body()
    sig_header = request.headers.get("stripe-signature", "")

    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, settings.stripe_webhook_secret
        )
    except stripe.error.SignatureVerificationError:
        raise HTTPException(status_code=400, detail="Invalid webhook signature")

    event_id = event["id"]
    etype    = event["type"]
    data     = json.loads(str(event["data"]["object"]))
    log.info(f"Webhook: {etype} ({event_id})")

    # Idempotency ledger — Stripe delivers at-least-once, so a redelivered event id
    # must be a no-op even though most handlers below are already independently
    # idempotent (ON CONFLICT / WHERE stripe_subscription_id=...).
    already_processed = await db.fetchval(
        "SELECT status = 'processed' FROM stripe_events WHERE id = $1", event_id
    )
    if already_processed:
        log.info(f"Webhook {event_id} already processed — skipping redelivery")
        return {"received": True}

    await db.execute(
        """
        INSERT INTO stripe_events (id, type, payload, status)
        VALUES ($1, $2, $3::jsonb, 'processing')
        ON CONFLICT (id) DO UPDATE SET status = 'processing', error_message = NULL
        """,
        event_id, etype, json.dumps(json.loads(str(event))),
    )

    try:
        if etype == "checkout.session.completed":
            await _handle_checkout_completed(data, db)
        elif etype == "checkout.session.expired":
            await _handle_checkout_expired(data, db)
        elif etype == "customer.subscription.updated":
            await _handle_subscription_updated(data, db)
        elif etype == "customer.subscription.deleted":
            await _handle_subscription_deleted(data, db)
        elif etype == "invoice.payment_failed":
            await _handle_payment_failed(data, db)
        elif etype == "invoice.payment_succeeded":
            await _handle_payment_succeeded(data, db)
        elif etype == "charge.refunded":
            await _handle_charge_refunded(data, db)
        elif etype == "charge.dispute.created":
            await _handle_dispute_created(data, db)
    except Exception as e:
        log.error(f"Webhook error ({etype}): {e}", exc_info=True)
        await db.execute(
            "UPDATE stripe_events SET status = 'failed', error_message = $2 WHERE id = $1",
            event_id, str(e)[:2000],
        )
        raise HTTPException(status_code=500, detail=str(e))

    await db.execute(
        "UPDATE stripe_events SET status = 'processed', processed_at = NOW() WHERE id = $1", event_id
    )
    return {"received": True}


def _subscription_period_end(sub_data: dict) -> Optional[int]:
    """current_period_end moved off the top-level Subscription object onto
    subscription items in newer Stripe API versions — confirmed via real
    testing (the top-level field came back missing/stale in webhook
    payloads on this account's API version, even though a fresh
    Subscription.retrieve() still has it). Prefer the item-level value.
    billing_cycle_anchor is deliberately NOT used as a fallback — it's the
    period START, not end, so using it here was always semantically wrong,
    just previously masked by the top-level field usually being present."""
    items = (sub_data.get("items") or {}).get("data") or []
    if items and items[0].get("current_period_end"):
        return items[0]["current_period_end"]
    return sub_data.get("current_period_end")


async def _handle_topup_checkout_completed(s: dict, db) -> None:
    """Fulfillment for the mode='payment' lead_topup checkout created in
    create_topup_checkout. Marks the pending row paid without recomputing the
    period window here — the window was already stamped at checkout-creation
    time, which avoids misattributing the credit if a subscription renewal
    happens to fire in the gap between checkout creation and payment completion.
    The WHERE status='pending' guard makes this independently idempotent, on
    top of the outer stripe_events ledger."""
    row = await db.fetchrow(
        """
        UPDATE lead_topups SET status='paid', stripe_payment_intent_id=$2, updated_at=NOW()
        WHERE stripe_checkout_session_id=$1 AND status='pending'
        RETURNING organization_id, purchased_by_user_id, package_size
        """,
        s["id"], s.get("payment_intent"),
    )
    if not row:
        log.info(f"Topup checkout {s['id']} already processed or unknown — no-op")
        return
    try:
        await create_notification(
            db, user_id=row["purchased_by_user_id"], category="billing_limits", type="topup_purchased",
            title="Additional records purchased",
            body=f"+{row['package_size']:,} additional records were added to your account for this billing period.",
            link_section="settings", link_sub_tab="billing",
        )
    except Exception as e:
        log.error(f"Topup purchase notification error: {e}", exc_info=True)


async def _handle_checkout_expired(s: dict, db) -> None:
    """A customer who abandons the Stripe checkout page for a topup would
    otherwise leave a 'pending' lead_topups row forever — harmless (fulfillment
    only ever looks at status='paid'), but confusing to debug. No-op for
    subscription-mode sessions (metadata.kind won't be 'lead_topup')."""
    metadata = s.get("metadata") or {}
    if metadata.get("kind") != "lead_topup":
        return
    await db.execute(
        "UPDATE lead_topups SET status='failed', updated_at=NOW() WHERE stripe_checkout_session_id=$1 AND status='pending'",
        s["id"],
    )


async def _handle_checkout_completed(s: dict, db) -> None:
    metadata = s.get("metadata") or {}
    if metadata.get("kind") == "lead_topup":
        await _handle_topup_checkout_completed(s, db)
        return

    sub_id = s.get("subscription")
    if not sub_id:
        log.warning("No subscription in checkout.session.completed")
        return

    # Get customer email
    customer_email = None
    cd = s.get("customer_details")
    if isinstance(cd, dict):
        customer_email = cd.get("email")
    if not customer_email:
        customer_email = s.get("customer_email")
    if not customer_email:
        cid = s.get("customer")
        if cid:
            c = stripe.Customer.retrieve(cid)
            customer_email = json.loads(str(c)).get("email")

    if not customer_email:
        log.error("No email in checkout session")
        return

    # Get plan from subscription
    sub      = stripe.Subscription.retrieve(sub_id)
    sub_data = json.loads(str(sub))
    price_id = sub_data["items"]["data"][0]["price"]["id"]
    plan_id  = PRICE_TO_PLAN.get(price_id)

    if not plan_id:
        log.error(f"Unknown price_id: {price_id}")
        return

    stripe_customer_id = s.get("customer")
    period_end = _subscription_period_end(sub_data) or int(time.time()) + 30 * 86400
    cancel_at = sub_data.get("cancel_at_period_end", False)

    # Check if this is an existing logged-in user (upgrading plan)
    existing_user_id = metadata.get("supabase_user_id")

    if existing_user_id:
        # ── Existing user upgrading plan ──
        log.info(f"Upgrading plan for existing user {existing_user_id} → {plan_id}")

        # Update stripe_customer_id on user
        if stripe_customer_id:
            await db.execute(
                "UPDATE users SET stripe_customer_id = $2 WHERE id = $1",
                existing_user_id, stripe_customer_id,
            )

        # Upsert subscription
        await db.execute(
            """
            INSERT INTO subscriptions
                (user_id, plan_id, status, stripe_subscription_id,
                 current_period_end, cancel_at_period_end)
            VALUES ($1, $2, 'active', $3, to_timestamp($4), $5)
            ON CONFLICT (user_id) DO UPDATE SET
                plan_id                = EXCLUDED.plan_id,
                status                 = 'active',
                stripe_subscription_id = EXCLUDED.stripe_subscription_id,
                current_period_end     = EXCLUDED.current_period_end,
                cancel_at_period_end   = EXCLUDED.cancel_at_period_end,
                updated_at             = NOW()
            """,
            existing_user_id, plan_id, sub_id, period_end, cancel_at,
        )
        log.info(f"Plan upgraded to {plan_id} for user {existing_user_id}")

    else:
        # ── New user from landing page ── save to pending_signups
        log.info(f"New user payment for {customer_email} — plan: {plan_id}")
        await db.execute(
            """
            INSERT INTO pending_signups
                (email, stripe_customer_id, stripe_subscription_id, plan_id)
            VALUES ($1, $2, $3, $4)
            ON CONFLICT (email) DO UPDATE SET
                stripe_customer_id     = EXCLUDED.stripe_customer_id,
                stripe_subscription_id = EXCLUDED.stripe_subscription_id,
                plan_id                = EXCLUDED.plan_id,
                created_at             = NOW()
            """,
            customer_email, stripe_customer_id, sub_id, plan_id,
        )
        log.info(f"Pending signup saved for {customer_email} — plan: {plan_id}")


async def _handle_subscription_updated(s: dict, db) -> None:
    sub_id     = s["id"]
    price_id   = s["items"]["data"][0]["price"]["id"]
    plan_id    = PRICE_TO_PLAN.get(price_id)
    status     = s["status"]
    period_end = _subscription_period_end(s)
    cancel_at  = s.get("cancel_at_period_end", False)
    if not plan_id:
        return
    await db.execute(
        """
        UPDATE subscriptions SET
            plan_id=$2, status=$3,
            current_period_end=to_timestamp($4),
            cancel_at_period_end=$5, updated_at=NOW()
        WHERE stripe_subscription_id=$1
        """,
        sub_id, plan_id, status, period_end, cancel_at,
    )
    log.info(f"Subscription updated: {plan_id} status={status}")


async def _handle_subscription_deleted(s: dict, db) -> None:
    await db.execute(
        "UPDATE subscriptions SET status='canceled', updated_at=NOW() WHERE stripe_subscription_id=$1",
        s["id"],
    )
    log.info(f"Subscription canceled: {s['id']}")


async def _handle_payment_failed(s: dict, db) -> None:
    """Best-effort notification only — wrapped in its own try/except so a failure
    here can never turn an otherwise-successful webhook into a 500 (Stripe retries
    non-2xx responses, which would needlessly replay the whole event)."""
    try:
        customer_id = s.get("customer")
        if not customer_id:
            return
        user_row = await db.fetchrow("SELECT id FROM users WHERE stripe_customer_id = $1", customer_id)
        if not user_row:
            return
        await create_notification(
            db, user_id=user_row["id"], category="billing_limits", type="payment_failure",
            title="Payment failed",
            body="Your most recent payment could not be processed. Please update your payment method to avoid service interruption.",
            link_section="settings", link_sub_tab="billing",
        )
    except Exception as e:
        log.error(f"Payment-failure notification error: {e}", exc_info=True)


async def _handle_payment_succeeded(s: dict, db) -> None:
    """Only fires for renewal cycles (billing_reason == subscription_cycle), not
    the initial checkout payment — same isolation posture as _handle_payment_failed."""
    if s.get("billing_reason") != "subscription_cycle":
        return
    try:
        customer_id = s.get("customer")
        if not customer_id:
            return
        user_row = await db.fetchrow("SELECT id FROM users WHERE stripe_customer_id = $1", customer_id)
        if not user_row:
            return
        await create_notification(
            db, user_id=user_row["id"], category="billing_limits", type="subscription_renewal",
            title="Subscription renewed",
            body="Your subscription has renewed successfully.",
            link_section="settings", link_sub_tab="billing",
        )
    except Exception as e:
        log.error(f"Subscription-renewal notification error: {e}", exc_info=True)


async def _org_id_for_stripe_customer(db, stripe_customer_id: str):
    """Refunds/disputes are billing-owner-level: users.stripe_customer_id is only
    ever set on the account_owner (create_checkout / the checkout-completed upgrade
    branch above), never a teammate — so owner_user_id is the correct join, mirroring
    admin_clients.py's plan-change endpoint treating "the org's plan" as the owner's
    subscriptions row."""
    return await db.fetchval(
        "SELECT o.id FROM organizations o JOIN users u ON u.id = o.owner_user_id WHERE u.stripe_customer_id = $1",
        stripe_customer_id,
    )


async def _handle_charge_refunded(s: dict, db) -> None:
    """Policy: a FULL refund auto-suspends the org (almost always means the
    relationship is over — closes the revenue-leak window). A PARTIAL refund only
    notifies (goodwill/proration gestures shouldn't be punished with a suspension).

    Double-suspend guard: if this exact charge was already refunded through the
    admin panel (app/routers/admin_clients.py::refund_client_charge writes an
    admin_refund_issued audit row synchronously, before this webhook can plausibly
    arrive), skip re-deciding suspension so the admin's explicit also_suspend choice
    (including "no") stays the final word. Worst case if this check ever misses is a
    harmless duplicate suspend, never a missed one."""
    customer_id = s.get("customer")
    if not customer_id:
        return
    org_id = await _org_id_for_stripe_customer(db, customer_id)
    if not org_id:
        log.warning(f"charge.refunded for unknown Stripe customer {customer_id}")
        return

    charge_id = s.get("id")
    is_full   = s.get("refunded") is True
    amount    = Decimal(s.get("amount_refunded", 0)) / 100
    currency  = (s.get("currency") or "usd").upper()

    admin_handled = await db.fetchval(
        """
        SELECT 1 FROM audit_logs
        WHERE action = 'admin_refund_issued' AND resource_type = 'organizations'
          AND resource_id = $1 AND new_value_json->>'charge_id' = $2
        LIMIT 1
        """,
        str(org_id), charge_id,
    )
    if not admin_handled:
        await log_audit(
            db, actor_user_id=None, actor_role="system", action="charge_refunded",
            resource_type="organizations", resource_id=str(org_id),
            new={"charge_id": charge_id, "amount_refunded": str(amount), "currency": currency, "full_refund": is_full},
        )
        if is_full:
            await suspend_org(db, org_id, actor_user_id=None, actor_role="system")
            log.info(f"Org {org_id} auto-suspended: full refund on charge {charge_id}")

    owner_id = await db.fetchval("SELECT owner_user_id FROM organizations WHERE id = $1", org_id)
    if owner_id:
        try:
            await create_notification(
                db, user_id=owner_id, category="billing_limits", type="refund_processed",
                title="Refund processed" + (" — account suspended" if is_full else ""),
                body=(
                    f"A full refund of {amount} {currency} was issued and your account access has been "
                    "suspended. Contact support if this was unexpected."
                    if is_full else
                    f"A partial refund of {amount} {currency} was issued to your payment method."
                ),
                link_section="settings", link_sub_tab="billing",
            )
        except Exception as e:
            log.error(f"Refund notification error: {e}", exc_info=True)


async def _handle_dispute_created(s: dict, db) -> None:
    """A dispute/chargeback always suspends, regardless of amount — adversarial by
    construction (the customer went to their bank, not to us) and carries real
    platform risk independent of dollar amount."""
    charge_id = s.get("charge")
    if not charge_id:
        return
    try:
        charge = stripe.Charge.retrieve(charge_id)
    except stripe.error.StripeError as e:
        log.error(f"Could not retrieve charge {charge_id} for dispute {s.get('id')}: {e}")
        return

    customer_id = charge.get("customer")
    if not customer_id:
        return
    org_id = await _org_id_for_stripe_customer(db, customer_id)
    if not org_id:
        log.warning(f"charge.dispute.created for unknown Stripe customer {customer_id}")
        return

    amount   = Decimal(s.get("amount", 0)) / 100
    currency = (s.get("currency") or "usd").upper()

    await log_audit(
        db, actor_user_id=None, actor_role="system", action="dispute_created_auto_suspend",
        resource_type="organizations", resource_id=str(org_id),
        new={"dispute_id": s.get("id"), "charge_id": charge_id, "amount": str(amount), "currency": currency, "reason": s.get("reason")},
    )
    await suspend_org(db, org_id, actor_user_id=None, actor_role="system")
    log.warning(f"Org {org_id} auto-suspended: dispute {s.get('id')} on charge {charge_id}")

    org_row = await db.fetchrow("SELECT owner_user_id, name FROM organizations WHERE id = $1", org_id)
    owner_id = org_row["owner_user_id"] if org_row else None
    org_name = org_row["name"] if org_row else str(org_id)
    if owner_id:
        try:
            await create_notification(
                db, user_id=owner_id, category="billing_limits", type="payment_disputed",
                title="Payment disputed — account suspended",
                body=f"A chargeback/dispute was filed for {amount} {currency} and your account access has been suspended. Contact support to resolve.",
                link_section="settings", link_sub_tab="billing",
            )
        except Exception as e:
            log.error(f"Dispute notification error: {e}", exc_info=True)

    try:
        await notify_admins_with_permission(
            db, permission_key="billing_admin",
            category="billing_limits", type="payment_disputed",
            title="Payment disputed — account suspended",
            body=(
                f"{org_name}: a chargeback/dispute was filed for {amount} {currency} "
                f"(charge {charge_id}, reason: {s.get('reason') or 'unspecified'}) — account suspended."
            ),
            link_section="clients", link_resource_id=str(org_id),
        )
    except Exception as e:
        log.error(f"admin dispute notification failed for org {org_id}: {e}", exc_info=True)