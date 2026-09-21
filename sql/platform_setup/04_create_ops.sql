-- STEP 04 - Recreate OPS before any validation or pipeline execution.
-- One operations catalog records DEV and PROD independently through the
-- environment column.

CREATE CATALOG IF NOT EXISTS `finops_ops`
COMMENT 'Operational monitoring and reconciliation for FinOps pipelines';

CREATE SCHEMA IF NOT EXISTS `finops_ops`.`audit`
COMMENT 'Pipeline runs, monthly snapshots, reconciliation, and archive audit';

CREATE TABLE IF NOT EXISTS `finops_ops`.`audit`.`pipeline_run` (
  run_id STRING,
  pipeline_name STRING,
  environment STRING,
  billing_month STRING,
  status STRING,
  started_at TIMESTAMP,
  finished_at TIMESTAMP,
  message STRING
) USING DELTA;

CREATE TABLE IF NOT EXISTS `finops_ops`.`audit`.`month_snapshot` (
  run_id STRING,
  pipeline_name STRING,
  environment STRING,
  billing_month STRING,
  capture_stage STRING,
  source_type STRING,
  row_count BIGINT,
  billed_cost_total DECIMAL(38,6),
  effective_cost_total DECIMAL(38,6),
  list_cost_total DECIMAL(38,6),
  distinct_accounts BIGINT,
  distinct_resources BIGINT,
  duplicate_charge_ids BIGINT,
  null_critical_count BIGINT,
  min_charge_period TIMESTAMP,
  max_charge_period TIMESTAMP,
  delta_table_version BIGINT,
  captured_at TIMESTAMP
) USING DELTA;

CREATE TABLE IF NOT EXISTS `finops_ops`.`audit`.`monthly_reconciliation` (
  run_id STRING,
  environment STRING,
  billing_month STRING,
  before_rows BIGINT,
  billing_rows BIGINT,
  after_rows BIGINT,
  before_billed_cost DECIMAL(38,6),
  billing_billed_cost DECIMAL(38,6),
  after_billed_cost DECIMAL(38,6),
  billing_daily_difference DECIMAL(38,6),
  after_billing_difference DECIMAL(38,6),
  status STRING,
  reconciled_at TIMESTAMP
) USING DELTA;

CREATE TABLE IF NOT EXISTS `finops_ops`.`audit`.`month_status` (
  environment STRING,
  billing_month STRING,
  status STRING,
  authoritative_source STRING,
  last_run_id STRING,
  updated_at TIMESTAMP
) USING DELTA;

CREATE TABLE IF NOT EXISTS `finops_ops`.`audit`.`file_archive` (
  run_id STRING,
  environment STRING,
  billing_month STRING,
  source_uri STRING,
  archive_uri STRING,
  source_generation STRING,
  archive_generation STRING,
  crc32c STRING,
  size_bytes BIGINT,
  archive_status STRING,
  archived_at TIMESTAMP,
  error_message STRING
) USING DELTA;
