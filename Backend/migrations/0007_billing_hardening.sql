-- Billing hardening: webhook idempotency ledger + two new refund/dispute
-- notification types for a GHL-linked Stripe Checkout launch. See KNOWLEDGE.md /
-- the billing-hardening plan for the full rationale.

BEGIN;

-- notifications.type's CHECK constraint (0004_phase6_settings.sql) predates the
-- refund/dispute auto-suspend webhook handlers — widen it to include the two new
-- types they write. DROP+ADD is the standard idempotent way to alter a CHECK
-- constraint; safe to re-run (dropping a constraint that's already been widened
-- and re-adding the same definition is a no-op).
ALTER TABLE notifications DROP CONSTRAINT IF EXISTS notifications_type_check;
ALTER TABLE notifications ADD CONSTRAINT notifications_type_check CHECK (type IN (
  'business_request_submitted','business_request_completed',
  'business_request_failed','business_request_cancelled',
  'people_request_submitted','people_request_needs_info','people_request_completed',
  'monthly_limit_warning','daily_limit_warning',
  'subscription_renewal','payment_failure',
  'team_invitation','support_response','file_delivered',
  'refund_processed','payment_disputed'
));

CREATE TABLE IF NOT EXISTS stripe_events (
  id text PRIMARY KEY,           -- Stripe's own event id (evt_...) — natural idempotency key
  type text NOT NULL,
  payload jsonb NOT NULL,
  status text NOT NULL DEFAULT 'processing' CHECK (status IN ('processing','processed','failed')),
  error_message text,
  created_at timestamptz NOT NULL DEFAULT now(),
  processed_at timestamptz
);

CREATE INDEX IF NOT EXISTS stripe_events_type_idx ON stripe_events(type);
CREATE INDEX IF NOT EXISTS stripe_events_created_at_idx ON stripe_events(created_at DESC);

ALTER TABLE stripe_events ENABLE ROW LEVEL SECURITY;

COMMIT;
