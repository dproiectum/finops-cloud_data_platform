-- BIGQUERY, NOT DATABRICKS. Read-only export for the public monthly summary.
-- Billing export confirmed by the project owner on 2026-10-07.
-- Estimate bytes processed before running; the initial export scans all history.
-- This is usage-month accounting (UTC), not invoice-month reconciliation.
-- Review the project filter: shared/non-project taxes and charges are excluded.
-- All months are conservatively marked partial until manually reconciled.
-- Source: https://docs.cloud.google.com/billing/docs/how-to/bq-examples
SELECT
  FORMAT_TIMESTAMP('%Y-%m', usage_start_time, 'UTC') AS month,
  'GCP' AS provider,
  service.description AS service,
  currency,
  SUM(CAST(cost AS NUMERIC)) AS cost_before_credits,
  SUM(IFNULL((SELECT SUM(CAST(credit.amount AS NUMERIC))
              FROM UNNEST(credits) AS credit), 0)) AS credits,
  CAST(NULL AS NUMERIC) AS usage_quantity,
  '' AS usage_unit,
  'billing_export' AS cost_basis,
  'partial' AS period_status
FROM `global-repeater-355412.finops_billing.gcp_billing_export_v1_01C7B0_D31E31_1E865E`
WHERE project.id = 'global-repeater-355412'
GROUP BY month, service, currency
ORDER BY month, service;
