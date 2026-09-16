"""
"Would the tightened watchdog catch this job, and does the reset/heartbeat SQL do
what it claims?" -- tested as pure SQL contracts, same rationale as
test_worker_contract.py: worker/main.py's watchdog loop is a separate long-running
OS process that can never see data sitting inside this test's uncommitted
transaction, so this copies the real queries verbatim and asserts against fixture
rows in isolation.
"""

import pytest

from app.jobs_reset import reset_job_to_pending
from tests.factories import make_client, make_job

pytestmark = pytest.mark.asyncio(loop_scope="session")

# Copied verbatim from worker/main.py::_watchdog_loop
STUCK_JOB_SQL = """
    SELECT id, user_id, industry, state, retry_count
    FROM jobs
    WHERE status = 'running'
      AND updated_at < NOW() - make_interval(mins => $1)
    FOR UPDATE SKIP LOCKED
"""
STUCK_THRESHOLD_MIN = 5


async def test_stuck_job_beyond_threshold_is_caught(db_conn, auth_user_pool):
    user_id, _org_id = await make_client(db_conn, auth_user_pool[0])
    job_id = await make_job(db_conn, user_id, status="running")
    await db_conn.execute(
        "UPDATE jobs SET updated_at = NOW() - INTERVAL '6 minutes' WHERE id = $1", job_id
    )

    rows = await db_conn.fetch(STUCK_JOB_SQL, STUCK_THRESHOLD_MIN)
    assert any(r["id"] == job_id for r in rows)


async def test_job_within_threshold_is_not_caught(db_conn, auth_user_pool):
    user_id, _org_id = await make_client(db_conn, auth_user_pool[1])
    job_id = await make_job(db_conn, user_id, status="running")
    await db_conn.execute(
        "UPDATE jobs SET updated_at = NOW() - INTERVAL '4 minutes' WHERE id = $1", job_id
    )

    rows = await db_conn.fetch(STUCK_JOB_SQL, STUCK_THRESHOLD_MIN)
    assert not any(r["id"] == job_id for r in rows)


async def test_pending_job_is_never_caught_regardless_of_age(db_conn, auth_user_pool):
    # The watchdog only ever targets 'running' jobs -- a job that's been 'pending'
    # for a long time (e.g. no active subscription) is a different problem the
    # watchdog must not touch.
    user_id, _org_id = await make_client(db_conn, auth_user_pool[2])
    job_id = await make_job(db_conn, user_id, status="pending")
    await db_conn.execute(
        "UPDATE jobs SET updated_at = NOW() - INTERVAL '1 hour' WHERE id = $1", job_id
    )

    rows = await db_conn.fetch(STUCK_JOB_SQL, STUCK_THRESHOLD_MIN)
    assert not any(r["id"] == job_id for r in rows)


async def test_auto_requeue_increments_retry_count_and_resets_progress(db_conn, auth_user_pool):
    user_id, _org_id = await make_client(db_conn, auth_user_pool[3])
    job_id = await make_job(db_conn, user_id, status="running", total_clean=42)
    await db_conn.execute(
        "UPDATE jobs SET current_step = 'step3_emails', emails_found = 5 WHERE id = $1", job_id
    )

    await reset_job_to_pending(db_conn, job_id, bump_retry_count=True)
    row = await db_conn.fetchrow(
        "SELECT status, retry_count, current_step, total_clean, emails_found FROM jobs WHERE id = $1", job_id
    )
    assert row["status"] == "pending"
    assert row["retry_count"] == 1
    assert row["current_step"] is None
    assert row["total_clean"] == 0
    assert row["emails_found"] == 0

    # A second auto-requeue reaches the MAX_AUTO_RETRIES=2 threshold worker/main.py
    # checks before switching to the permanent-fail branch.
    await reset_job_to_pending(db_conn, job_id, bump_retry_count=True)
    row = await db_conn.fetchrow("SELECT retry_count FROM jobs WHERE id = $1", job_id)
    assert row["retry_count"] == 2


async def test_manual_retry_resets_retry_count_to_zero(db_conn, auth_user_pool):
    # A human explicitly retrying a job that already exhausted its auto-retry
    # budget should get a clean slate, not immediately re-fail with zero chances.
    user_id, _org_id = await make_client(db_conn, auth_user_pool[4])
    job_id = await make_job(db_conn, user_id, status="failed")
    await db_conn.execute("UPDATE jobs SET retry_count = 2 WHERE id = $1", job_id)

    await reset_job_to_pending(db_conn, job_id, bump_retry_count=False)
    row = await db_conn.fetchrow("SELECT status, retry_count FROM jobs WHERE id = $1", job_id)
    assert row["status"] == "pending"
    assert row["retry_count"] == 0


HEARTBEAT_UPSERT_SQL = """
    INSERT INTO worker_heartbeats (worker_id, last_beat_at, consecutive_failures, pool_recreations, running_jobs, updated_at)
    VALUES ($1, NOW(), $2, $3, $4, NOW())
    ON CONFLICT (worker_id) DO UPDATE SET
        last_beat_at = EXCLUDED.last_beat_at,
        consecutive_failures = EXCLUDED.consecutive_failures,
        pool_recreations = EXCLUDED.pool_recreations,
        running_jobs = EXCLUDED.running_jobs,
        updated_at = NOW()
"""


async def test_heartbeat_upsert_keeps_a_single_row_with_latest_values(db_conn):
    await db_conn.execute(HEARTBEAT_UPSERT_SQL, "primary", 0, 0, 1)
    await db_conn.execute(HEARTBEAT_UPSERT_SQL, "primary", 2, 1, 0)

    rows = await db_conn.fetch("SELECT * FROM worker_heartbeats WHERE worker_id = 'primary'")
    assert len(rows) == 1
    assert rows[0]["consecutive_failures"] == 2
    assert rows[0]["pool_recreations"] == 1
    assert rows[0]["running_jobs"] == 0
