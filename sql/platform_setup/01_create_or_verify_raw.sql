-- STEP 01 - Create RAW only when absent, then verify the monthly Parquets.
-- Existing objects and GCS files are not replaced or deleted.

CREATE EXTERNAL LOCATION IF NOT EXISTS `finops_gcs`
URL 'gs://dtl_finops'
WITH (STORAGE CREDENTIAL `finops_gcs_storage_dev`)
COMMENT 'GCS location used by the FinOps platform';

CREATE CATALOG IF NOT EXISTS `finops_raw`
COMMENT 'Environment-independent FOCUS source data';

CREATE SCHEMA IF NOT EXISTS `finops_raw`.`landing`
COMMENT 'External Volumes containing immutable FOCUS Parquet files';

CREATE EXTERNAL VOLUME IF NOT EXISTS `finops_raw`.`landing`.`focus`
LOCATION 'gs://dtl_finops/focus'
COMMENT 'FOCUS source files consumed independently by DEV and PROD';

CREATE EXTERNAL VOLUME IF NOT EXISTS `finops_raw`.`landing`.`focus_archive`
LOCATION 'gs://dtl_finops/focus_archive'
COMMENT 'Optional archive location; automatic archival is currently disabled';

SHOW VOLUMES IN `finops_raw`.`landing`;
LIST '/Volumes/finops_raw/landing/focus/monthly';
