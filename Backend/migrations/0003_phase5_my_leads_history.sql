-- Phase 5 — My Leads & History unified file index
-- Run manually against Supabase (SQL editor) BEFORE deploying backend code that
-- depends on it. Safe to re-run: every statement is IF NOT EXISTS / ON CONFLICT guarded.

BEGIN;

CREATE TABLE IF NOT EXISTS lead_files (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id uuid NOT NULL REFERENCES organizations(id),
  user_id uuid NOT NULL REFERENCES users(id),
  source_type text NOT NULL CHECK (source_type IN ('business', 'people')),
  source_id uuid NOT NULL,                 -- jobs.id (business) or people_lead_requests.id (people)
  file_category text NOT NULL CHECK (file_category IN
    ('business_with_website', 'business_no_website', 'people_leads')),
  display_name text NOT NULL,              -- user-renamable (§13.3's single writable action)
  storage_path text NOT NULL,
  file_type text NOT NULL DEFAULT 'csv' CHECK (file_type IN ('csv', 'xlsx')),
  file_size integer,                       -- nullable: best-effort, see app/leads_index.py notes
  record_count integer NOT NULL DEFAULT 0,
  website_count integer NOT NULL DEFAULT 0,
  email_count integer NOT NULL DEFAULT 0,
  state text,
  city text,
  industry_or_category text,               -- jobs.industry OR people_lead_requests.lead_type
  created_at timestamptz NOT NULL DEFAULT now(),
  download_count integer NOT NULL DEFAULT 0,
  last_downloaded_at timestamptz,
  UNIQUE (source_type, source_id, file_category)   -- idempotency for hook + backfill
);

CREATE INDEX IF NOT EXISTS lead_files_org_created_idx ON lead_files(organization_id, created_at DESC);
CREATE INDEX IF NOT EXISTS lead_files_org_source_idx  ON lead_files(organization_id, source_type);
CREATE INDEX IF NOT EXISTS lead_files_user_idx        ON lead_files(user_id);

ALTER TABLE lead_files ENABLE ROW LEVEL SECURITY;   -- deny-all posture, matches 0001/0002

-- ── Backfill: index existing completed business job outputs ──────────────────
-- Both with_web_csv and no_web_csv are ALWAYS non-null on a status='done' job
-- (runner.py uploads both unconditionally) — the only gate needed is record_count > 0,
-- so a job with zero with-website leads correctly gets 1 row, not 2 with an empty one.
INSERT INTO lead_files (
  organization_id, user_id, source_type, source_id, file_category,
  display_name, storage_path, file_type, file_size,
  record_count, website_count, email_count, state, industry_or_category, created_at
)
SELECT
  om.organization_id, j.user_id, 'business', j.id, 'business_with_website',
  j.industry || ' — ' || j.state || ' (With Website)',
  j.with_web_csv, 'csv', NULL,
  j.with_website, j.with_website, j.emails_found,
  j.state, j.industry, COALESCE(j.completed_at, j.created_at)
FROM jobs j
JOIN LATERAL (
  SELECT organization_id FROM organization_members
  WHERE user_id = j.user_id AND is_active = true
  ORDER BY created_at ASC LIMIT 1
) om ON true
WHERE j.status = 'done' AND j.with_web_csv IS NOT NULL AND j.with_website > 0
ON CONFLICT (source_type, source_id, file_category) DO NOTHING;

INSERT INTO lead_files (
  organization_id, user_id, source_type, source_id, file_category,
  display_name, storage_path, file_type, file_size,
  record_count, website_count, email_count, state, industry_or_category, created_at
)
SELECT
  om.organization_id, j.user_id, 'business', j.id, 'business_no_website',
  j.industry || ' — ' || j.state || ' (No Website)',
  j.no_web_csv, 'csv', NULL,
  j.no_website, 0, 0,
  j.state, j.industry, COALESCE(j.completed_at, j.created_at)
FROM jobs j
JOIN LATERAL (
  SELECT organization_id FROM organization_members
  WHERE user_id = j.user_id AND is_active = true
  ORDER BY created_at ASC LIMIT 1
) om ON true
WHERE j.status = 'done' AND j.no_web_csv IS NOT NULL AND j.no_website > 0
ON CONFLICT (source_type, source_id, file_category) DO NOTHING;

-- ── Backfill: index already-delivered People Leads files ─────────────────────
INSERT INTO lead_files (
  organization_id, user_id, source_type, source_id, file_category,
  display_name, storage_path, file_type, file_size,
  record_count, website_count, email_count, state, city, industry_or_category, created_at
)
SELECT
  plr.organization_id, plr.requested_by, 'people', plr.id, 'people_leads',
  plr.request_name, plf.storage_path, plf.file_type, plf.file_size,
  plr.delivered_quantity, 0, plf.email_count,
  plr.state, plr.city, plr.lead_type, plr.completed_at
FROM people_lead_requests plr
JOIN LATERAL (
  SELECT * FROM people_lead_files WHERE request_id = plr.id ORDER BY created_at DESC LIMIT 1
) plf ON true
WHERE plr.internal_status = 'delivered' AND plr.delivered_quantity > 0
ON CONFLICT (source_type, source_id, file_category) DO NOTHING;

COMMIT;
