"""
Shared job-reset logic — used by both the manual admin retry endpoint
(app/routers/admin_jobs.py) and the worker's watchdog auto-requeue
(worker/main.py) so the reset SQL can never drift between the two call sites.

bump_retry_count=True (watchdog auto-requeue) increments jobs.retry_count.
bump_retry_count=False (human-initiated manual retry) resets it to 0 — a human
explicitly asking for a fresh attempt shouldn't inherit an exhausted auto-retry
budget from earlier watchdog recoveries.
"""

from uuid import UUID

import asyncpg


async def reset_job_to_pending(conn: asyncpg.Connection, job_id: UUID, *, bump_retry_count: bool) -> None:
    await conn.execute(
        """
        UPDATE jobs SET
            status = 'pending', current_step = NULL, current_city = NULL,
            cities_done = 0, total_raw = 0, total_clean = 0, with_website = 0, no_website = 0,
            emails_found = 0, emails_attempted = 0, duplicates_removed = 0,
            with_web_csv = NULL, no_web_csv = NULL, error_message = NULL,
            started_at = NULL, maps_done_at = NULL, emails_started_at = NULL, emails_done_at = NULL,
            completed_at = NULL,
            retry_count = CASE WHEN $2 THEN retry_count + 1 ELSE 0 END,
            updated_at = NOW()
        WHERE id = $1
        """,
        job_id, bump_retry_count,
    )
    await conn.execute(
        """
        UPDATE job_cities SET
            maps_status = 'pending', maps_leads = 0, status = 'pending',
            maps_started_at = NULL, maps_done_at = NULL, error = NULL
        WHERE job_id = $1
        """,
        job_id,
    )
