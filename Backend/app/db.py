"""
Database pool — asyncpg, opened on startup, closed on shutdown.

We connect with the service role's Postgres credentials, which bypasses
RLS. RLS stays ON as a safety net; the API enforces user_id filters in
every query manually.
"""

import asyncpg

from app.config import settings


_pool: asyncpg.Pool | None = None


async def init_db_pool() -> None:
    global _pool
    _pool = await asyncpg.create_pool(
        settings.database_url,
        min_size=2,
        max_size=10,
        command_timeout=30,
        statement_cache_size=0,  # required for Supabase pooler (pgbouncer)
    )


async def close_db_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


def get_pool() -> asyncpg.Pool:
    if _pool is None:
        raise RuntimeError("DB pool not initialized — call init_db_pool() first")
    return _pool
