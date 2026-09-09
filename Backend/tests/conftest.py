"""
Phase 9 test infrastructure.

Isolation design (see the Phase 9 plan for the full rationale):
- A small, session-scoped pool of REAL Supabase auth users (created once via the
  same Admin-API httpx pattern app/routers/register.py already uses, deleted once
  at suite end) — real because public.users.id has a hard FK to auth.users.id.
- Every test gets its own connection wrapped in a transaction that is ALWAYS rolled
  back, never committed — so relabeling the same small pool of auth users with
  different public.users/org/role/permission rows per test is safe: nothing a test
  inserts survives past that test.
- app.dependency_overrides[get_db_conn] points every request the ASGI test client
  makes at that same connection, so the override transparently covers every route
  (confirmed: get_db_conn/DBConn is the only connection-acquisition path anywhere in
  app/ — no router or helper acquires its own connection).
- The one exception is test_migrations_idempotent.py, which deliberately uses its own
  standalone, non-transactional connection (see that file's docstring for why).
"""

import time
from uuid import uuid4

import httpx
import jwt
import pytest
import pytest_asyncio

from app.config import settings
from app.db import close_db_pool, get_pool, init_db_pool
from app.deps import get_db_conn
from app.main import app

SB_HEADERS = {
    "apikey": settings.supabase_service_role_key,
    "Authorization": f"Bearer {settings.supabase_service_role_key}",
    "Content-Type": "application/json",
}

AUTH_USER_POOL_SIZE = 8


@pytest_asyncio.fixture(scope="session", autouse=True, loop_scope="session")
async def _db_pool():
    await init_db_pool()
    yield
    await close_db_pool()


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def auth_user_pool(_db_pool):
    """A small, fixed set of real auth.users rows, created once and reused by every
    test with completely different roles/orgs — safe because every test's own
    public-schema inserts roll back. Avoids one real bcrypt-hashing HTTP round trip
    per test (the same class of "real but slow" problem already ruled out for
    Playwright in this phase's scope)."""
    ids = []
    async with httpx.AsyncClient(timeout=20) as client:
        for i in range(AUTH_USER_POOL_SIZE):
            email = f"test-fixture-{i}-{uuid4().hex[:8]}@example.test"
            res = await client.post(
                f"{settings.supabase_url}/auth/v1/admin/users",
                headers=SB_HEADERS,
                json={"email": email, "password": "TestFixture123!", "email_confirm": True},
            )
            assert res.status_code in (200, 201), res.text
            ids.append({"id": res.json()["id"], "email": email})
    yield ids
    async with httpx.AsyncClient(timeout=20) as client:
        for u in ids:
            await client.delete(
                f"{settings.supabase_url}/auth/v1/admin/users/{u['id']}", headers=SB_HEADERS
            )


@pytest_asyncio.fixture
async def db_conn():
    """Function-scoped: one connection, one transaction, ALWAYS rolled back —
    even on a passing test. Uses the low-level start()/rollback() form rather than
    `async with conn.transaction():`, which commits on clean exit."""
    pool = get_pool()
    async with pool.acquire() as conn:
        tx = conn.transaction()
        await tx.start()
        try:
            yield conn
        finally:
            await tx.rollback()


@pytest_asyncio.fixture
async def client(db_conn):
    """ASGI test client whose every request is transparently routed through the
    same rolled-back transaction as whatever the test itself inserts via db_conn."""
    async def _override():
        yield db_conn

    app.dependency_overrides[get_db_conn] = _override
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.pop(get_db_conn, None)


def mint_jwt(user_id, email: str) -> str:
    payload = {
        "sub": str(user_id),
        "email": email,
        "aud": "authenticated",
        "role": "authenticated",
        "iat": int(time.time()),
        "exp": int(time.time()) + 3600,
    }
    return jwt.encode(payload, settings.supabase_jwt_secret, algorithm="HS256")


def auth_headers(user_id, email: str) -> dict:
    return {"Authorization": f"Bearer {mint_jwt(user_id, email)}"}


@pytest.fixture
def make_headers():
    """Convenience: make_headers(user) where user is any dict/record with id+email."""
    def _make(user) -> dict:
        uid = user["id"] if isinstance(user, dict) else user.id
        email = user["email"] if isinstance(user, dict) else user.email
        return auth_headers(uid, email)
    return _make
