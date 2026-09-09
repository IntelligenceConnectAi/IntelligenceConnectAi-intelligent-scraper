-- Phase 4 — People Leads
--
-- Run manually against Supabase (SQL editor) BEFORE deploying the backend code that
-- depends on it. Safe to re-run: every statement is IF NOT EXISTS guarded.
--
-- No backfill needed here — every user already has exactly one organization from the
-- Phase 1 migration + app/routers/register.py's signup hook.

BEGIN;

CREATE TABLE IF NOT EXISTS people_lead_requests (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id uuid NOT NULL REFERENCES organizations(id),
  requested_by uuid NOT NULL REFERENCES users(id),
  request_name text NOT NULL,
  lead_type text NOT NULL CHECK (lead_type IN
    ('property_owners','absentee_owners','vacant_property_owners',
     'high_equity_homeowners','landowners','other')),
  state text NOT NULL,
  city text,
  county text,
  zip_codes text[] NOT NULL DEFAULT '{}',
  requested_quantity integer NOT NULL CHECK (requested_quantity > 0),
  delivered_quantity integer NOT NULL DEFAULT 0,
  targeting_filters_json jsonb NOT NULL DEFAULT '{}'::jsonb,
  client_instructions text,
  client_status text NOT NULL DEFAULT 'Submitted' CHECK
    (client_status IN ('Submitted','Processing','Needs Information','Completed','Cancelled')),
  internal_status text NOT NULL DEFAULT 'new' CHECK (internal_status IN
    ('new','assigned','collecting_data','cleaning_data','awaiting_upload',
     'uploaded','quality_review','revision_required','approved','delivered','cancelled')),
  assigned_admin_id uuid REFERENCES users(id),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  completed_at timestamptz,
  cancelled_at timestamptz
);
CREATE INDEX IF NOT EXISTS people_lead_requests_org_idx ON people_lead_requests(organization_id);
CREATE INDEX IF NOT EXISTS people_lead_requests_requested_by_idx ON people_lead_requests(requested_by);
CREATE INDEX IF NOT EXISTS people_lead_requests_assigned_admin_idx ON people_lead_requests(assigned_admin_id);
CREATE INDEX IF NOT EXISTS people_lead_requests_internal_status_idx ON people_lead_requests(internal_status);
CREATE INDEX IF NOT EXISTS people_lead_requests_created_at_idx ON people_lead_requests(created_at DESC);

CREATE TABLE IF NOT EXISTS people_lead_files (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  request_id uuid NOT NULL REFERENCES people_lead_requests(id),
  organization_id uuid NOT NULL REFERENCES organizations(id),
  storage_path text NOT NULL,
  original_filename text NOT NULL,
  display_name text,
  file_type text NOT NULL CHECK (file_type IN ('csv','xlsx')),
  file_size integer NOT NULL,
  total_rows integer NOT NULL DEFAULT 0,
  accepted_rows integer NOT NULL DEFAULT 0,
  rejected_rows integer NOT NULL DEFAULT 0,
  duplicate_rows integer NOT NULL DEFAULT 0,
  email_count integer NOT NULL DEFAULT 0,
  phone_count integer NOT NULL DEFAULT 0,
  uploaded_by uuid NOT NULL REFERENCES users(id),
  approved_by uuid REFERENCES users(id),
  delivered_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS people_lead_files_request_idx ON people_lead_files(request_id);
CREATE INDEX IF NOT EXISTS people_lead_files_org_idx ON people_lead_files(organization_id);

ALTER TABLE people_lead_requests ENABLE ROW LEVEL SECURITY;
ALTER TABLE people_lead_files ENABLE ROW LEVEL SECURITY;

COMMIT;
