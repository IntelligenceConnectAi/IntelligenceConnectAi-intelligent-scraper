"""
Intelligent Scraper — Background Worker
Polls the jobs table every 3 seconds for pending jobs.

Global limit: MAX_GLOBAL_CONCURRENT = 2
  - Max 2 jobs running at the same time PER REPLICA of this service (pulled
    down from an earlier 10 after real production incidents — see the
    constant's own comment below for the full story). Total cluster-wide
    capacity is this × however many replicas Railway is running.
  - The next pending job past that per-replica limit waits in queue, picked up
    by whichever replica (this one or another) next has a free slot.
  - As soon as any running job finishes, the next pending job starts automatically.

Step 4 — horizontal replicas:
  - Job claiming uses `SELECT ... FOR UPDATE SKIP LOCKED` (see _poll_loop) so
    multiple replicas can poll concurrently without ever grabbing the same
    job — a second replica's query simply never sees a row this one already
    has locked, instead of racing to claim it too. The status flip to
    'running' happens in the same transaction as the claim.
  - Each replica has its own heartbeat identity (HEARTBEAT_WORKER_ID, derived
    from Railway's RAILWAY_REPLICA_ID) instead of one shared row, so a
    specific replica dying is visible instead of being masked by others'
    heartbeats overwriting it.
  - The watchdog also claims stuck jobs with FOR UPDATE SKIP LOCKED, so with N
    replicas all running their own watchdog loop, only one of them actually
    resets a given stuck row — no leader election needed, every replica is
    equally capable of watchdog duty.
  - A replica can only task.cancel() a job it is itself tracking in-process —
    it has no way to reach into another replica's process. The ownership-
    fencing check in runner.py's _is_job_canceled (via claim_token) is what
    makes a reset from a DIFFERENT replica's watchdog actually stop the
    original task: reset_job_to_pending() clears started_at, the next claim
    stamps a fresh value, and the original task's per-item checks notice the
    mismatch and abandon their work on their own.

Resilience (worker_heartbeats table, jobs.retry_count):
  - The poll loop writes a heartbeat every cycle; 3 consecutive DB failures trigger
    a forced connection-pool recreation (see PoolHolder) rather than trusting the
    pool to self-heal — a real incident showed a stale pool can stay non-functional
    for minutes otherwise.
  - The watchdog runs every 45s (not 5min) and looks for jobs stuck >5min in
    'running'. It cancels any still-tracked in-process task for that job first
    (closing a zombie-task race — without this, auto-requeuing a job whose original
    task is merely hung, not dead, would create two coroutines writing the same
    job_id) before auto-requeuing it (bounded to MAX_AUTO_RETRIES) or, once
    exhausted, marking it permanently failed with a real client notification.
"""

import asyncio
import logging
import os
import signal
import sys

import asyncpg

from app.config import settings
from app.jobs_reset import reset_job_to_pending
from app.leads_index import index_business_job_files
from app.notifications import create_notification
from app.storage import delete_object, try_download_object, upload_csv
from worker.runner import run_scrape_job

# UTF-8 defense-in-depth: hardcoded emoji were already removed from log messages
# below, but *dynamic* content (a scraped business name, an exception message) can
# still contain non-ASCII and hit the same Windows-console wall — reconfigure() is a
# no-op on Railway's Linux containers, it only matters for local Windows dev.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    datefmt="%H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger(__name__)

# ── Global concurrency limit ──────────────────────────────────
# Was 2, raised to 10 for the first Tier-1 pass, then pulled back down TWICE
# after real production incidents on Railway: pthread_create failures under
# real concurrent load — not a CPU/RAM shortage (24 vCPU/24GB was barely
# touched), but the container's process/thread ceiling, which multiplies
# with how many jobs run at once × each job's own browser-process count
# (worker/runner.py's MAX_CONCURRENT_EMAIL). Even 4 here combined with the
# first pullback's MAX_CONCURRENT_EMAIL=3 still failed with 2 jobs
# overlapping (6 concurrent full Chrome processes). Re-tune upward only with
# real evidence of the actual ceiling, tested with 2+ jobs running at once —
# a single job in isolation does not reproduce this.
MAX_GLOBAL_CONCURRENT = 2

