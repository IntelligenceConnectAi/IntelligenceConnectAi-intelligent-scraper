-- Worker Resilience — heartbeat, fast auto-recovery, bounded retries
--
-- Run manually against Supabase (SQL editor) BEFORE deploying the backend code that
-- depends on it. Safe to re-run: every statement is IF NOT EXISTS guarded.
--
-- worker_heartbeats: single fixed row (worker_id='primary') — this app's concurrency
-- model (MAX_GLOBAL_CONCURRENT, the module-level _running dict in worker/main.py) is
-- already process-local/single-instance, never designed for horizontal worker
-- replicas, so one row accurately reflects reality and avoids unbounded growth
-- across Railway restarts.
--
-- jobs.retry_count: bounded auto-retry counter for the tightened watchdog. Shared
-- between the watchdog's auto-requeue (bumps it) and the existing manual admin retry
-- endpoint (resets it to 0 — a human explicitly asking for a fresh attempt shouldn't
-- inherit an exhausted auto-retry budget).

BEGIN;

CREATE TABLE IF NOT EXISTS worker_heartbeats (
  worker_id text PRIMARY KEY,
  started_at timestamptz NOT NULL DEFAULT now(),
  last_beat_at timestamptz NOT NULL DEFAULT now(),
  consecutive_failures integer NOT NULL DEFAULT 0,
  pool_recreations integer NOT NULL DEFAULT 0,
  running_jobs integer NOT NULL DEFAULT 0,
  updated_at timestamptz NOT NULL DEFAULT now()
);

ALTER TABLE jobs ADD COLUMN IF NOT EXISTS retry_count integer NOT NULL DEFAULT 0;

-- The stuck-job watchdog query now runs every 45s (was 5min) — a partial index
-- keeps it cheap at the new frequency. jobs has no index covering this today.
CREATE INDEX IF NOT EXISTS jobs_running_updated_at_idx ON jobs(updated_at) WHERE status = 'running';

ALTER TABLE worker_heartbeats ENABLE ROW LEVEL SECURITY;

COMMIT;
