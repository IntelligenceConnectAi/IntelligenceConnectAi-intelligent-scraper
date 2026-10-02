"""
Admin "Clients" view (Phase 8 Lean MVP + Clients Management Core tier + billing
hardening's admin refund action):
  GET   /admin/clients                 -> list organizations + owner/plan/seats (search/filter/paginate)
  GET   /admin/clients/plans           -> admin plan picker (includes inactive plans, unlike public GET /plans)
  GET   /admin/clients/{org_id}        -> detail: members + lifetime counts
  GET   /admin/clients/{org_id}/invoices   -> recent Stripe invoices for the client's billing owner
  POST  /admin/clients/{org_id}/suspend    -> disable every active member's login   (RequireSuperAdmin)
  POST  /admin/clients/{org_id}/reactivate -> re-enable exactly who the last suspend disabled (RequireSuperAdmin)
  PATCH /admin/clients/{org_id}/plan       -> reassign the billing owner's plan/lead-limits (RequireSuperAdmin)
  POST  /admin/clients/{org_id}/refund     -> refund a specific invoice, optionally suspend (RequireSuperAdmin)

RequireAdmin bare on the read-only routes — cross-cutting info every admin persona
plausibly needs (support fielding a ticket, billing checking a plan), not worth
inventing a new permission key for. Reuses the exact organizations ->
subscriptions(PK=user_id) -> plans join app/routers/organization.py's _seat_info()
already established.

Suspend/reactivate loop every active organization_members row, not just
owner_user_id: app/deps.py::get_current_user enforces access per-user
(users.is_active), not per-org, so disabling only the owner would leave
teammates with full access. organizations has no status column and
organization_members.is_active (team-membership relationship) is never touched
here — that's a different concern. Reactivate restores exactly the roster the
most recent suspend actually disabled, using the suspend action's own audit_logs
row as the snapshot (no new table): this correctly skips a teammate who was
individually disabled before the org suspend.

The refund route deliberately requires picking a specific invoice (via the
/invoices endpoint) rather than blindly refunding "the most recent charge" —
cheap to build via the shared app/stripe_helpers.py mapping, and meaningfully
safer against refunding the wrong payment.
"""

import json
from decimal import Decimal
from typing import Literal, Optional
from uuid import UUID

import stripe
from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel

from app.audit import log_audit
from app.config import settings
from app.deps import DBConn
from app.permissions import AdminDep, SuperAdminDep
from app.schemas import AdminClientDetail, AdminClientMember, AdminClientSummary, AdminPlanSummary, InvoiceResponse
from app.stripe_helpers import list_stripe_invoices
from app.user_status import set_user_active, suspend_org

stripe.api_key = settings.stripe_secret_key

router = APIRouter()

_BASE_SELECT = """
    SELECT o.id, o.name, o.created_at, o.owner_user_id,
           u.email AS owner_email, u.full_name AS owner_full_name, u.is_active AS owner_is_active,
           p.id AS plan_id, p.name AS plan_name, s.status AS subscription_status,
           p.max_team_seats,
           (SELECT COUNT(*) FROM organization_members om
            WHERE om.organization_id = o.id AND om.is_active = true) AS seats_used
    FROM organizations o
    JOIN users u ON u.id = o.owner_user_id
    LEFT JOIN subscriptions s ON s.user_id = o.owner_user_id AND s.status = 'active'
    LEFT JOIN plans p ON p.id = s.plan_id
"""


@router.get("", response_model=list[AdminClientSummary])
async def list_clients(
    admin: AdminDep,
    db: DBConn,
    q: Optional[str] = None,
    active: Optional[bool] = None,
    limit: int = 50,
    offset: int = 0,
):
    conditions: list[str] = []
    params: list = []

    if q:
        params.append(f"%{q}%")
        conditions.append(f"(o.name ILIKE ${len(params)} OR u.email ILIKE ${len(params)} OR u.full_name ILIKE ${len(params)})")
    if active is not None:
        params.append(active)
        conditions.append(f"u.is_active = ${len(params)}")

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    limit = min(max(limit, 1), 200)
    params.append(limit)
    params.append(max(offset, 0))
    rows = await db.fetch(
        f"{_BASE_SELECT} {where} ORDER BY o.created_at DESC LIMIT ${len(params) - 1} OFFSET ${len(params)}",
        *params,
    )
    return [AdminClientSummary(**dict(r)) for r in rows]


