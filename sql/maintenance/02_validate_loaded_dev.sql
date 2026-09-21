-- Read-only checks after running 03_billing_backfill.ipynb.

SELECT 'bronze.focus_billing_raw' AS table_name, count(*) AS row_count
FROM `finops_dev`.`bronze`.`focus_billing_raw`
UNION ALL
SELECT 'silver.focus_cost_usage', count(*)
FROM `finops_dev`.`silver`.`focus_cost_usage`
UNION ALL
SELECT 'silver.focus_cost_usage_central', count(*)
FROM `finops_dev`.`silver`.`focus_cost_usage_central`
UNION ALL
SELECT 'gold.fact_finops_cost_usage', count(*)
FROM `finops_dev`.`gold`.`fact_finops_cost_usage`
UNION ALL
SELECT 'datamart.dm_monthly_billing', count(*)
FROM `finops_dev`.`datamart`.`dm_monthly_billing`;

SELECT environment, billing_month, status, authoritative_source, updated_at
FROM `finops_ops`.`audit`.`month_status`
WHERE environment = 'dev'
ORDER BY billing_month;

SELECT environment, billing_month, status,
       billing_rows, after_rows, after_billing_difference, reconciled_at
FROM `finops_ops`.`audit`.`monthly_reconciliation`
WHERE environment = 'dev'
ORDER BY billing_month;

-- Expected result: no row. One source path must belong to only one ingestion run
-- after a clean reload.
SELECT _source_file, count(DISTINCT _ingestion_run_id) AS ingestion_runs
FROM `finops_dev`.`bronze`.`focus_billing_raw`
GROUP BY _source_file
HAVING count(DISTINCT _ingestion_run_id) > 1;

-- Expected duplicate_keys = 0 for every month.
SELECT
  billing_month,
  count(*) AS fact_rows,
  count(DISTINCT cost_usage_sk) AS distinct_fact_keys,
  count(*) - count(DISTINCT cost_usage_sk) AS duplicate_keys
FROM `finops_dev`.`gold`.`fact_finops_cost_usage`
GROUP BY billing_month
ORDER BY billing_month;

-- Expected duplicate_charge_ids = 0 for every AFTER snapshot.
SELECT billing_month, row_count, duplicate_charge_ids, null_critical_count
FROM `finops_ops`.`audit`.`month_snapshot`
WHERE environment = 'dev' AND capture_stage = 'AFTER'
ORDER BY billing_month;
