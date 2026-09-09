-- Email notifications: a master email on/off switch on top of the existing
-- muted_categories gate (see app/notifications.py), plus one new notification
-- type for the net-new "new support ticket" admin alert. The admin-side
-- payment-dispute alert reuses the existing payment_disputed type — recipient
-- is distinguished by notifications.user_id, not by type, so no new type is
-- needed there.

BEGIN;

ALTER TABLE notification_preferences
  ADD COLUMN IF NOT EXISTS email_enabled boolean NOT NULL DEFAULT true;
-- DEFAULT true is deliberate: every email this feature sends is
-- transactional/account-service class (payment failure/dispute, ticket reply,
-- job done/failed, team invite) — the class that's conventionally on-by-default
-- across SaaS, not marketing. Existing users/admins are retroactively opted in
-- on deploy, which is the intended behavior. A fixed-default boolean ADD COLUMN
-- is metadata-only on PG11+, so this is safe against a populated table.

ALTER TABLE notifications DROP CONSTRAINT IF EXISTS notifications_type_check;
ALTER TABLE notifications ADD CONSTRAINT notifications_type_check CHECK (type IN (
  'business_request_submitted','business_request_completed',
  'business_request_failed','business_request_cancelled',
  'people_request_submitted','people_request_needs_info','people_request_completed',
  'monthly_limit_warning','daily_limit_warning',
  'subscription_renewal','payment_failure',
  'team_invitation','support_response','file_delivered',
  'refund_processed','payment_disputed',
  'new_support_ticket'
));

COMMIT;
