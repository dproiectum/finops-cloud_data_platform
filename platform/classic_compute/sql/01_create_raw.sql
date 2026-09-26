-- CLASSIC COMPUTE STEP 01 - Re-register the unchanged GCS source as external RAW Volumes.
-- This creates Unity Catalog metadata only; it does not copy the Parquet files.

CREATE EXTERNAL LOCATION IF NOT EXISTS `finops_gcs`
URL 'gs://dtl_finops'
WITH (STORAGE CREDENTIAL `finops_gcs_storage_dev`)
COMMENT 'GCS location used by the FinOps platform';

CREATE CATALOG IF NOT EXISTS `finops_raw`
MANAGED LOCATION 'gs://dtl_finops-unitycatalog-euw1/catalogs/finops_raw'
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
DESCRIBE VOLUME `finops_raw`.`landing`.`focus`;
DESCRIBE VOLUME `finops_raw`.`landing`.`focus_archive`;
LIST '/Volumes/finops_raw/landing/focus/monthly';
