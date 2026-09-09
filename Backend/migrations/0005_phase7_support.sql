-- Phase 7 — Support
--
-- Run manually against Supabase (SQL editor) BEFORE deploying the backend code that
-- depends on it. Safe to re-run: every statement is IF NOT EXISTS guarded.
--
-- Adds a support-ticket module (§20/§23.9): support_tickets, support_ticket_messages,
-- support_ticket_attachments. No backfill needed — nothing retroactive makes sense
-- (historical support interactions, if any, happened outside this system).

BEGIN;

CREATE TABLE IF NOT EXISTS support_tickets (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id uuid NOT NULL REFERENCES organizations(id),
  created_by uuid NOT NULL REFERENCES users(id),
  subject text NOT NULL,
  category text NOT NULL CHECK (category IN
    ('business_leads','people_leads','billing','account','file_download',
     'data_quality','technical_issue','other')),
  status text NOT NULL DEFAULT 'open' CHECK
    (status IN ('open','in_progress','escalated','resolved','closed')),
  priority text NOT NULL DEFAULT 'normal' CHECK (priority IN ('low','normal','high','urgent')),
  assigned_admin_id uuid REFERENCES users(id),
  linked_resource_type text CHECK
    (linked_resource_type IN ('business_request','people_lead_request','lead_file','invoice')),
  linked_resource_id text,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  resolved_at timestamptz,
  closed_at timestamptz
);
CREATE INDEX IF NOT EXISTS support_tickets_org_idx ON support_tickets(organization_id);
CREATE INDEX IF NOT EXISTS support_tickets_created_by_idx ON support_tickets(created_by);
CREATE INDEX IF NOT EXISTS support_tickets_assigned_admin_idx ON support_tickets(assigned_admin_id);
CREATE INDEX IF NOT EXISTS support_tickets_status_idx ON support_tickets(status);
CREATE INDEX IF NOT EXISTS support_tickets_created_at_idx ON support_tickets(created_at DESC);

CREATE TABLE IF NOT EXISTS support_ticket_messages (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  ticket_id uuid NOT NULL REFERENCES support_tickets(id),
  sender_user_id uuid NOT NULL REFERENCES users(id),
  sender_is_admin boolean NOT NULL DEFAULT false,
  is_internal_note boolean NOT NULL DEFAULT false,
  body text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS support_ticket_messages_ticket_idx ON support_ticket_messages(ticket_id, created_at);

CREATE TABLE IF NOT EXISTS support_ticket_attachments (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  ticket_id uuid NOT NULL REFERENCES support_tickets(id),
  message_id uuid NOT NULL REFERENCES support_ticket_messages(id),
  storage_path text NOT NULL,
  original_filename text NOT NULL,
  file_type text NOT NULL,
  file_size integer NOT NULL,
  uploaded_by uuid NOT NULL REFERENCES users(id),
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS support_ticket_attachments_ticket_idx ON support_ticket_attachments(ticket_id);
CREATE INDEX IF NOT EXISTS support_ticket_attachments_message_idx ON support_ticket_attachments(message_id);

ALTER TABLE support_tickets ENABLE ROW LEVEL SECURITY;
ALTER TABLE support_ticket_messages ENABLE ROW LEVEL SECURITY;
ALTER TABLE support_ticket_attachments ENABLE ROW LEVEL SECURITY;

COMMIT;
