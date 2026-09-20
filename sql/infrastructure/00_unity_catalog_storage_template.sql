-- ADMIN TEMPLATE: replace every CHANGE_ME value before execution.
-- The Storage Credential is created in Catalog Explorer and must already have
-- read/write IAM access to gs://dtl_finops.

CREATE EXTERNAL LOCATION IF NOT EXISTS finops_gcs
URL 'gs://dtl_finops'
WITH (STORAGE CREDENTIAL `CHANGE_ME_STORAGE_CREDENTIAL`)
COMMENT 'FOCUS active and archive prefixes';

CREATE CATALOG IF NOT EXISTS finops_dev;
CREATE SCHEMA IF NOT EXISTS finops_dev.raw;

CREATE EXTERNAL VOLUME IF NOT EXISTS finops_dev.raw.focus
LOCATION 'gs://dtl_finops/focus'
COMMENT 'Active FOCUS landing files';

CREATE EXTERNAL VOLUME IF NOT EXISTS finops_dev.raw.focus_archive
LOCATION 'gs://dtl_finops/focus_archive'
COMMENT 'Processed FOCUS source archive';

-- Repeat the catalog/schema/volume declarations for finops_prod or bind the
-- external location and credentials to a dedicated production workspace.
