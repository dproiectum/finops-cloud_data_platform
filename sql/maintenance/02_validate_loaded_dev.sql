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
