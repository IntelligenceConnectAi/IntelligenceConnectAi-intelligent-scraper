-- Splits the combined "with website" output into two files: businesses with an
-- email found, and businesses with a website but no email found. The old
-- combined with_web_csv/no_web_csv columns and business_with_website/
-- business_no_website lead_files categories are left untouched -- they keep
-- serving jobs completed before this ships. New jobs populate the two new
-- columns/categories instead and leave with_web_csv NULL (no_web_csv is
-- unaffected either way -- the "no website" file itself isn't being split).

BEGIN;

ALTER TABLE jobs ADD COLUMN IF NOT EXISTS with_web_email_csv text;
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS with_web_no_email_csv text;

ALTER TABLE lead_files DROP CONSTRAINT IF EXISTS lead_files_file_category_check;
ALTER TABLE lead_files ADD CONSTRAINT lead_files_file_category_check CHECK (file_category IN
  ('business_with_website', 'business_no_website', 'people_leads',
   'business_with_website_email', 'business_with_website_no_email'));

COMMIT;
