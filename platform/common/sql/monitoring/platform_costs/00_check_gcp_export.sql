-- BIGQUERY, NOT DATABRICKS. Read-only platform-cost source coverage check.
-- Estimate bytes processed before running; no table is created or modified.
-- Loaded dates and row counts do not prove that a month is fully exported.
SELECT
  FORMAT_TIMESTAMP('%Y-%m', usage_start_time, 'UTC') AS usage_month,
  project.id AS project_id,
  project.name AS project_name,
  service.description AS service,
  currency,
  COUNT(*) AS billing_records,
  MIN(DATE(usage_start_time, 'UTC')) AS first_available_usage_date,
  MAX(DATE(usage_start_time, 'UTC')) AS last_available_usage_date
FROM `global-repeater-355412.finops_billing.gcp_billing_export_v1_01C7B0_D31E31_1E865E`
WHERE (project.id = 'global-repeater-355412'
       OR (project.id = 'pr-5193ad409e7b591' AND service.description = 'Databricks'))
GROUP BY usage_month, project_id, project_name, service, currency
ORDER BY usage_month, project_id, service;

-- Reconciliation by usage month (UTC), not invoice.month. No DBU estimate included.
SELECT
  FORMAT_TIMESTAMP('%Y-%m', usage_start_time, 'UTC') AS usage_month,
  currency,
  ROUND(SUM(CAST(cost AS NUMERIC) + IFNULL((
    SELECT SUM(CAST(c.amount AS NUMERIC)) FROM UNNEST(credits) AS c
  ), 0)), 2) AS recorded_platform_net_cost,
  MAX(export_time) AS latest_export_time
FROM `global-repeater-355412.finops_billing.gcp_billing_export_v1_01C7B0_D31E31_1E865E`
WHERE (project.id = 'global-repeater-355412'
       OR (project.id = 'pr-5193ad409e7b591' AND service.description = 'Databricks'))
  AND usage_start_time >= TIMESTAMP '2026-09-01 00:00:00+00'
  AND usage_start_time < CURRENT_TIMESTAMP()
GROUP BY usage_month, currency
ORDER BY usage_month, currency;
