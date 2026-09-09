"""
Team management (Phase 6, §17/§24.2) — the first real use of Phase 1's
organization_members/organization_invitations tables, which were schema-only
until now.

Role gating (§5.1-5.3): Account Owner can invite/remove/change-role for anyone;
Client Admin can invite/remove ONLY Client Members (never change roles at all —
that's Owner-only); Client Member has no team-management access. GET "/members"
is the one exception left open to all active roles (read-only roster).

Invitations are never emailed — no email-sending infrastructure exists anywhere
in this codebase (see app/invitations.py). Create/resend return a one-time raw
link for the inviter to copy/share manually.
"""

from datetime import datetime, timedelta, timezone
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.audit import log_audit
from app.deps import DBConn
from app.invitations import build_invite_link, generate_invite_token
from app.org_access import MyMembershipDep, RequireOrgRole
from app.schemas import (
    CreateInvitationRequest,
    CreateInvitationResponse,
    InvitationResponse,
    OrganizationMemberResponse,
    OrganizationResponse,
    PatchOrganizationRequest,
    UpdateMemberRoleRequest,
)

router = APIRouter()

INVITE_TTL = timedelta(days=7)


def _to_invitation_response(row) -> InvitationResponse:
    d = dict(row)
    d["is_expired"] = d["expires_at"] < datetime.now(timezone.utc)
    return InvitationResponse(**d)


async def _seat_info(db, org_id: UUID) -> tuple[int | None, int, int | None]:
    max_seats = await db.fetchval(
        """
        SELECT p.max_team_seats
        FROM organizations o
        JOIN subscriptions s ON s.user_id = o.owner_user_id AND s.status = 'active'
        JOIN plans p ON p.id = s.plan_id
        WHERE o.id = $1
        """,
        org_id,
    )
    active_members = await db.fetchval(
        "SELECT COUNT(*) FROM organization_members WHERE organization_id = $1 AND is_active = true",
        org_id,
    )
    pending_invites = await db.fetchval(
        "SELECT COUNT(*) FROM organization_invitations WHERE organization_id = $1 AND status = 'pending' AND expires_at > NOW()",
        org_id,
    )
    used = active_members + pending_invites
    remaining = (max_seats - used) if max_seats is not None else None
    return max_seats, used, remaining


async def _build_org_response(db, org_id: UUID, my_role: str) -> OrganizationResponse:
    org = await db.fetchrow("SELECT * FROM organizations WHERE id = $1", org_id)
    if not org:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found")
    max_seats, used, remaining = await _seat_info(db, org["id"])
    return OrganizationResponse(
        id=org["id"], name=org["name"], my_role=my_role,
        max_team_seats=max_seats, seats_used=used, seats_remaining=remaining,
        created_at=org["created_at"],
    )


@router.get("", response_model=OrganizationResponse)
async def get_organization(membership: MyMembershipDep, db: DBConn):
    return await _build_org_response(db, membership["organization_id"], membership["role"])


@router.patch("", response_model=OrganizationResponse)
async def rename_organization(
    body: PatchOrganizationRequest,
    membership: Annotated[dict, Depends(RequireOrgRole("account_owner"))],
    db: DBConn,
    request: Request,
):
    org_id = membership["organization_id"]
    previous = await db.fetchrow("SELECT name FROM organizations WHERE id = $1", org_id)
    await db.execute(
        "UPDATE organizations SET name = $2, updated_at = NOW() WHERE id = $1",
        org_id, body.name.strip(),
    )
    await log_audit(
        db, actor_user_id=None, actor_role=membership["role"],
        action="organization_renamed", resource_type="organizations", resource_id=str(org_id),
        previous={"name": previous["name"]}, new={"name": body.name.strip()}, request=request,
    )
    return await _build_org_response(db, org_id, membership["role"])


