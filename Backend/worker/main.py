"""
Intelligent Scraper — Background Worker
Polls the jobs table every 3 seconds for pending jobs.

Global limit: MAX_GLOBAL_CONCURRENT = 10
  - Max 10 jobs running at the same time across ALL users
  - 11th user waits in queue
  - As soon as any of the 10 finish, next pending job starts automatically
"""

import asyncio
import logging
import signal

import asyncpg

from app.config import settings
from app.storage import upload_csv
from worker.runner import run_scrape_job

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [WORKER] %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

# ── Global concurrency limit ──────────────────────────────────
MAX_GLOBAL_CONCURRENT = 5   # max jobs running at once across all users

# job_id → user_id for currently running jobs
_running: dict[str, str] = {}
_shutdown = False


async def _upload(content: bytes, storage_path: str) -> str:
    return await upload_csv(storage_path, content)


async def _process_job(job: dict, pool: asyncpg.Pool) -> None:
    job_id  = str(job["id"])
    user_id = str(job["user_id"])
    log.info(f"▶ Starting job {job_id[:8]}  [{job['industry']} / {job['state']} / {len(job['cities'])} cities]  [{len(_running)}/{MAX_GLOBAL_CONCURRENT} slots used]")

    try:
        result = await run_scrape_job(
            job_id         = job_id,
            user_id        = user_id,
            industry       = job["industry"],
            state          = job["state"],
            cities         = list(job["cities"]),
            include_emails = bool(job["plan_email_scraping"]),
            pool           = pool,
            upload_fn      = _upload,
        )

        async with pool.acquire() as conn:
            await conn.execute(
                "SELECT update_usage_after_job($1,$2,$3,$4,$5,$6)",
                job["user_id"],
                result["total_clean"],
                result["with_website"],
                result["no_website"],
                result["emails_found"],
                result["with_website"],
            )

        log.info(f"✅ Job {job_id[:8]} done — {result['total_clean']} leads, {result['emails_found']} emails  [{len(_running)-1}/{MAX_GLOBAL_CONCURRENT} slots used]")

    except Exception as exc:
        log.error(f"❌ Job {job_id[:8]} failed: {exc}", exc_info=True)
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE jobs SET status='failed', error_message=$2, updated_at=NOW() WHERE id=$1",
                job["id"], str(exc)[:500],
            )

    finally:
        _running.pop(job_id, None)
        log.info(f"🔓 Slot freed — {len(_running)}/{MAX_GLOBAL_CONCURRENT} slots now used")


async def _poll_loop(pool: asyncpg.Pool) -> None:
    log.info(f"👀 Worker polling every 3 seconds — global limit: {MAX_GLOBAL_CONCURRENT} concurrent jobs")

    while not _shutdown:
        try:
            # How many slots are free?
            free_slots = MAX_GLOBAL_CONCURRENT - len(_running)

            if free_slots > 0:
                rows = await pool.fetch(
                    """
                    SELECT
                        j.id, j.user_id, j.industry, j.state, j.cities,
                        p.email_scraping AS plan_email_scraping
                    FROM jobs j
                    JOIN subscriptions s ON s.user_id = j.user_id AND s.status = 'active'
                    JOIN plans p         ON p.id = s.plan_id
                    WHERE j.status = 'pending'
                    ORDER BY j.created_at ASC
                    LIMIT $1
                    """,
                    free_slots,
                )

                for job in rows:
                    job_id = str(job["id"])

                    if job_id in _running:
                        continue

                    # Still within global limit?
                    if len(_running) >= MAX_GLOBAL_CONCURRENT:
                        break

                    _running[job_id] = str(job["user_id"])
                    asyncio.create_task(_process_job(dict(job), pool))
                    log.info(f"📥 Queued job {job_id[:8]} — {len(_running)}/{MAX_GLOBAL_CONCURRENT} slots now used")

        except Exception as e:
            log.error(f"Poll loop error: {e}", exc_info=True)

        await asyncio.sleep(3)


async def main() -> None:
    log.info("🚀 Intelligent Scraper Worker starting…")
    log.info(f"⚙️  Global concurrent job limit: {MAX_GLOBAL_CONCURRENT}")

    pool = await asyncpg.create_pool(
        settings.database_url,
        min_size=2,
        max_size=5,
        command_timeout=60,
        statement_cache_size=0,
    )

    loop = asyncio.get_running_loop()

    def _handle_signal():
        global _shutdown
        _shutdown = True
        log.info("🛑 Shutdown signal — finishing current jobs then exiting…")

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _handle_signal)
        except NotImplementedError:
            pass

    await _poll_loop(pool)
    await pool.close()
    log.info("Worker stopped.")


if __name__ == "__main__":
    asyncio.run(main())