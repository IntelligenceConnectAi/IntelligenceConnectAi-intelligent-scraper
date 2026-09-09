-- Admin-facing notification types for the two request-creation flows and
-- People Leads assignment. Previously, a brand-new People/Business Leads
-- request never notified any admin at all (dashboard or email) — the only
-- notification on creation went to the submitting client. Mirrors the
-- existing "new_support_ticket" precedent (notify_admins_with_permission).

BEGIN;

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
  'new_people_request','new_business_request','people_request_assigned'
));

COMMIT;