# ── Resilience tuning ──────────────────────────────────────────
WATCHDOG_INTERVAL_S = 45       # was 300 (5 min)
STUCK_THRESHOLD_MIN = 10       # was 5 — Phase 3's EMAIL_CRAWL_TIMEOUT is 240s (4min),
                                # so one worst-case round where every concurrent slot
                                # simultaneously hits the full cap with zero completions
                                # is itself 240s; two such rounds back-to-back (480s)
                                # needs to stay comfortably under this threshold, hence
                                # 10min not 5. This bound does NOT depend on how many
                                # concurrent slots there are (MAX_CONCURRENT_EMAIL) —
                                # only on the per-item timeout — so raising that constant
                                # doesn't require raising this one. Phase 2 detail
                                # enrichment's own worst-case gap is still only ~2.8min;
                                # Phase 1 is separately time-bounded (runner.py)
MAX_AUTO_RETRIES = 2
POOL_FAILURE_THRESHOLD = 3     # consecutive heartbeat failures before pool recreation

# Step 4 (horizontal replicas): was a hardcoded "primary" — every replica would
# have overwritten the same worker_heartbeats row every 3s, making it impossible
# to tell replicas apart or notice one specific replica dying while others stay
# healthy. RAILWAY_REPLICA_ID is a real Railway-provided env var, unique per
# replica; "local" is the fallback for local dev / a single non-replicated
# instance, where there's only ever one row anyway.
REPLICA_ID = os.environ.get("RAILWAY_REPLICA_ID", "local")
HEARTBEAT_WORKER_ID = REPLICA_ID

# job_id → user_id for currently running jobs
_running: dict[str, str] = {}
# job_id → asyncio.Task — lets the watchdog cancel a genuinely hung task before
# auto-requeuing its job, instead of racing a second coroutine against it.
_running_tasks: dict[str, asyncio.Task] = {}
_shutdown = False


class PoolHolder:
    """Mutable wrapper around the asyncpg pool so long-lived consumers (_poll_loop,
    _watchdog_loop) always see the current pool after a recreation — a plain
    reassigned local variable wouldn't propagate across those two coroutines."""

    def __init__(self, pool: asyncpg.Pool):
        self.pool = pool
        self.consecutive_failures = 0
        self.pool_recreations = 0

    async def recreate(self) -> None:
        old = self.pool
        try:
            # Forceful + synchronous, not close() — these connections are already
            # believed dead; awaiting a graceful close() on a genuinely dead pool
            # can itself hang, which is exactly the symptom that motivated this.
            old.terminate()
        except Exception:
            log.error("Error terminating stale pool", exc_info=True)
        try:
            new_pool = await asyncio.wait_for(
                asyncpg.create_pool(
                    settings.database_url,
                    # Supabase's session-mode pooler here caps at 15 total client
                    # connections, shared with app/db.py's API pool (max_size=5) — the
                    # old min=5/max=25 here (sized for a since-pulled-back
                    # MAX_GLOBAL_CONCURRENT=10 plan) could alone exceed 15, starving the
                    # API and 500ing every /auth/me and /notifications call whenever a
                    # job was actively running (2026-09-14 EMAXCONNSESSION incident).
                    min_size=3, max_size=8,
                    command_timeout=60, statement_cache_size=0, timeout=10,
                ),
                timeout=15,
            )
        except Exception:
            log.error("Pool recreation failed — will retry next cycle", exc_info=True)
            return
        self.pool = new_pool
        self.pool_recreations += 1
        self.consecutive_failures = 0
        log.warning(f"Connection pool recreated (recreation #{self.pool_recreations})")


async def _upload(content: bytes, storage_path: str) -> str:
    return await upload_csv(storage_path, content)


async def _download(storage_path: str) -> bytes | None:
    return await try_download_object(storage_path)


async def _delete(storage_path: str) -> None:
    await delete_object(storage_path)


