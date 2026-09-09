-- Two more findings from Supabase's security advisor after 0010:
--
-- 1. security_definer_view (ERROR): user_current_plan / user_today_usage were
--    created as plain views, which Postgres treats with definer-like row
--    visibility by default — querying them directly via the anon/authenticated
--    PostgREST role would bypass the RLS just enabled on users/subscriptions/
--    plans in 0010. Setting security_invoker=on makes them run as the querying
--    role instead. Confirmed safe: the frontend never queries these views
--    (grepped, zero matches) and the backend's own usage (app/routers/usage.py)
--    goes through the direct-Postgres/service-role connection, which bypasses
--    RLS regardless of this setting — no functional change for the backend.
--
-- 2. function_search_path_mutable (WARN): can_user_scrape / update_usage_after_job
--    had no fixed search_path — standard hardening against search_path
--    hijacking, zero behavior change (both already fully-qualify nothing outside
--    public, so pinning search_path to public is a no-op for their own logic).

BEGIN;

ALTER VIEW user_current_plan SET (security_invoker = on);
ALTER VIEW user_today_usage SET (security_invoker = on);

ALTER FUNCTION can_user_scrape(uuid, integer) SET search_path = public;
ALTER FUNCTION update_usage_after_job(uuid, integer, integer, integer, integer, integer) SET search_path = public;

COMMIT;
