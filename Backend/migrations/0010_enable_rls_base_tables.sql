-- Enable RLS on the 7 base-schema tables that were missed when 0000 was written.
--
-- Every table added from 0001 onward already follows a "deny-all RLS, service-role
-- bypasses" posture (see their own comments). These 7 — users, plans, subscriptions,
-- pending_signups, jobs, job_cities, daily_usage — are the base-schema exception:
-- RLS was never enabled on them, which leaves them fully readable/writable by anyone
-- holding just the public anon key (via Supabase's PostgREST/client-SDK path),
-- bypassing the FastAPI backend's own authorization entirely.
--
-- Confirmed safe to enable with no policies (deny-all for anon/authenticated):
-- the frontend's Supabase JS SDK is used for auth/session only — it never queries
-- any of these tables directly (grepped, zero matches). All real data access goes
-- through the FastAPI backend via the service-role key / direct Postgres connection,
-- which bypasses RLS entirely and is therefore unaffected by this change.
--
-- Flagged by Supabase's own security advisor (critical/rls_disabled) when this
-- schema was first stood up on a fresh project (2026-09).

BEGIN;

ALTER TABLE users ENABLE ROW LEVEL SECURITY;
ALTER TABLE plans ENABLE ROW LEVEL SECURITY;
ALTER TABLE subscriptions ENABLE ROW LEVEL SECURITY;
ALTER TABLE pending_signups ENABLE ROW LEVEL SECURITY;
ALTER TABLE jobs ENABLE ROW LEVEL SECURITY;
ALTER TABLE job_cities ENABLE ROW LEVEL SECURITY;
ALTER TABLE daily_usage ENABLE ROW LEVEL SECURITY;

COMMIT;