async def _process_job(job: dict, pool: asyncpg.Pool, claim_token) -> None:
    job_id  = str(job["id"])
    user_id = str(job["user_id"])
    log.info(f"[job {job_id[:8]}] starting  [{job['industry']} / {job['state']} / {len(job['cities'])} cities]  [{len(_running)}/{MAX_GLOBAL_CONCURRENT} slots used, replica {REPLICA_ID}]")

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
            download_fn    = _download,
            delete_fn      = _delete,
            claim_token    = claim_token,
        )

        if result.get("canceled"):
            # Either a user-initiated cancel (POST /jobs/{id}/cancel), or — with
            # Step 4's multiple replicas — this replica's task was reclaimed by
            # another replica's watchdog partway through and cooperatively
            # stopped once it noticed (see runner.py's _is_job_canceled). Either
            # way run_scrape_job already left the row in the correct state; no
            # usage charge, no indexing, no "completed" notification from this
            # (possibly stale) execution.
            log.info(f"[job {job_id[:8]}] canceled or reclaimed  [{len(_running)-1}/{MAX_GLOBAL_CONCURRENT} slots used]")
        else:
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

            # ── Phase 5 hook (§27): index completed outputs into lead_files. ──
            # Isolated on purpose — an indexing failure must never fail or mark-failed
            # an already-successfully-completed job. Logged separately, never raised.
            try:
                async with pool.acquire() as conn:
                    await index_business_job_files(conn, job_id=job["id"])
            except Exception as idx_exc:
                log.error(f"[job {job_id[:8]}] lead-file indexing failed (job remains completed): {idx_exc}", exc_info=True)

            # ── Phase 6 hook (§19/§27): best-effort completion notification. ──
            try:
                async with pool.acquire() as conn:
                    await create_notification(
                        conn, user_id=job["user_id"], category="business_updates",
                        type="business_request_completed", title="Business Leads request completed",
                        body=f"Your {job['industry']} / {job['state']} request is ready — {result['total_clean']} leads found.",
                        link_section="my-leads",
                    )
            except Exception as notif_exc:
                log.error(f"[job {job_id[:8]}] completion notification failed: {notif_exc}", exc_info=True)

            log.info(f"[job {job_id[:8]}] done — {result['total_clean']} leads, {result['emails_found']} emails  [{len(_running)-1}/{MAX_GLOBAL_CONCURRENT} slots used]")

    except asyncio.CancelledError:
        # Cancelled by the watchdog because this job looked orphaned (stale
        # updated_at + still a live task). Don't touch the jobs row here — the
        # watchdog owns the reset/fail decision for whatever it just cancelled.
        log.warning(f"[job {job_id[:8]}] task cancelled (likely by watchdog)")
        raise

    except Exception as exc:
        log.error(f"[job {job_id[:8]}] failed: {exc}", exc_info=True)
        # Step 4 fencing: if another replica's watchdog already reclaimed this
        # job (reset_job_to_pending clears started_at, the new claim stamps a
        # fresh value), this task's own error is stale — the row now belongs to
        # a fresh attempt, and writing 'failed' here would stomp on it. Skip the
        # destructive write (and the failure notification) unless we still own it.
        async with pool.acquire() as conn:
            still_ours = claim_token is None or await conn.fetchval(
                "SELECT started_at = $2 FROM jobs WHERE id = $1", job["id"], claim_token,
            )
            if still_ours:
                await conn.execute(
                    "UPDATE jobs SET status='failed', error_message=$2, updated_at=NOW() WHERE id=$1",
                    job["id"], str(exc)[:500],
                )
            else:
                log.warning(f"[job {job_id[:8]}] error occurred after this task was reclaimed by "
                            f"another replica — leaving the job row alone")
        if still_ours:
            try:
                async with pool.acquire() as conn:
                    await create_notification(
                        conn, user_id=job["user_id"], category="business_updates",
                        type="business_request_failed", title="Business Leads request failed",
                        body=f"Your {job['industry']} / {job['state']} request could not be completed. Please try again or contact support.",
                        link_section="get-leads", link_sub_tab="business",
                    )
            except Exception as notif_exc:
                log.error(f"[job {job_id[:8]}] failure notification failed: {notif_exc}", exc_info=True)

    finally:
        _running.pop(job_id, None)
        _running_tasks.pop(job_id, None)
        log.info(f"[job {job_id[:8]}] slot freed — {len(_running)}/{MAX_GLOBAL_CONCURRENT} slots now used")


async def _write_heartbeat(holder: PoolHolder) -> None:
    """The single canonical DB-health probe for the poll loop. Deliberately
    separate from the job-dispatch try/except below so an unrelated bug there
    (e.g. a bad task arg) can't falsely trigger a pool recreation."""
    try:
        await holder.pool.execute(
            """
            INSERT INTO worker_heartbeats (worker_id, last_beat_at, consecutive_failures, pool_recreations, running_jobs, updated_at)
            VALUES ($1, NOW(), $2, $3, $4, NOW())
            ON CONFLICT (worker_id) DO UPDATE SET
                last_beat_at = EXCLUDED.last_beat_at,
                consecutive_failures = EXCLUDED.consecutive_failures,
                pool_recreations = EXCLUDED.pool_recreations,
                running_jobs = EXCLUDED.running_jobs,
                updated_at = NOW()
            """,
            HEARTBEAT_WORKER_ID, holder.consecutive_failures, holder.pool_recreations, len(_running),
        )
        holder.consecutive_failures = 0
    except Exception as e:
        # Cap the displayed/tracked count at the threshold once reached — recreate()
        # is retried every cycle from here (via the >= check below) until it
        # succeeds, without the log line climbing to confusing values like "11/3"
        # while Postgres is still down.
        holder.consecutive_failures = min(holder.consecutive_failures + 1, POOL_FAILURE_THRESHOLD)
        log.error(f"Heartbeat write failed ({holder.consecutive_failures}/{POOL_FAILURE_THRESHOLD}): {e}")
        if holder.consecutive_failures >= POOL_FAILURE_THRESHOLD:
            await holder.recreate()