@router.get("/members", response_model=list[OrganizationMemberResponse])
async def list_members(membership: MyMembershipDep, db: DBConn):
    rows = await db.fetch(
        """
        SELECT om.id, om.user_id, u.email, u.full_name, om.role, om.created_at
        FROM organization_members om
        JOIN users u ON u.id = om.user_id
        WHERE om.organization_id = $1 AND om.is_active = true
        ORDER BY om.created_at ASC
        """,
        membership["organization_id"],
    )
    return [OrganizationMemberResponse(**dict(r)) for r in rows]


@router.get("/invitations", response_model=list[InvitationResponse])
async def list_invitations(
    membership: Annotated[dict, Depends(RequireOrgRole("account_owner", "client_admin"))],
    db: DBConn,
):
    rows = await db.fetch(
        "SELECT * FROM organization_invitations WHERE organization_id = $1 AND status = 'pending' ORDER BY created_at DESC",
        membership["organization_id"],
    )
    return [_to_invitation_response(r) for r in rows]


@router.post("/invitations", response_model=CreateInvitationResponse, status_code=status.HTTP_201_CREATED)
async def create_invitation(
    body: CreateInvitationRequest,
    membership: Annotated[dict, Depends(RequireOrgRole("account_owner", "client_admin"))],
    db: DBConn,
    request: Request,
):
    org_id = membership["organization_id"]
    email = body.email.strip().lower()

    if membership["role"] == "client_admin" and body.role != "client_member":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Client Admins can only invite Client Members",
        )

    existing_user = await db.fetchval("SELECT 1 FROM users WHERE lower(email) = $1", email)
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with this email already exists — multi-organization membership isn't supported yet.",
        )

    max_seats, used, _ = await _seat_info(db, org_id)
    existing_invite = await db.fetchrow(
        "SELECT id FROM organization_invitations WHERE organization_id = $1 AND lower(email) = $2 AND status = 'pending'",
        org_id, email,
    )
    if max_seats is not None and used >= max_seats and not existing_invite:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Seat limit reached ({used}/{max_seats}). Remove a member or upgrade your plan.",
        )

    raw_token, token_hash = generate_invite_token()
    expires_at = datetime.now(timezone.utc) + INVITE_TTL

    if existing_invite:
        row = await db.fetchrow(
            """
            UPDATE organization_invitations
            SET role = $2, token_hash = $3, expires_at = $4, invited_by = $5
            WHERE id = $1
            RETURNING *
            """,
            existing_invite["id"], body.role, token_hash, expires_at, membership.get("user_id"),
        )
    else:
        row = await db.fetchrow(
            """
            INSERT INTO organization_invitations
                (organization_id, email, role, token_hash, status, invited_by, expires_at)
            VALUES ($1,$2,$3,$4,'pending',$5,$6)
            RETURNING *
            """,
            org_id, email, body.role, token_hash, membership.get("user_id"), expires_at,
        )

    await log_audit(
        db, actor_user_id=membership.get("user_id"), actor_role=membership["role"],
        action="team_invitation_created", resource_type="organization_invitations",
        resource_id=str(row["id"]), new={"email": email, "role": body.role}, request=request,
    )

    return CreateInvitationResponse(
        invitation=_to_invitation_response(row),
        invite_link=build_invite_link(request, raw_token),
    )


async def _get_invitation_for_org(db, invitation_id: UUID, org_id: UUID):
    row = await db.fetchrow(
        "SELECT * FROM organization_invitations WHERE id = $1 AND organization_id = $2",
        invitation_id, org_id,
    )
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invitation not found")
    return row


def _check_invitation_role_gate(membership: dict, invitation) -> None:
    if membership["role"] == "client_admin" and invitation["role"] != "client_member":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Client Admins can only manage Client Member invitations",
        )


