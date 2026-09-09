"""
Admin Audit Log viewer (Phase 8 — Lean MVP, judgment-call route, not in the doc's
literal §24 list): audit_logs has been populated by every phase since Phase 1 but had
zero read endpoint until now. RequireSuperAdmin — log contents can be sensitive
(who did what to whom, including permission grants/revokes and disable/enable actions).
"""

import json
from datetime import date
from typing import Optional
from uuid import UUID

from fastapi import APIRouter

from app.deps import DBConn
from app.permissions import SuperAdminDep
from app.schemas import AdminAuditLogEntry

router = APIRouter()


def _load_json(value):
    if value is None:
        return None
    if isinstance(value, str):
        return json.loads(value) if value else None
    return value


@router.get("", response_model=list[AdminAuditLogEntry])
async def list_audit_logs(
    admin: SuperAdminDep,
    db: DBConn,
    actor_user_id: Optional[UUID] = None,
    action: Optional[str] = None,
    resource_type: Optional[str] = None,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    limit: int = 100,
    offset: int = 0,
):
    conditions: list[str] = []
    params: list = []

    def add(cond: str, value):
        params.append(value)
        conditions.append(cond.format(n=len(params)))

    if actor_user_id: add("al.actor_user_id = ${n}", actor_user_id)
    if action: add("al.action = ${n}", action)
    if resource_type: add("al.resource_type = ${n}", resource_type)
    if date_from: add("al.created_at >= ${n}", date_from)
    if date_to: add("al.created_at <= ${n}", date_to)

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    limit = min(max(limit, 1), 500)
    params.extend([limit, offset])

    rows = await db.fetch(
        f"""
        SELECT al.id, al.actor_user_id, u.email AS actor_email, al.actor_role, al.action,
               al.resource_type, al.resource_id, al.previous_value_json, al.new_value_json,
               al.ip_address, al.user_agent, al.created_at
        FROM audit_logs al
        LEFT JOIN users u ON u.id = al.actor_user_id
        {where}
        ORDER BY al.created_at DESC
        LIMIT ${len(params) - 1} OFFSET ${len(params)}
        """,
        *params,
    )
    entries = []
    for r in rows:
        d = dict(r)
        d["previous_value_json"] = _load_json(d["previous_value_json"])
        d["new_value_json"] = _load_json(d["new_value_json"])
        entries.append(AdminAuditLogEntry(**d))
    return entries