async def _poll_loop(holder: PoolHolder) -> None:
    log.info(f"Worker polling every 3 seconds — global limit: {MAX_GLOBAL_CONCURRENT} concurrent jobs per replica (replica {REPLICA_ID})")

    while not _shutdown:
        await _write_heartbeat(holder)

        try:
            # How many slots are free?
            free_slots = MAX_GLOBAL_CONCURRENT - len(_running)

            candidates: list = []
            claim_tokens: dict = {}

            if free_slots > 0:
                # Step 4: claim atomically. FOR UPDATE SKIP LOCKED lets multiple
                # replicas poll concurrently without ever grabbing the same job —
                # a second replica's SELECT simply never sees a row this one
                # already has locked, instead of racing to claim it too. The
                # status flip to 'running' happens in the same transaction as
                # the lock, before it's released, closing the window a plain
                # SELECT-then-UPDATE would leave open for a second replica to
                # see the row as still 'pending'.
                async with holder.pool.acquire() as conn:
                    async with conn.transaction():
                        candidates = await conn.fetch(
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
                            FOR UPDATE OF j SKIP LOCKED
                            """,
                            free_slots,
                        )
                        if candidates:
                            claim_rows = await conn.fetch(
                                """
                                UPDATE jobs SET status = 'running', started_at = NOW(), updated_at = NOW()
                                WHERE id = ANY($1::uuid[])
                                RETURNING id, started_at
                                """,
                                [c["id"] for c in candidates],
                            )
                            # started_at, captured here, becomes this job's fencing
                            # token — see runner.py's _is_job_canceled for why.
                            claim_tokens = {str(r["id"]): r["started_at"] for r in claim_rows}

            for job in candidates:
                job_id = str(job["id"])

                if job_id in _running:
                    continue

                # Still within global limit?
                if len(_running) >= MAX_GLOBAL_CONCURRENT:
                    break

                _running[job_id] = str(job["user_id"])
                task = asyncio.create_task(_process_job(dict(job), holder.pool, claim_tokens[job_id]))
                _running_tasks[job_id] = task
                log.info(f"[job {job_id[:8]}] queued — {len(_running)}/{MAX_GLOBAL_CONCURRENT} slots now used (replica {REPLICA_ID})")

        except Exception as e:
            log.error(f"Poll loop error: {e}", exc_info=True)

        await asyncio.sleep(3)


async def _watchdog_loop(holder: PoolHolder) -> None:
    """
    Every 45s: find jobs stuck in 'running' with no update for 5+ minutes.
    Cancel any still-tracked in-process task for that job (it's either already
    dead or genuinely hung — either way it must not keep writing to the same
    job_id after we reset it), then auto-requeue (bounded to MAX_AUTO_RETRIES)
    or mark permanently failed with a real client notification.
    Handles power cuts, network drops, OOM crashes, and DB outages that orphan
    a job mid-run — all without any human needing to notice or act.

    Step 4: every replica runs this same loop independently. The stuck-job
    query below uses FOR UPDATE SKIP LOCKED so if two replicas' watchdogs fire
    at nearly the same moment and both see the same stale row, only one of
    them actually locks and processes it — the other's query simply doesn't
    see it, no leader election needed. task.cancel() below can only ever stop
    a task THIS replica is tracking; if the stuck job actually belongs to a
    different (possibly still-alive, just slow) replica, this watchdog can't
    reach it directly — but reset_job_to_pending()'s started_at bump acts as a
    fencing token that job's real owner will notice on its own next per-item
    check (see runner.py's _is_job_canceled) and stop cooperatively.
    """
    log.info(f"Watchdog started — checks every {WATCHDOG_INTERVAL_S}s for jobs stuck >{STUCK_THRESHOLD_MIN}min (replica {REPLICA_ID})")
    while not _shutdown:
        await asyncio.sleep(WATCHDOG_INTERVAL_S)
        try:
            async with holder.pool.acquire() as conn:
                async with conn.transaction():
                    stuck = await conn.fetch(
                        """
                        SELECT id, user_id, industry, state, retry_count
                        FROM jobs
                        WHERE status = 'running'
                          AND updated_at < NOW() - make_interval(mins => $1)
                        FOR UPDATE SKIP LOCKED
                        """,
                        STUCK_THRESHOLD_MIN,
                    )
                    for row in stuck:
                        job_id = str(row["id"])

                        task = _running_tasks.get(job_id)
                        if task and not task.done():
                            task.cancel()
                            log.warning(f"[job {job_id[:8]}] watchdog cancelled in-process hung task")
                        _running.pop(job_id, None)
                        _running_tasks.pop(job_id, None)

                        if row["retry_count"] < MAX_AUTO_RETRIES:
                            await reset_job_to_pending(conn, row["id"], bump_retry_count=True)
                            log.warning(
                                f"[job {job_id[:8]}] watchdog auto-requeued "
                                f"[{row['industry']} / {row['state']}] (attempt {row['retry_count'] + 1}/{MAX_AUTO_RETRIES}, replica {REPLICA_ID})"
                            )
                        else:
                            await conn.execute(
                                "UPDATE jobs SET status='failed', error_message=$2, updated_at=NOW() WHERE id=$1",
                                row["id"],
                                f"Job stalled and could not be automatically recovered after {MAX_AUTO_RETRIES} attempts. Please try again or contact support.",
                            )
                            try:
                                await create_notification(
                                    conn, user_id=row["user_id"], category="business_updates",
                                    type="business_request_failed", title="Business Leads request failed",
                                    body=f"Your {row['industry']} / {row['state']} request could not be completed. Please try again or contact support.",
                                    link_section="get-leads", link_sub_tab="business",
                                )
                            except Exception as notif_exc:
                                log.error(f"[job {job_id[:8]}] failure notification failed: {notif_exc}", exc_info=True)
                            log.warning(f"[job {job_id[:8]}] watchdog permanently failed [{row['industry']} / {row['state']}] — auto-retry budget exhausted")
        except Exception as e:
            log.error(f"Watchdog error: {e}", exc_info=True)


async def main() -> None:
    log.info(f"Intelligent Scraper Worker starting… (replica {REPLICA_ID})")
    log.info(f"Global concurrent job limit: {MAX_GLOBAL_CONCURRENT} per replica")

    pool = await asyncpg.create_pool(
        settings.database_url,
        # Must match PoolHolder.recreate()'s sizing above.
        # Step 4 (horizontal replicas): this budget is PER REPLICA, and every
        # replica plus the API service share Supabase's pooler connection cap.
        # Before running more than 1 replica, confirm the pooler's pool_size
        # setting (Database Settings, currently 15 on our project — see
        # PERFORMANCE_BASELINE.md) has been raised to comfortably fit
        # N x max_size (this) + the API's own max_size — e.g. 3 replicas x 8
        # + API's 5 = 29, which needs pool_size raised well past today's 15
        # even though the underlying free-tier hard cap is 60.
        min_size=3,
        max_size=8,
        command_timeout=60,
        statement_cache_size=0,
    )
    holder = PoolHolder(pool)

    # One-time "boot" heartbeat — started_at only ever changes on an actual process
    # restart, giving a clean answer to "did the worker restart?" independent of the
    # recurring last_beat_at writes in _poll_loop.
    await holder.pool.execute(
        """
        INSERT INTO worker_heartbeats (worker_id, started_at, last_beat_at, consecutive_failures, pool_recreations, running_jobs, updated_at)
        VALUES ($1, NOW(), NOW(), 0, 0, 0, NOW())
        ON CONFLICT (worker_id) DO UPDATE SET
            started_at = EXCLUDED.started_at,
            last_beat_at = EXCLUDED.last_beat_at,
            consecutive_failures = 0,
            updated_at = NOW()
        """,
        HEARTBEAT_WORKER_ID,
    )

    loop = asyncio.get_running_loop()

    def _handle_signal():
        global _shutdown
        _shutdown = True
        log.info("Shutdown signal — finishing current jobs then exiting…")

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _handle_signal)
        except NotImplementedError:
            pass

    # Run poll loop + watchdog concurrently
    await asyncio.gather(
        _poll_loop(holder),
        _watchdog_loop(holder),
    )
    await holder.pool.close()
    log.info("Worker stopped.")


if __name__ == "__main__":
    asyncio.run(main())
