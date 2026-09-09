"""
Deliberately uses its OWN standalone connection -- never the shared transactional
fixture from conftest.py. Every migration file's SQL text contains literal
BEGIN;/COMMIT; -- running that raw text through a connection already wrapped in a
Python-level conn.transaction() would let the literal COMMIT silently end the outer
transaction early, defeating the rollback-based isolation every other test relies
on. This is the one test in the suite that is not fully hermetic against the shared
dev database, and that's a deliberate, justified exception: every statement in all
6 migration files is IF NOT EXISTS / ON CONFLICT DO NOTHING / CREATE OR REPLACE
(confirmed by reading all of them), so re-running them a second time is a true no-op.
"""

import pathlib

import asyncpg
import pytest

from app.config import settings

MIGRATIONS_DIR = pathlib.Path(__file__).parent.parent / "migrations"


@pytest.mark.asyncio(loop_scope="session")
async def test_all_migrations_rerun_without_error():
    files = sorted(MIGRATIONS_DIR.glob("*.sql"))
    assert files, "expected at least one migration file"

    conn = await asyncpg.connect(settings.database_url)
    try:
        for path in files:
            await conn.execute(path.read_text(encoding="utf-8"))
    finally:
        await conn.close()
