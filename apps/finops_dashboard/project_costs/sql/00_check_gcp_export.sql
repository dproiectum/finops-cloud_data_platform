-- BIGQUERY, NOT DATABRICKS. Read-only initial source coverage check.
-- Estimate bytes processed before running; no table is created or modified.
-- Loaded dates and row counts do not prove that a month is fully exported.
SELECT
  FORMAT_TIMESTAMP('%Y-%m', usage_start_time, 'UTC') AS usage_month,
  currency,
  COUNT(*) AS billing_records,
  MIN(DATE(usage_start_time, 'UTC')) AS first_available_usage_date,
  MAX(DATE(usage_start_time, 'UTC')) AS last_available_usage_date
FROM `global-repeater-355412.finops_billing.gcp_billing_export_v1_01C7B0_D31E31_1E865E`
WHERE project.id = 'global-repeater-355412'
GROUP BY usage_month, currency
ORDER BY usage_month;