@router.get("/plans", response_model=list[AdminPlanSummary])
async def list_admin_plans(admin: AdminDep, db: DBConn):
    rows = await db.fetch(
        """
        SELECT id, name, price_monthly, leads_per_month, leads_per_day, is_active
        FROM plans
        ORDER BY display_order NULLS LAST, price_monthly
        """
    )
    return [AdminPlanSummary(**dict(r)) for r in rows]


@router.get("/{org_id}", response_model=AdminClientDetail)
async def get_client(org_id: UUID, admin: AdminDep, db: DBConn):
    row = await db.fetchrow(f"{_BASE_SELECT} WHERE o.id = $1", org_id)
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Client not found")

    member_rows = await db.fetch(
        """
        SELECT om.user_id, u.email, u.full_name, om.role, u.is_active
        FROM organization_members om JOIN users u ON u.id = om.user_id
        WHERE om.organization_id = $1 AND om.is_active = true
        ORDER BY om.created_at ASC
        """,
        org_id,
    )
    jobs_count = await db.fetchval(
        """
        SELECT COUNT(*) FROM jobs
        WHERE user_id IN (SELECT user_id FROM organization_members WHERE organization_id = $1 AND is_active = true)
        """,
        org_id,
    )
    people_requests_count = await db.fetchval(
        "SELECT COUNT(*) FROM people_lead_requests WHERE organization_id = $1", org_id
    )
    lead_files_count = await db.fetchval(
        "SELECT COUNT(*) FROM lead_files WHERE organization_id = $1", org_id
    )
    support_tickets_count = await db.fetchval(
        "SELECT COUNT(*) FROM support_tickets WHERE organization_id = $1", org_id
    )

    return AdminClientDetail(
        **dict(row),
        members=[AdminClientMember(**dict(m)) for m in member_rows],
        jobs_count=jobs_count, people_requests_count=people_requests_count,
        lead_files_count=lead_files_count, support_tickets_count=support_tickets_count,
    )


async def _require_org(db: DBConn, org_id: UUID):
    org = await db.fetchrow("SELECT id, owner_user_id FROM organizations WHERE id = $1", org_id)
    if not org:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Client not found")
    return org


@router.post("/{org_id}/suspend")
async def suspend_client(org_id: UUID, admin: SuperAdminDep, db: DBConn, request: Request):
    await _require_org(db, org_id)
    member_ids = await suspend_org(
        db, org_id, actor_user_id=admin.id, actor_role=admin.platform_role, request=request
    )
    return {"message": f"Client suspended ({len(member_ids)} account(s) disabled)"}


@router.post("/{org_id}/reactivate")
async def reactivate_client(org_id: UUID, admin: SuperAdminDep, db: DBConn, request: Request):
    await _require_org(db, org_id)

    last_suspend = await db.fetchrow(
        """
        SELECT new_value_json FROM audit_logs
        WHERE resource_type = 'organizations' AND resource_id = $1 AND action = 'client_org_suspended'
        ORDER BY created_at DESC LIMIT 1
        """,
        str(org_id),
    )
    current_member_ids = {
        r["user_id"]
        for r in await db.fetch(
            "SELECT user_id FROM organization_members WHERE organization_id = $1 AND is_active = true", org_id
        )
    }

    if last_suspend is not None:
        snapshot_ids = set(json.loads(last_suspend["new_value_json"])["disabled_user_ids"])
        target_ids = [uid for uid in current_member_ids if str(uid) in snapshot_ids]
    else:
        target_ids = list(current_member_ids)

    for user_id in target_ids:
        await set_user_active(db, user_id, True)

    await log_audit(
        db, actor_user_id=admin.id, actor_role=admin.platform_role,
        action="client_org_reactivated", resource_type="organizations", resource_id=str(org_id),
        new={"enabled_user_ids": [str(u) for u in target_ids]}, request=request,
    )
    return {"message": f"Client reactivated ({len(target_ids)} account(s) enabled)"}


class UpdateClientPlanRequest(BaseModel):
    plan_id: str
    status: Literal["active", "trialing", "past_due", "canceled"] = "active"


