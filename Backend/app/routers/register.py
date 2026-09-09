"""
POST /auth/register
User completes signup after Stripe payment.
Verifies email is in pending_signups, creates Supabase account,
assigns plan, logs user in.

Handles the GHL-linked-Stripe-Checkout launch case where a purchase never
carries a supabase_user_id (that metadata is only set when checkout starts
*inside* the logged-in app — see app/routers/billing.py::create_checkout): a
returning/churned customer buying again from the marketing site must not hit a
duplicate-account error, and check-payment must resolve correctly even before
the checkout.session.completed webhook has landed (see
_verify_session_and_backfill_pending_signup).
"""

import logging
from datetime import datetime, timezone
from typing import Optional

import httpx
import stripe
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.config import settings
from app.deps import DBConn
from app.invitations import hash_token
from app.notifications import create_notification
from app.schemas import AcceptInvitationRequest, InvitationPreviewResponse, User

log = logging.getLogger(__name__)
router = APIRouter()

stripe.api_key = settings.stripe_secret_key


class RegisterRequest(BaseModel):
    email: str
    password: str
    full_name: str


class RegisterResponse(BaseModel):
    user: User
    access_token: str
    refresh_token: str


class CheckPaymentResponse(BaseModel):
    paid: bool
    plan_id: Optional[str] = None
    existing_account: bool = False
    email: Optional[str] = None


def _sb_headers() -> dict:
    return {
        "apikey": settings.supabase_service_role_key,
        "Authorization": f"Bearer {settings.supabase_service_role_key}",
        "Content-Type": "application/json",
    }


async def _attach_pending_plan_to_existing_user(db, user_id, pending) -> None:
    """Mirrors billing.py's _handle_checkout_completed existing-user upgrade
    branch — used by check_payment's early-detection path and register's
    defensive belt-and-suspenders path so the two can't drift apart."""
    async with db.transaction():
        if pending["stripe_customer_id"]:
            await db.execute(
                "UPDATE users SET stripe_customer_id = $2 WHERE id = $1",
                user_id, pending["stripe_customer_id"],
            )
        await db.execute(
            """
            INSERT INTO subscriptions
                (user_id, plan_id, status, stripe_subscription_id,
                 stripe_customer_id, current_period_end, cancel_at_period_end)
            VALUES ($1, $2, 'active', $3, $4, NOW() + INTERVAL '30 days', false)
            ON CONFLICT (user_id) DO UPDATE SET
                plan_id                = EXCLUDED.plan_id,
                status                 = 'active',
                stripe_subscription_id = EXCLUDED.stripe_subscription_id,
                stripe_customer_id     = EXCLUDED.stripe_customer_id,
                updated_at             = NOW()
            """,
            user_id, pending["plan_id"], pending["stripe_subscription_id"], pending["stripe_customer_id"],
        )
        await db.execute("DELETE FROM pending_signups WHERE lower(email) = $1", pending["email"])


def _looks_like_duplicate_email_error(data: dict) -> bool:
    code = (data.get("code") or "").lower()
    msg = (data.get("msg") or data.get("message") or "").lower()
    return code in ("email_exists", "user_already_exists") or ("already" in msg and "regist" in msg)


async def _verify_session_and_backfill_pending_signup(db, session_id: str, email_hint: Optional[str]):
    """Fast path for the redirect-can-race-the-webhook problem: verifies directly
    against Stripe (no propagation delay, unlike waiting on our own webhook) and,
    if genuinely paid, writes the same pending_signups row the webhook would have
    (ON CONFLICT upsert — forwards-compatible with the webhook landing later, not
    a parallel code path)."""
    try:
        session = stripe.checkout.Session.retrieve(session_id, expand=["subscription"])
    except stripe.error.StripeError as e:
        log.warning(f"check-payment session_id verify failed for {session_id}: {e}")
        return None, email_hint

    if session.get("payment_status") != "paid":
        return None, email_hint

    customer_details = session.get("customer_details") or {}
    session_email = (customer_details.get("email") or session.get("customer_email") or "").strip().lower()
    if email_hint and session_email and session_email != email_hint:
        log.warning(f"check-payment session_id {session_id} email mismatch")
        return None, email_hint

    resolved_email = session_email or email_hint
    sub = session.get("subscription")
    if not resolved_email or not isinstance(sub, dict):
        return None, resolved_email

    plan_id = settings.stripe_price_to_plan.get(sub["items"]["data"][0]["price"]["id"])
    if not plan_id:
        return None, resolved_email

    await db.execute(
        """
        INSERT INTO pending_signups (email, stripe_customer_id, stripe_subscription_id, plan_id)
        VALUES ($1, $2, $3, $4)
        ON CONFLICT (email) DO UPDATE SET
            stripe_customer_id     = EXCLUDED.stripe_customer_id,
            stripe_subscription_id = EXCLUDED.stripe_subscription_id,
            plan_id                = EXCLUDED.plan_id,
            created_at             = NOW()
        """,
        resolved_email, session.get("customer"), sub["id"], plan_id,
    )
    pending = await db.fetchrow("SELECT * FROM pending_signups WHERE lower(email) = $1", resolved_email)
    return pending, resolved_email


