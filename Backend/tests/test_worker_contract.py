"""
"Would the real worker pick this job up?" -- tested as a pure SQL contract, not by
running the actual worker process or Playwright. worker/main.py's poll loop is a
separate long-running OS process with its own connection pool; it can never see
data sitting inside this test's uncommitted transaction, so there's no way to
observe it directly. Instead this copies the worker's REAL poll query verbatim
(not a paraphrase) and asserts a fixture job is/isn't a member of its result set.

The real query requires an ACTIVE subscription joined to a plan for the job's
owning user -- a bare `status='pending'` job for a user with no/inactive
subscription is invisible to the worker and would never run. This is the detail a
naive test would miss.
"""

import pytest

from tests.factories import make_client, make_job, make_subscription

pytestmark = pytest.mark.asyncio(loop_scope="session")

# Copied verbatim from worker/main.py::_poll_loop
WORKER_POLL_SQL = """
    SELECT
        j.id, j.user_id, j.industry, j.state, j.cities,
        p.email_scraping AS plan_email_scraping
    FROM jobs j
    JOIN subscriptions s ON s.user_id = j.user_id AND s.status = 'active'
    JOIN plans p         ON p.id = s.plan_id
    WHERE j.status = 'pending'
    ORDER BY j.created_at ASC
    LIMIT $1
"""


async def test_pending_job_with_active_subscription_is_visible_to_worker(db_conn, auth_user_pool):
    user_id, _org_id = await make_client(db_conn, auth_user_pool[0])
    job_id = await make_job(db_conn, user_id, status="pending")

    rows = await db_conn.fetch(WORKER_POLL_SQL, 10000)
    assert any(r["id"] == job_id for r in rows)


async def test_pending_job_without_active_subscription_is_invisible_to_worker(db_conn, auth_user_pool):
    user_id, _org_id = await make_client(db_conn, auth_user_pool[1])
    # Deactivate the subscription the fixture created -- the job must not be
    # pickable by the worker's real query without an active plan.
    await make_subscription(db_conn, user_id, status="canceled")
    job_id = await make_job(db_conn, user_id, status="pending")

    rows = await db_conn.fetch(WORKER_POLL_SQL, 10000)
    assert not any(r["id"] == job_id for r in rows)