@router.patch("/{org_id}/plan")
async def update_client_plan(
    org_id: UUID, body: UpdateClientPlanRequest, admin: SuperAdminDep, db: DBConn, request: Request,
):
    org = await _require_org(db, org_id)

    plan = await db.fetchrow("SELECT id FROM plans WHERE id = $1", body.plan_id)
    if not plan:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Unknown plan_id: {body.plan_id}")

    owner_id = org["owner_user_id"]
    previous = await db.fetchrow("SELECT plan_id, status FROM subscriptions WHERE user_id = $1", owner_id)

    await db.execute(
        """
        INSERT INTO subscriptions (user_id, plan_id, status, current_period_end)
        VALUES ($1, $2, $3, NOW() + INTERVAL '30 days')
        ON CONFLICT (user_id) DO UPDATE SET
            plan_id = EXCLUDED.plan_id,
            status = EXCLUDED.status,
            -- Only fill in a period when one is genuinely missing (a subscriptions
            -- row this endpoint is creating for the first time, or one left NULL by
            -- an earlier bug) -- never clobber a real Stripe-sourced period that's
            -- already set, since this endpoint has no way to know the true cycle
            -- boundary once Stripe owns it.
            current_period_end = COALESCE(subscriptions.current_period_end, EXCLUDED.current_period_end),
            updated_at = NOW()
        """,
        owner_id, body.plan_id, body.status,
    )
    await log_audit(
        db, actor_user_id=admin.id, actor_role=admin.platform_role,
        action="client_plan_changed", resource_type="organizations", resource_id=str(org_id),
        previous=dict(previous) if previous else None,
        new={"plan_id": body.plan_id, "status": body.status}, request=request,
    )
    return {"message": f"Plan changed to {body.plan_id}"}


@router.get("/{org_id}/invoices", response_model=list[InvoiceResponse])
async def list_client_invoices(org_id: UUID, admin: AdminDep, db: DBConn):
    org = await _require_org(db, org_id)
    customer_id = await db.fetchval("SELECT stripe_customer_id FROM users WHERE id = $1", org["owner_user_id"])
    if not customer_id:
        return []
    return await list_stripe_invoices(customer_id)


class RefundInvoiceRequest(BaseModel):
    invoice_id: str
    amount: Optional[Decimal] = None  # None = full refund of the invoice's charge
    reason: Optional[Literal["duplicate", "fraudulent", "requested_by_customer"]] = None
    also_suspend: bool = True


@router.post("/{org_id}/refund")
async def refund_client_charge(
    org_id: UUID, body: RefundInvoiceRequest, admin: SuperAdminDep, db: DBConn, request: Request,
):
    org = await _require_org(db, org_id)
    customer_id = await db.fetchval("SELECT stripe_customer_id FROM users WHERE id = $1", org["owner_user_id"])
    if not customer_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="This client has no Stripe customer on file")

    try:
        invoice = stripe.Invoice.retrieve(body.invoice_id)
    except stripe.error.StripeError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Could not retrieve invoice: {e}")
    if invoice.get("customer") != customer_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="That invoice does not belong to this client")
    if invoice.get("status") != "paid":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Only paid invoices can be refunded")
    charge_id = invoice.get("charge")
    if not charge_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="This invoice has no associated charge to refund")

    kwargs: dict = {"charge": charge_id}
    if body.amount is not None:
        kwargs["amount"] = int(body.amount * 100)
    if body.reason:
        kwargs["reason"] = body.reason
    try:
        refund = stripe.Refund.create(**kwargs)
    except stripe.error.StripeError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Stripe refund failed: {e}")

    # Written synchronously, before Stripe's own charge.refunded webhook can plausibly
    # arrive — app/routers/billing.py::_handle_charge_refunded checks for this exact
    # (org_id, charge_id) row to avoid re-deciding suspension on top of this admin's
    # explicit also_suspend choice.
    await log_audit(
        db, actor_user_id=admin.id, actor_role=admin.platform_role, action="admin_refund_issued",
        resource_type="organizations", resource_id=str(org_id),
        new={
            "invoice_id": body.invoice_id, "charge_id": charge_id, "refund_id": refund["id"],
            "amount": str(body.amount) if body.amount is not None else "full", "reason": body.reason,
        },
        request=request,
    )

    if body.also_suspend:
        await suspend_org(db, org_id, actor_user_id=admin.id, actor_role=admin.platform_role, request=request)

    return {
        "message": "Refund issued" + (" and client suspended" if body.also_suspend else ""),
        "refund_id": refund["id"],
    }
