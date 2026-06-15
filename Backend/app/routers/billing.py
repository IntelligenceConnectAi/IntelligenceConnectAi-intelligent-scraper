import json
import logging

import httpx
import stripe
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from app.config import settings
from app.deps import CurrentUserDep, DBConn

log = logging.getLogger(__name__)
router = APIRouter()

stripe.api_key = settings.stripe_secret_key

PRICE_TO_PLAN: dict[str, str] = {
    settings.stripe_starter_price_id: "starter",
    settings.stripe_pro_price_id:     "pro",
    settings.stripe_elite_price_id:   "elite",
}


def _sb_headers() -> dict:
    return {
        "apikey": settings.supabase_service_role_key,
        "Authorization": f"Bearer {settings.supabase_service_role_key}",
        "Content-Type": "application/json",
    }


class CheckoutRequest(BaseModel):
    price_id: str
    success_url: str = "http://localhost:5173/signup?checkout=success"
    cancel_url:  str = "http://localhost:5173?checkout=canceled"
    customer_email: str = ""


@router.post("/checkout")
async def create_checkout(body: CheckoutRequest, user: CurrentUserDep, db: DBConn):
    if body.price_id not in PRICE_TO_PLAN:
        raise HTTPException(status_code=400, detail="Invalid price ID")

    row = await db.fetchrow(
        "SELECT stripe_customer_id FROM users WHERE id = $1", user.id
    )
    customer_id = row["stripe_customer_id"] if row else None

    # Verify customer still exists in Stripe
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

    # Build success URL with email for auto-redirect
    import urllib.parse
    success_url = body.success_url
    if user.email:
        success_url = f"http://localhost:5173/signup?email={urllib.parse.quote(user.email)}&checkout=success"

    session = stripe.checkout.Session.create(
        customer=customer_id,
        payment_method_types=["card"],
        line_items=[{"price": body.price_id, "quantity": 1}],
        mode="subscription",
        success_url=success_url,
        cancel_url=body.cancel_url,
        metadata={"supabase_user_id": str(user.id)},
    )
    return {"checkout_url": session.url}


@router.get("/portal")
async def customer_portal(user: CurrentUserDep, db: DBConn):
    row = await db.fetchrow(
        "SELECT stripe_customer_id FROM users WHERE id = $1", user.id
    )
    customer_id = row["stripe_customer_id"] if row else None
    if not customer_id:
        raise HTTPException(status_code=404, detail="No billing account found.")

    session = stripe.billing_portal.Session.create(
        customer=customer_id,
        return_url="http://localhost:5173",
    )
    return {"portal_url": session.url}


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

    etype = event["type"]
    data  = json.loads(str(event["data"]["object"]))
    log.info(f"Webhook: {etype}")

    try:
        if etype == "checkout.session.completed":
            await _handle_checkout_completed(data, db)
        elif etype == "customer.subscription.updated":
            await _handle_subscription_updated(data, db)
        elif etype == "customer.subscription.deleted":
            await _handle_subscription_deleted(data, db)
    except Exception as e:
        log.error(f"Webhook error ({etype}): {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

    return {"received": True}


async def _handle_checkout_completed(s: dict, db) -> None:
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
    period_end = (
        sub_data.get("current_period_end")
        or sub_data.get("billing_cycle_anchor")
        or int(__import__("time").time()) + 30 * 86400
    )
    cancel_at = sub_data.get("cancel_at_period_end", False)

    # Check if this is an existing logged-in user (upgrading plan)
    metadata    = s.get("metadata") or {}
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
    period_end = s.get("current_period_end") or s.get("billing_cycle_anchor")
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