-- Additional-records billing feature:
--
-- 1) Plan rebrand + limit increase (name/leads_per_month/leads_per_day only —
--    price_monthly is UNCHANGED). plans.id is now a legacy internal identifier,
--    decoupled from the current user-facing name — DO NOT assume id == name.
--    id is kept stable because it's a foreign key from subscriptions.plan_id
--    (existing paying customers) and is wired into STRIPE_*_PRICE_ID env-var-
--    keyed lookups (app/config.py: stripe_price_to_plan). Mapping:
--      id=starter    -> name "Starter"    (unchanged), 5,000   -> 10,000/mo
--      id=pro        -> name "Growth"     (renamed),   40,000  -> 25,000/mo
--      id=elite      -> name "Pro"        (renamed),   100,000 -> 50,000/mo
--      id=enterprise -> name "Enterprise" (unchanged), 250,000 -> 125,000/mo
--        (enterprise stays contact-sales-only, no self-serve Stripe path)
--    leads_per_day recomputed as round(leads_per_month / 30) so the existing
--    daily pacing cap stays proportionally consistent with the new figures.
--
-- 2) lead_topups: durable record of self-serve "additional records" purchases
--    (one-time Stripe Checkout charges, mode="payment"), plus the
--    effective-monthly-limit helper that reads it (app/leads_usage.py::
--    get_effective_monthly_limit). period_end is stamped from the buyer's live
--    subscriptions.current_period_end at purchase time; matching against a
--    live current_period_end read later is a plain equality check that
--    naturally stops counting a top-up once the subscription renews to a new
--    period — no expiry job needed.

BEGIN;

UPDATE plans SET name = 'Starter',    leads_per_month = 10000,  leads_per_day = 333  WHERE id = 'starter';
UPDATE plans SET name = 'Growth',     leads_per_month = 25000,  leads_per_day = 833  WHERE id = 'pro';
UPDATE plans SET name = 'Pro',        leads_per_month = 50000,  leads_per_day = 1667 WHERE id = 'elite';
UPDATE plans SET name = 'Enterprise', leads_per_month = 125000, leads_per_day = 4167 WHERE id = 'enterprise';

CREATE TABLE IF NOT EXISTS lead_topups (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id uuid NOT NULL REFERENCES organizations(id),
  purchased_by_user_id uuid NOT NULL REFERENCES users(id),
  plan_id text REFERENCES plans(id),           -- plan active at purchase time (audit only)
  package_size integer NOT NULL,
  amount_paid numeric NOT NULL,
  currency text NOT NULL DEFAULT 'usd',
  stripe_checkout_session_id text NOT NULL UNIQUE,
  stripe_payment_intent_id text,
  status text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','paid','failed','refunded')),
  period_start timestamptz NOT NULL,
  period_end timestamptz NOT NULL,             -- == subscriptions.current_period_end at purchase time
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

-- Hot-path lookup: "sum paid topups for this org, this exact period" — called on
-- every job-create, people-lead-create, and dashboard load.
CREATE INDEX IF NOT EXISTS lead_topups_org_period_idx
  ON lead_topups (organization_id, status, period_end);

ALTER TABLE lead_topups ENABLE ROW LEVEL SECURITY;   -- no policies — service-role
                                                       -- backend connection bypasses RLS,
                                                       -- same posture as stripe_events (0007)

-- Widen notifications.type for the top-up-purchased receipt notification.
ALTER TABLE notifications DROP CONSTRAINT IF EXISTS notifications_type_check;
ALTER TABLE notifications ADD CONSTRAINT notifications_type_check CHECK (type IN (
  'business_request_submitted','business_request_completed',
  'business_request_failed','business_request_cancelled',
  'people_request_submitted','people_request_needs_info','people_request_completed',
  'monthly_limit_warning','daily_limit_warning',
  'subscription_renewal','payment_failure',
  'team_invitation','support_response','file_delivered',
  'refund_processed','payment_disputed',
  'new_support_ticket',
  'new_people_request','new_business_request','people_request_assigned',
  'topup_purchased'
));

COMMIT;
