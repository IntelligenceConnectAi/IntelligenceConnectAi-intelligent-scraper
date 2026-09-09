"""
Phase 6 — Team invitation token helpers, shared by app/routers/organization.py
(create/resend) and app/routers/register.py (public preview/accept). No
email-sending infrastructure exists anywhere in this codebase (confirmed by
grepping requirements.txt and the whole app/ tree) — invitations are always a
one-time link the inviter copies/shares manually, never emailed.
"""

import hashlib
import secrets

from fastapi import Request

from app.config import settings


def generate_invite_token() -> tuple[str, str]:
    """Returns (raw_token, token_hash). Only the hash is ever persisted."""
    raw = secrets.token_urlsafe(32)
    return raw, hash_token(raw)


def hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def build_invite_link(request: Request, token: str) -> str:
    """Prefers the request's own Origin header (local dev's frontend often lands
    on a different port than vite.config.js requests, e.g. 5174 instead of 5173,
    when 5173 is already taken) — falls back to the first configured CORS origin
    for server-to-server calls with no Origin header."""
    origin = request.headers.get("origin")
    allowed = settings.cors_origins_list
    if origin and origin in allowed:
        base = origin
    else:
        base = allowed[0] if allowed else ""
    return f"{base.rstrip('/')}/join?token={token}"
