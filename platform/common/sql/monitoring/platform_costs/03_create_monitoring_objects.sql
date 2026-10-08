-- DATABRICKS BELGIUM ONLY. Additive setup; do not run catalog-reset scripts.
-- Uses the existing finops_ops managed storage and finops_gcs external location.
CREATE SCHEMA IF NOT EXISTS finops_ops.monitoring
COMMENT 'Private operational monitoring, independent of synthetic business data';

CREATE EXTERNAL VOLUME IF NOT EXISTS finops_ops.monitoring.platform_cost_files
LOCATION 'gs://dtl_finops/platform_costs'
COMMENT 'Private platform cost extracts and approved serving object';

CREATE TABLE IF NOT EXISTS finops_ops.monitoring.platform_cost_monthly (
  month STRING NOT NULL, provider STRING NOT NULL, service STRING NOT NULL,
  currency STRING NOT NULL,
  cost_before_credits DECIMAL(38,18) NOT NULL,
  credits DECIMAL(38,18), usage_quantity DECIMAL(38,18),
  usage_unit STRING, cost_basis STRING NOT NULL, period_status STRING NOT NULL,
  collection_run_id STRING NOT NULL, collected_at TIMESTAMP NOT NULL
) USING DELTA
COMMENT 'Latest validated full aggregate snapshot for the two platform-cost sources';

CREATE TABLE IF NOT EXISTS finops_ops.monitoring.platform_cost_collection_run (
  run_id STRING NOT NULL, started_at TIMESTAMP NOT NULL,
  finished_at TIMESTAMP NOT NULL, status STRING NOT NULL,
  gcp_export_run_id STRING, gcp_extracted_at TIMESTAMP,
  gcp_rows INT, databricks_rows INT, snapshot_sha256 STRING,
  error_code STRING
) USING DELTA
COMMENT 'Private collection audit; no source credentials or raw error bodies';

DESCRIBE VOLUME finops_ops.monitoring.platform_cost_files;
SHOW TABLES IN finops_ops.monitoring;