@router.post("/register", response_model=RegisterResponse)
async def register(body: RegisterRequest, db: DBConn) -> RegisterResponse:
    email    = body.email.strip().lower()
    password = body.password.strip()
    name     = body.full_name.strip()

    if len(password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters")

    # ── 1. Check pending_signups ──
    pending = await db.fetchrow(
        "SELECT * FROM pending_signups WHERE lower(email) = $1", email
    )
    if not pending:
        raise HTTPException(
            status_code=403,
            detail="No payment found for this email. Please purchase a plan first."
        )

    plan_id               = pending["plan_id"]
    stripe_customer_id    = pending["stripe_customer_id"]
    stripe_subscription_id = pending["stripe_subscription_id"]

    # ── 1b. Returning/churned customer — a GHL-originated Stripe Checkout purchase
    # never carries the supabase_user_id metadata that would let the webhook detect
    # "existing user upgrading" (see billing.py::create_checkout). If this email
    # already has an account, attach the new plan to it directly instead of
    # attempting a duplicate Supabase account creation, which Supabase would reject. ──
    existing = await db.fetchrow("SELECT id FROM users WHERE lower(email) = $1", email)
    if existing:
        await _attach_pending_plan_to_existing_user(db, existing["id"], pending)
        raise HTTPException(
            status_code=409,
            detail="An account with this email already exists. Your new plan is now active — please log in.",
        )

    headers = _sb_headers()

    # ── 2. Create Supabase Auth user ──
    async with httpx.AsyncClient(timeout=20) as client:
        res = await client.post(
            f"{settings.supabase_url}/auth/v1/admin/users",
            headers=headers,
            json={
                "email": email,
                "password": password,
                "email_confirm": True,
                "user_metadata": {"full_name": name},
            },
        )
        data = res.json()

    if res.status_code not in (200, 201):
        # Belt-and-suspenders: the local check above missed (drift between
        # public.users and auth.users), but Supabase itself still knows this
        # email is taken. Repair rather than surface a raw Supabase error to a
        # customer who already paid.
        if _looks_like_duplicate_email_error(data):
            log.warning(f"Supabase reports duplicate email for {email} despite no local users row — repairing")
            auth_row = await db.fetchrow("SELECT id FROM auth.users WHERE lower(email) = $1", email)
            if auth_row:
                await db.execute(
                    """
                    INSERT INTO users (id, email, full_name, is_admin, is_active)
                    VALUES ($1, $2, $3, false, true)
                    ON CONFLICT (id) DO NOTHING
                    """,
                    auth_row["id"], email, name,
                )
                await _attach_pending_plan_to_existing_user(db, auth_row["id"], pending)
                raise HTTPException(
                    status_code=409,
                    detail="An account with this email already exists. Your new plan is now active — please log in.",
                )
            log.error(f"Duplicate-email error for {email} but no matching auth.users row — needs manual reconciliation")
        log.error(f"Supabase user creation failed for {email}: {data}")
        raise HTTPException(status_code=400, detail="We couldn't create your account. Please try again or contact support.")

    user_id = data["id"]
    log.info(f"Supabase user created: {user_id} for {email}")

    # ── 3-5. Users + subscription + default org + pending_signups cleanup, atomically ──
    async with db.transaction():
        # 3. Insert into users table — stripe_customer_id must be written here too
        # (not just onto subscriptions below), or /billing/portal, /billing/invoices,
        # and /billing/payment-method (all keyed off users.stripe_customer_id) come
        # up empty for a brand-new signup despite a fully valid paid subscription.
        # Mirrors _attach_pending_plan_to_existing_user's existing-user path, which
        # already does this correctly.
        await db.execute(
            """
            INSERT INTO users (id, email, full_name, is_admin, is_active, stripe_customer_id)
            VALUES ($1, $2, $3, false, true, $4)
            ON CONFLICT (id) DO UPDATE SET
                full_name          = EXCLUDED.full_name,
                stripe_customer_id = EXCLUDED.stripe_customer_id,
                updated_at         = NOW()
            """,
            user_id, email, name, stripe_customer_id,
        )

        # 4. Assign subscription
        await db.execute(
            """
            INSERT INTO subscriptions
                (user_id, plan_id, status, stripe_subscription_id,
                 stripe_customer_id, current_period_end, cancel_at_period_end)
            VALUES ($1, $2, 'active', $3, $4, NOW() + INTERVAL '30 days', false)
            ON CONFLICT (user_id) DO UPDATE SET
                plan_id                = EXCLUDED.plan_id,
                status                 = 'active',
                stripe_subscription_id = EXCLUDED.stripe_subscription_id,
                stripe_customer_id     = EXCLUDED.stripe_customer_id,
                updated_at             = NOW()
            """,
            user_id, plan_id, stripe_subscription_id, stripe_customer_id,
        )
        log.info(f"Subscription assigned: {plan_id} for {email}")

        # 4b. Default organization (account_owner) — every user owns exactly one org,
        # matching the backfill applied to pre-existing users in the Phase 1 migration.
        org_name = f"{name or email.split('@')[0]}'s Organization"
        await db.execute(
            """
            INSERT INTO organizations (name, owner_user_id)
            VALUES ($1, $2)
            ON CONFLICT (owner_user_id) DO NOTHING
            """,
            org_name, user_id,
        )
        org_id = await db.fetchval(
            "SELECT id FROM organizations WHERE owner_user_id = $1", user_id
        )
        await db.execute(
            """
            INSERT INTO organization_members (organization_id, user_id, role, is_active)
            VALUES ($1, $2, 'account_owner', true)
            ON CONFLICT (organization_id, user_id) DO NOTHING
            """,
            org_id, user_id,
        )

        # 5. Remove from pending_signups
        await db.execute(
            "DELETE FROM pending_signups WHERE lower(email) = $1", email
        )

    # ── 6. Sign in to get tokens ──
    async with httpx.AsyncClient(timeout=20) as client:
        res2 = await client.post(
            f"{settings.supabase_url}/auth/v1/token?grant_type=password",
            headers={
                "apikey": settings.supabase_anon_key,
                "Content-Type": "application/json",
            },
            json={"email": email, "password": password},
        )
        tokens = res2.json()

    if res2.status_code != 200:
        log.error(f"Auto-login failed: {tokens}")
        raise HTTPException(
            status_code=200,
            detail="Account created! Please log in manually."
        )

    access_token  = tokens["access_token"]
    refresh_token = tokens["refresh_token"]

    user = User(
        id=user_id,
        email=email,
        full_name=name,
        is_admin=False,
        is_active=True,
        created_at=datetime.now(timezone.utc),
    )

    log.info(f"Registration complete for {email} — plan: {plan_id}")
    return RegisterResponse(
        user=user,
        access_token=access_token,
        refresh_token=refresh_token,
    )


@router.get("/check-payment", response_model=CheckPaymentResponse)
async def check_payment(
    db: DBConn, email: Optional[str] = None, session_id: Optional[str] = None,
) -> CheckPaymentResponse:
    """Check if email has a pending payment (for frontend validation). Accepts an
    optional Stripe Checkout session_id — the fast path for the redirect racing
    the checkout.session.completed webhook (see
    _verify_session_and_backfill_pending_signup) — used only when the plain
    email-keyed pending_signups lookup comes up empty, so it costs nothing once
    the webhook has already landed."""
    resolved_email = email.strip().lower() if email else None

    pending = None
    if resolved_email:
        pending = await db.fetchrow("SELECT * FROM pending_signups WHERE lower(email) = $1", resolved_email)

    if pending is None and session_id:
        pending, resolved_email = await _verify_session_and_backfill_pending_signup(db, session_id, resolved_email)

    if not resolved_email:
        return CheckPaymentResponse(paid=False)

    existing = await db.fetchrow("SELECT id FROM users WHERE lower(email) = $1", resolved_email)

    if existing and pending:
        await _attach_pending_plan_to_existing_user(db, existing["id"], pending)
        return CheckPaymentResponse(paid=True, plan_id=pending["plan_id"], existing_account=True, email=resolved_email)
    if existing:
        return CheckPaymentResponse(paid=False, existing_account=True, email=resolved_email)
    if not pending:
        return CheckPaymentResponse(paid=False, email=resolved_email)
    return CheckPaymentResponse(paid=True, plan_id=pending["plan_id"], email=resolved_email)


# ── Phase 6 — Team invitation preview/accept (public, no email service exists
# anywhere in this codebase — invitations are always a manually-shared link) ──

@router.get("/invitations/{token}", response_model=InvitationPreviewResponse)
async def preview_invitation(token: str, db: DBConn) -> InvitationPreviewResponse:
    token_hash = hash_token(token)
    row = await db.fetchrow(
        """
        SELECT i.*, o.name AS organization_name
        FROM organization_invitations i
        JOIN organizations o ON o.id = i.organization_id
        WHERE i.token_hash = $1
        """,
        token_hash,
    )
    if not row:
        return InvitationPreviewResponse(valid=False, reason="Invitation not found")
    if row["status"] != "pending":
        return InvitationPreviewResponse(valid=False, reason=f"This invitation has already been {row['status']}")
    if row["expires_at"] < datetime.now(timezone.utc):
        return InvitationPreviewResponse(valid=False, reason="This invitation has expired")
    return InvitationPreviewResponse(
        valid=True, organization_name=row["organization_name"], role=row["role"], email=row["email"],
    )


@router.post("/invitations/{token}/accept", response_model=RegisterResponse)
async def accept_invitation(token: str, body: AcceptInvitationRequest, db: DBConn) -> RegisterResponse:
    password = body.password.strip()
    name = body.full_name.strip()
    if len(password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters")

    token_hash = hash_token(token)
    invitation = await db.fetchrow("SELECT * FROM organization_invitations WHERE token_hash = $1", token_hash)
    if not invitation:
        raise HTTPException(status_code=404, detail="Invitation not found")
    if invitation["status"] != "pending":
        raise HTTPException(status_code=400, detail=f"This invitation has already been {invitation['status']}")
    if invitation["expires_at"] < datetime.now(timezone.utc):
        raise HTTPException(status_code=400, detail="This invitation has expired")

    email = invitation["email"].strip().lower()

    # ── Multi-org membership isn't supported: get_current_org_id() assumes exactly
    # one active org per user, so an existing account can't safely accept a second. ──
    existing = await db.fetchval("SELECT 1 FROM users WHERE lower(email) = $1", email)
    if existing:
        raise HTTPException(
            status_code=409,
            detail="An account with this email already exists — multi-organization membership isn't supported yet.",
        )

    headers = _sb_headers()

    # ── Create Supabase Auth user (mirrors /auth/register's block exactly) ──
    async with httpx.AsyncClient(timeout=20) as client:
        res = await client.post(
            f"{settings.supabase_url}/auth/v1/admin/users",
            headers=headers,
            json={
                "email": email,
                "password": password,
                "email_confirm": True,
                "user_metadata": {"full_name": name},
            },
        )
        data = res.json()

    if res.status_code not in (200, 201):
        error = data.get("msg") or data.get("message") or "Registration failed"
        log.error(f"Supabase user creation failed (invite accept): {data}")
        raise HTTPException(status_code=400, detail=error)

    user_id = data["id"]
    log.info(f"Supabase user created via invite accept: {user_id} for {email}")

    # ── Join the INVITING organization — NOT a new one (the one branch difference
    # from normal /auth/register, which always creates a fresh org for the signer-up). ──
    async with db.transaction():
        await db.execute(
            """
            INSERT INTO users (id, email, full_name, is_admin, is_active)
            VALUES ($1, $2, $3, false, true)
            ON CONFLICT (id) DO UPDATE SET
                full_name  = EXCLUDED.full_name,
                updated_at = NOW()
            """,
            user_id, email, name,
        )
        await db.execute(
            """
            INSERT INTO organization_members (organization_id, user_id, role, is_active, invited_by)
            VALUES ($1, $2, $3, true, $4)
            ON CONFLICT (organization_id, user_id) DO NOTHING
            """,
            invitation["organization_id"], user_id, invitation["role"], invitation["invited_by"],
        )
        await db.execute(
            "UPDATE organization_invitations SET status = 'accepted', accepted_at = NOW() WHERE id = $1",
            invitation["id"],
        )

    if invitation["invited_by"]:
        try:
            await create_notification(
                db, user_id=invitation["invited_by"], category="team", type="team_invitation",
                title="New team member joined",
                body=f"{name or email} joined your organization.",
                link_section="settings", link_sub_tab="team",
            )
        except Exception as notif_exc:
            log.error(f"Notification failed for invite acceptance {invitation['id']}: {notif_exc}")

    # ── Sign in to get tokens (mirrors /auth/register's block exactly) ──
    async with httpx.AsyncClient(timeout=20) as client:
        res2 = await client.post(
            f"{settings.supabase_url}/auth/v1/token?grant_type=password",
            headers={
                "apikey": settings.supabase_anon_key,
                "Content-Type": "application/json",
            },
            json={"email": email, "password": password},
        )
        tokens = res2.json()

    if res2.status_code != 200:
        log.error(f"Auto-login failed after invite accept: {tokens}")
        raise HTTPException(status_code=200, detail="Account created! Please log in manually.")

    access_token  = tokens["access_token"]
    refresh_token = tokens["refresh_token"]

    user = User(
        id=user_id,
        email=email,
        full_name=name,
        is_admin=False,
        is_active=True,
        created_at=datetime.now(timezone.utc),
    )

    log.info(f"Invitation accepted for {email} — joined org {invitation['organization_id']}")
    return RegisterResponse(
        user=user,
        access_token=access_token,
        refresh_token=refresh_token,
    )