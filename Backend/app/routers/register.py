"""
POST /auth/register
User completes signup after Stripe payment.
Verifies email is in pending_signups, creates Supabase account,
assigns plan, logs user in.
"""

import logging
from datetime import datetime, timezone

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.config import settings
from app.deps import DBConn
from app.schemas import User

log = logging.getLogger(__name__)
router = APIRouter()


class RegisterRequest(BaseModel):
    email: str
    password: str
    full_name: str


class RegisterResponse(BaseModel):
    user: User
    access_token: str
    refresh_token: str


def _sb_headers() -> dict:
    return {
        "apikey": settings.supabase_service_role_key,
        "Authorization": f"Bearer {settings.supabase_service_role_key}",
        "Content-Type": "application/json",
    }


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
        error = data.get("msg") or data.get("message") or "Registration failed"
        log.error(f"Supabase user creation failed: {data}")
        raise HTTPException(status_code=400, detail=error)

    user_id = data["id"]
    log.info(f"Supabase user created: {user_id} for {email}")

    # ── 3. Insert into users table ──
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

    # ── 4. Assign subscription ──
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

    # ── 5. Remove from pending_signups ──
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


@router.get("/check-payment")
async def check_payment(email: str, db: DBConn):
    """Check if email has a pending payment (for frontend validation)."""
    row = await db.fetchrow(
        "SELECT plan_id FROM pending_signups WHERE lower(email) = $1",
        email.strip().lower()
    )
    if not row:
        return {"paid": False, "plan_id": None}
    return {"paid": True, "plan_id": row["plan_id"]}