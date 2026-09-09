-- Phase 6 — Settings (Team, Notifications, Billing expansion, Integrations)
--
-- Run manually against Supabase (SQL editor) BEFORE deploying the backend code that
-- depends on it. Safe to re-run: every statement is IF NOT EXISTS / ON CONFLICT guarded.
--
-- Adds: team-seat limits on plans, notifications + preferences, integration interest.
-- organization_invitations already exists (Phase 1) — this migration only indexes it
-- for the first real invite-flow usage.

BEGIN;

-- ── Team seat limits (additive column on plans, Phase 1's precedent) ──
ALTER TABLE plans ADD COLUMN IF NOT EXISTS max_team_seats integer;
UPDATE plans SET max_team_seats = 3  WHERE id = 'starter' AND max_team_seats IS NULL;
UPDATE plans SET max_team_seats = 10 WHERE id = 'pro'     AND max_team_seats IS NULL;
UPDATE plans SET max_team_seats = 25 WHERE id = 'elite'   AND max_team_seats IS NULL;
-- enterprise stays NULL = unlimited seats

-- ── Invitations: index for the first real invite-flow lookups ──
CREATE INDEX IF NOT EXISTS organization_invitations_token_hash_idx ON organization_invitations(token_hash);
CREATE INDEX IF NOT EXISTS organization_invitations_org_status_idx ON organization_invitations(organization_id, status);

-- ── Notifications ──
CREATE TABLE IF NOT EXISTS notifications (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES users(id),
  category text NOT NULL CHECK (category IN
    ('business_updates','people_updates','billing_limits','team','support')),
  type text NOT NULL CHECK (type IN (
    'business_request_submitted','business_request_completed',
    'business_request_failed','business_request_cancelled',
    'people_request_submitted','people_request_needs_info','people_request_completed',
    'monthly_limit_warning','daily_limit_warning',
    'subscription_renewal','payment_failure',
    'team_invitation','support_response','file_delivered'
  )),
  title text NOT NULL,
  body text NOT NULL,
  link_section text,
  link_sub_tab text,
  link_resource_id text,
  is_read boolean NOT NULL DEFAULT false,
  created_at timestamptz NOT NULL DEFAULT now(),
  read_at timestamptz
);
CREATE INDEX IF NOT EXISTS notifications_user_unread_idx ON notifications(user_id, is_read, created_at DESC);

CREATE TABLE IF NOT EXISTS notification_preferences (
  user_id uuid PRIMARY KEY REFERENCES users(id),
  muted_categories text[] NOT NULL DEFAULT '{}',
  updated_at timestamptz NOT NULL DEFAULT now()
);

-- ── Integration interest (Notify Me) ──
CREATE TABLE IF NOT EXISTS integration_interest (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id uuid NOT NULL REFERENCES organizations(id),
  user_id uuid NOT NULL REFERENCES users(id),
  integration_key text NOT NULL CHECK (integration_key IN
    ('gohighlevel','hubspot','salesforce','pipedrive','zoho_crm',
     'google_sheets','zapier','make','webhooks')),
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (user_id, integration_key)
);
CREATE INDEX IF NOT EXISTS integration_interest_org_idx ON integration_interest(organization_id);

-- ── RLS: deny-all by default on new tables (service role bypasses, same posture as existing tables) ──
ALTER TABLE notifications ENABLE ROW LEVEL SECURITY;
ALTER TABLE notification_preferences ENABLE ROW LEVEL SECURITY;
ALTER TABLE integration_interest ENABLE ROW LEVEL SECURITY;

COMMIT;
