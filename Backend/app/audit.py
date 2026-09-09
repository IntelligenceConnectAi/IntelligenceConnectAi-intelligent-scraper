"""
Audit logging helper. asyncpg has no jsonb type codec configured on the pool
(see app/db.py), so previous/new values must be json.dumps'd and cast explicitly.
"""

import json
from typing import Any, Optional
from uuid import UUID

import asyncpg
from fastapi import Request


async def log_audit(
    conn: asyncpg.Connection,
    *,
    actor_user_id: Optional[UUID],
    actor_role: Optional[str],
    action: str,
    resource_type: Optional[str] = None,
    resource_id: Optional[str] = None,
    previous: Optional[Any] = None,
    new: Optional[Any] = None,
    request: Optional[Request] = None,
) -> None:
    ip_address = request.client.host if request and request.client else None
    user_agent = request.headers.get("user-agent") if request else None

    await conn.execute(
        """
        INSERT INTO audit_logs (
            actor_user_id, actor_role, action, resource_type, resource_id,
            previous_value_json, new_value_json, ip_address, user_agent
        )
        VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7::jsonb, $8, $9)
        """,
        actor_user_id,
        actor_role,
        action,
        resource_type,
        resource_id,
        json.dumps(previous) if previous is not None else None,
        json.dumps(new) if new is not None else None,
        ip_address,
        user_agent,
    )