@router.post("/invitations/{invitation_id}/resend", response_model=CreateInvitationResponse)
async def resend_invitation(
    invitation_id: UUID,
    membership: Annotated[dict, Depends(RequireOrgRole("account_owner", "client_admin"))],
    db: DBConn,
    request: Request,
):
    invitation = await _get_invitation_for_org(db, invitation_id, membership["organization_id"])
    if invitation["status"] != "pending":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Only pending invitations can be resent")
    _check_invitation_role_gate(membership, invitation)

    raw_token, token_hash = generate_invite_token()
    expires_at = datetime.now(timezone.utc) + INVITE_TTL
    row = await db.fetchrow(
        "UPDATE organization_invitations SET token_hash = $2, expires_at = $3 WHERE id = $1 RETURNING *",
        invitation_id, token_hash, expires_at,
    )
    await log_audit(
        db, actor_user_id=membership.get("user_id"), actor_role=membership["role"],
        action="team_invitation_resent", resource_type="organization_invitations",
        resource_id=str(invitation_id), request=request,
    )
    return CreateInvitationResponse(
        invitation=_to_invitation_response(row),
        invite_link=build_invite_link(request, raw_token),
    )


@router.delete("/invitations/{invitation_id}")
async def cancel_invitation(
    invitation_id: UUID,
    membership: Annotated[dict, Depends(RequireOrgRole("account_owner", "client_admin"))],
    db: DBConn,
    request: Request,
):
    invitation = await _get_invitation_for_org(db, invitation_id, membership["organization_id"])
    if invitation["status"] != "pending":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invitation is not pending")
    _check_invitation_role_gate(membership, invitation)

    await db.execute("UPDATE organization_invitations SET status = 'cancelled' WHERE id = $1", invitation_id)
    await log_audit(
        db, actor_user_id=membership.get("user_id"), actor_role=membership["role"],
        action="team_invitation_cancelled", resource_type="organization_invitations",
        resource_id=str(invitation_id), request=request,
    )
    return {"message": "Invitation cancelled"}


async def _get_member_for_org(db, member_id: UUID, org_id: UUID):
    row = await db.fetchrow(
        "SELECT * FROM organization_members WHERE id = $1 AND organization_id = $2 AND is_active = true",
        member_id, org_id,
    )
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Member not found")
    return row


@router.patch("/members/{member_id}", response_model=OrganizationMemberResponse)
async def update_member_role(
    member_id: UUID,
    body: UpdateMemberRoleRequest,
    membership: Annotated[dict, Depends(RequireOrgRole("account_owner"))],
    db: DBConn,
    request: Request,
):
    member = await _get_member_for_org(db, member_id, membership["organization_id"])
    if member["role"] == "account_owner":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot change the account owner's role")

    await db.execute("UPDATE organization_members SET role = $2, updated_at = NOW() WHERE id = $1", member_id, body.role)
    await log_audit(
        db, actor_user_id=membership.get("user_id"), actor_role=membership["role"],
        action="team_member_role_changed", resource_type="organization_members", resource_id=str(member_id),
        previous={"role": member["role"]}, new={"role": body.role}, request=request,
    )
    row = await db.fetchrow(
        """
        SELECT om.id, om.user_id, u.email, u.full_name, om.role, om.created_at
        FROM organization_members om JOIN users u ON u.id = om.user_id
        WHERE om.id = $1
        """,
        member_id,
    )
    return OrganizationMemberResponse(**dict(row))


@router.delete("/members/{member_id}")
async def remove_member(
    member_id: UUID,
    membership: Annotated[dict, Depends(RequireOrgRole("account_owner", "client_admin"))],
    db: DBConn,
    request: Request,
):
    member = await _get_member_for_org(db, member_id, membership["organization_id"])
    if member["role"] == "account_owner":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot remove the account owner")
    if membership["role"] == "client_admin" and member["role"] != "client_member":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Client Admins can only remove Client Members")
    if member["user_id"] == membership.get("user_id"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot remove yourself")

    await db.execute("UPDATE organization_members SET is_active = false, updated_at = NOW() WHERE id = $1", member_id)
    await log_audit(
        db, actor_user_id=membership.get("user_id"), actor_role=membership["role"],
        action="team_member_removed", resource_type="organization_members", resource_id=str(member_id),
        previous={"role": member["role"]}, request=request,
    )
    return {"message": "Member removed"}
