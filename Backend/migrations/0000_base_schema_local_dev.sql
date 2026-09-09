-- Base application schema — LOCAL DEV RECONSTRUCTION ONLY.
--
-- This is NOT a copy of the real production schema (which lives only in Supabase
-- and has no migration files anywhere in this repo). It's a best-effort reconstruction
-- built from every SQL query found across app/ and worker/, good enough to run the full
-- app (signup, jobs, usage, billing, admin) against an isolated local Supabase stack for
-- development/testing. Never run this against the real production database — it would
-- conflict with (and is unnecessary alongside) the tables that already exist there.

BEGIN;

CREATE TABLE IF NOT EXISTS users (
  id uuid PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
  email text NOT NULL,
  full_name text,
  is_admin boolean NOT NULL DEFAULT false,
  is_active boolean NOT NULL DEFAULT true,
  stripe_customer_id text,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS plans (
  id text PRIMARY KEY,
  name text NOT NULL,
  price_monthly numeric NOT NULL,
  leads_per_month integer NOT NULL,
  leads_per_day integer NOT NULL,
  cities_per_job integer NOT NULL,
  keywords_per_job integer NOT NULL DEFAULT 1,
  history_days integer NOT NULL,
  concurrent_jobs integer NOT NULL,
  email_scraping boolean NOT NULL DEFAULT false,
  api_access boolean NOT NULL DEFAULT false,
  is_active boolean NOT NULL DEFAULT true
);

CREATE TABLE IF NOT EXISTS subscriptions (
  user_id uuid PRIMARY KEY REFERENCES users(id),
  plan_id text NOT NULL REFERENCES plans(id),
  status text NOT NULL DEFAULT 'active',
  stripe_subscription_id text,
  stripe_customer_id text,
  current_period_end timestamptz,
  cancel_at_period_end boolean NOT NULL DEFAULT false,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS pending_signups (
  email text PRIMARY KEY,
  stripe_customer_id text,
  stripe_subscription_id text,
  plan_id text REFERENCES plans(id),
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS jobs (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES users(id),
  industry text NOT NULL,
  state text NOT NULL,
  cities text[] NOT NULL,
  status text NOT NULL DEFAULT 'pending',
  current_step text,
  current_city text,
  cities_done integer NOT NULL DEFAULT 0,
  cities_total integer NOT NULL DEFAULT 0,
  total_raw integer NOT NULL DEFAULT 0,
  total_clean integer NOT NULL DEFAULT 0,
  with_website integer NOT NULL DEFAULT 0,
  no_website integer NOT NULL DEFAULT 0,
  emails_found integer NOT NULL DEFAULT 0,
  emails_attempted integer NOT NULL DEFAULT 0,
  duplicates_removed integer NOT NULL DEFAULT 0,
  with_web_csv text,
  no_web_csv text,
  error_message text,
  created_at timestamptz NOT NULL DEFAULT now(),
  started_at timestamptz,
  maps_done_at timestamptz,
  emails_started_at timestamptz,
  emails_done_at timestamptz,
  completed_at timestamptz,
  updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS jobs_user_id_idx ON jobs(user_id);

CREATE TABLE IF NOT EXISTS job_cities (
  id bigserial PRIMARY KEY,
  job_id uuid NOT NULL REFERENCES jobs(id),
  city text NOT NULL,
  maps_status text NOT NULL DEFAULT 'pending',
  maps_leads integer DEFAULT 0,
  status text NOT NULL DEFAULT 'pending',
  maps_started_at timestamptz,
  maps_done_at timestamptz,
  error text
);
CREATE INDEX IF NOT EXISTS job_cities_job_id_idx ON job_cities(job_id);

-- ── Daily usage tracking (backs the two views below + can_user_scrape) ──
CREATE TABLE IF NOT EXISTS daily_usage (
  user_id uuid NOT NULL REFERENCES users(id),
  usage_date date NOT NULL DEFAULT CURRENT_DATE,
  leads_used integer NOT NULL DEFAULT 0,
  leads_with_web integer NOT NULL DEFAULT 0,
  leads_no_web integer NOT NULL DEFAULT 0,
  emails_found integer NOT NULL DEFAULT 0,
  jobs_run integer NOT NULL DEFAULT 0,
  PRIMARY KEY (user_id, usage_date)
);

CREATE OR REPLACE VIEW user_current_plan AS
SELECT
  u.id AS user_id,
  u.email,
  p.id AS plan_id,
  p.name AS plan_name,
  p.price_monthly,
  p.leads_per_day AS daily_limit,
  p.leads_per_month AS monthly_limit,
  p.cities_per_job,
  p.concurrent_jobs,
  p.email_scraping,
  p.api_access,
  s.status AS subscription_status,
  s.current_period_end,
  s.cancel_at_period_end
FROM users u
LEFT JOIN subscriptions s ON s.user_id = u.id AND s.status = 'active'
LEFT JOIN plans p ON p.id = s.plan_id;

CREATE OR REPLACE VIEW user_today_usage AS
SELECT
  u.id AS user_id,
  u.email,
  p.leads_per_day AS daily_limit,
  COALESCE(d.leads_used, 0) AS leads_used_today,
  COALESCE(d.leads_with_web, 0) AS leads_with_web_today,
  COALESCE(d.leads_no_web, 0) AS leads_no_web_today,
  COALESCE(d.emails_found, 0) AS emails_found_today,
  COALESCE(d.jobs_run, 0) AS jobs_run_today,
  GREATEST(COALESCE(p.leads_per_day, 0) - COALESCE(d.leads_used, 0), 0) AS leads_remaining
FROM users u
LEFT JOIN subscriptions s ON s.user_id = u.id AND s.status = 'active'
LEFT JOIN plans p ON p.id = s.plan_id
LEFT JOIN daily_usage d ON d.user_id = u.id AND d.usage_date = CURRENT_DATE;

CREATE OR REPLACE FUNCTION can_user_scrape(p_user_id uuid, p_estimated_leads integer)
RETURNS TABLE(allowed boolean, reason text) AS $$
DECLARE
  v_daily_limit integer;
  v_used_today integer;
BEGIN
  SELECT p.leads_per_day INTO v_daily_limit
  FROM subscriptions s JOIN plans p ON p.id = s.plan_id
  WHERE s.user_id = p_user_id AND s.status = 'active';

  IF v_daily_limit IS NULL THEN
    RETURN QUERY SELECT false, 'No active subscription';
    RETURN;
  END IF;

  SELECT COALESCE(leads_used, 0) INTO v_used_today
  FROM daily_usage WHERE user_id = p_user_id AND usage_date = CURRENT_DATE;

  IF COALESCE(v_used_today, 0) + p_estimated_leads > v_daily_limit THEN
    RETURN QUERY SELECT false, 'This request would exceed your daily lead limit';
    RETURN;
  END IF;

  RETURN QUERY SELECT true, NULL::text;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION update_usage_after_job(
  p_user_id uuid,
  p_total_clean integer,
  p_with_website integer,
  p_no_website integer,
  p_emails_found integer,
  p_leads_used integer
) RETURNS void AS $$
BEGIN
  INSERT INTO daily_usage (user_id, usage_date, leads_used, leads_with_web, leads_no_web, emails_found, jobs_run)
  VALUES (p_user_id, CURRENT_DATE, p_leads_used, p_with_website, p_no_website, p_emails_found, 1)
  ON CONFLICT (user_id, usage_date) DO UPDATE SET
    leads_used     = daily_usage.leads_used + EXCLUDED.leads_used,
    leads_with_web = daily_usage.leads_with_web + EXCLUDED.leads_with_web,
    leads_no_web   = daily_usage.leads_no_web + EXCLUDED.leads_no_web,
    emails_found   = daily_usage.emails_found + EXCLUDED.emails_found,
    jobs_run       = daily_usage.jobs_run + 1;
END;
$$ LANGUAGE plpgsql;

-- ── Seed plans matching production's current values (from GET /plans) ──
INSERT INTO plans (id, name, price_monthly, leads_per_month, leads_per_day, cities_per_job, keywords_per_job, history_days, concurrent_jobs, email_scraping, api_access, is_active)
VALUES
  ('starter', 'Starter', 49.00, 5000, 167, 10, 1, 7, 10, false, false, true),
  ('pro', 'Pro', 197.00, 40000, 1333, 30, 3, 30, 10, true, false, true),
  ('elite', 'Elite', 397.00, 100000, 3333, 100, 5, 365, 10, true, false, true),
  ('enterprise', 'Enterprise', 1500.00, 250000, 8333, 999, 10, 365, 25, true, true, true)
ON CONFLICT (id) DO NOTHING;

COMMIT;
