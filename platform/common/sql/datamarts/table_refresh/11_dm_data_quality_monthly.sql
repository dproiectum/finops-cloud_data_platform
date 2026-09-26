CREATE OR REPLACE TABLE {dm_data_quality_monthly} USING DELTA AS
SELECT
  billing_month,
  COUNT(*) AS total_rows,
  SUM(CASE WHEN BilledCost IS NULL THEN 1 ELSE 0 END) AS billed_cost_nulls,
  SUM(CASE WHEN BillingCurrency IS NULL THEN 1 ELSE 0 END) AS currency_nulls,
  SUM(CASE WHEN ServiceName IS NULL THEN 1 ELSE 0 END) AS service_nulls,
  COUNT(DISTINCT _ingestion_run_id) AS batches,
  MAX(_ingested_at) AS latest_silver_load
FROM {silver_central}
WHERE billing_month IS NOT NULL
GROUP BY billing_month;
