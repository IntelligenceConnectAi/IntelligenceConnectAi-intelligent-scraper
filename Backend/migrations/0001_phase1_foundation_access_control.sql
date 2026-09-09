-- Phase 1 — Foundation and Access Control
--
-- Run manually against Supabase (SQL editor) BEFORE deploying the backend code that
-- depends on it. Safe to re-run: every statement is IF NOT EXISTS / ON CONFLICT guarded.
--
-- Adds: platform roles, admin permission groups, organizations + membership scaffolding,
-- audit logs, and additive "package" columns on the existing plans table. Does not modify
-- or remove any existing column, table, view, or function.

BEGIN;

-- ── Platform role on users (is_admin stays untouched, deprecated later) ──
ALTER TABLE users ADD COLUMN IF NOT EXISTS platform_role text NOT NULL DEFAULT 'client'
  CHECK (platform_role IN ('super_admin','admin','client'));
UPDATE users SET platform_role = 'admin' WHERE is_admin = true AND platform_role = 'client';

-- ── Admin permission groups ──
CREATE TABLE IF NOT EXISTS admin_permissions (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  admin_user_id uuid NOT NULL REFERENCES users(id),
  permission_key text NOT NULL CHECK (permission_key IN
    ('operations_admin','people_leads_admin','support_admin','billing_admin')),
  granted_by uuid REFERENCES users(id),
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (admin_user_id, permission_key)
);
CREATE INDEX IF NOT EXISTS admin_permissions_admin_user_id_idx ON admin_permissions(admin_user_id);

-- ── Organizations / teams ──
CREATE TABLE IF NOT EXISTS organizations (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  name text NOT NULL,
  owner_user_id uuid NOT NULL REFERENCES users(id),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (owner_user_id)
);

CREATE TABLE IF NOT EXISTS organization_members (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id uuid NOT NULL REFERENCES organizations(id),
  user_id uuid NOT NULL REFERENCES users(id),
  role text NOT NULL CHECK (role IN ('account_owner','client_admin','client_member')),
  is_active boolean NOT NULL DEFAULT true,
  invited_by uuid REFERENCES users(id),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (organization_id, user_id)
);
CREATE INDEX IF NOT EXISTS organization_members_user_id_idx ON organization_members(user_id);
CREATE INDEX IF NOT EXISTS organization_members_org_id_idx ON organization_members(organization_id);

-- Schema only in Phase 1 — invite API/UI is a later phase (Team settings)
CREATE TABLE IF NOT EXISTS organization_invitations (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id uuid NOT NULL REFERENCES organizations(id),
  email text NOT NULL,
  role text NOT NULL CHECK (role IN ('client_admin','client_member')),
  token_hash text NOT NULL,
  status text NOT NULL DEFAULT 'pending',
  invited_by uuid REFERENCES users(id),
  expires_at timestamptz NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  accepted_at timestamptz
);

-- ── Audit logs ──
CREATE TABLE IF NOT EXISTS audit_logs (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  actor_user_id uuid REFERENCES users(id),
  actor_role text,
  action text NOT NULL,
  resource_type text,
  resource_id text,
  previous_value_json jsonb,
  new_value_json jsonb,
  ip_address text,
  user_agent text,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS audit_logs_actor_user_id_idx ON audit_logs(actor_user_id);
CREATE INDEX IF NOT EXISTS audit_logs_resource_idx ON audit_logs(resource_type, resource_id);
CREATE INDEX IF NOT EXISTS audit_logs_created_at_idx ON audit_logs(created_at DESC);

-- ── Idempotent backfill: give every existing user their own org they own ──
INSERT INTO organizations (name, owner_user_id)
SELECT COALESCE(NULLIF(u.full_name, ''), split_part(u.email, '@', 1)) || '''s Organization', u.id
FROM users u
ON CONFLICT (owner_user_id) DO NOTHING;

INSERT INTO organization_members (organization_id, user_id, role, is_active)
SELECT o.id, o.owner_user_id, 'account_owner', true
FROM organizations o
ON CONFLICT (organization_id, user_id) DO NOTHING;

-- ── RLS: deny-all by default on new tables (service role bypasses, same posture as existing tables) ──
ALTER TABLE admin_permissions ENABLE ROW LEVEL SECURITY;
ALTER TABLE organizations ENABLE ROW LEVEL SECURITY;
ALTER TABLE organization_members ENABLE ROW LEVEL SECURITY;
ALTER TABLE organization_invitations ENABLE ROW LEVEL SECURITY;
ALTER TABLE audit_logs ENABLE ROW LEVEL SECURITY;

-- ── Packages groundwork: additive columns on plans, nothing reads them yet ──
ALTER TABLE plans ADD COLUMN IF NOT EXISTS status text NOT NULL DEFAULT 'active'
  CHECK (status IN ('active','inactive','archived','hidden'));
ALTER TABLE plans ADD COLUMN IF NOT EXISTS annual_price numeric;
ALTER TABLE plans ADD COLUMN IF NOT EXISTS stripe_annual_price_id text;
ALTER TABLE plans ADD COLUMN IF NOT EXISTS display_order integer;
ALTER TABLE plans ADD COLUMN IF NOT EXISTS version integer NOT NULL DEFAULT 1;
ALTER TABLE plans ADD COLUMN IF NOT EXISTS parent_package_id text REFERENCES plans(id);
ALTER TABLE plans ADD COLUMN IF NOT EXISTS is_enterprise boolean NOT NULL DEFAULT false;

COMMIT;

-- ── Manual, one-time, NOT run automatically ──
-- After this script has been run, promote the first Super Admin by hand:
--   UPDATE users SET platform_role = 'super_admin' WHERE email = 'support@intelligenceconnectai.com';
