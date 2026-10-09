-- BIGQUERY ONLY. Run manually first, then schedule daily in location EU.
-- No local download and no service-account key in Databricks.
-- Unique export directory per full script execution; COMPLETE follows data export.
-- overwrite=true is required for a non-empty destination bucket. Only objects
-- with the exact generated export URIs can be replaced; no objects are deleted.
-- Always rerun the whole script to generate a new run_id, not an export alone.
-- Review estimated scan bytes and the destination bucket's location/permissions.
-- Explicit project allowlist: native FinOps services plus Databricks Marketplace.
-- Provider is a reporting category, not the invoicing channel: both come from GCP Billing.
DECLARE extracted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP();
DECLARE run_id STRING DEFAULT CONCAT(FORMAT_TIMESTAMP('%Y%m%dT%H%M%SZ', extracted_at, 'UTC'), '_', REPLACE(GENERATE_UUID(), '-', ''));
DECLARE base_uri STRING DEFAULT CONCAT('gs://dtl_finops/platform_costs/extracts/gcp/', run_id, '/');

CREATE TEMP TABLE daily_cost AS
SELECT
  FORMAT_TIMESTAMP('%Y-%m-%d', usage_start_time, 'UTC') AS usage_date,
  FORMAT_TIMESTAMP('%Y-%m', usage_start_time, 'UTC') AS month,
  CASE WHEN service.description = 'Databricks' THEN 'Databricks' ELSE 'GCP' END AS provider,
  service.description AS service,
  currency,
  CAST(SUM(CAST(cost AS NUMERIC)) AS STRING) AS cost_before_credits,
  CAST(SUM(IFNULL((SELECT SUM(CAST(credit.amount AS NUMERIC)) FROM UNNEST(credits) AS credit), 0)) AS STRING) AS credits,
  CAST(NULL AS STRING) AS usage_quantity,
  '' AS usage_unit,
  'billing_export' AS cost_basis,
  'partial' AS period_status
FROM `global-repeater-355412.finops_billing.gcp_billing_export_v1_01C7B0_D31E31_1E865E`
WHERE (project.id = 'global-repeater-355412'
       OR (project.id = 'pr-5193ad409e7b591' AND service.description = 'Databricks'))
  AND usage_start_time >= TIMESTAMP '2026-09-01 00:00:00+00'
  AND usage_start_time < extracted_at
GROUP BY usage_date, month, provider, service, currency;

ASSERT (SELECT COUNT(*) BETWEEN 1 AND 10000 FROM daily_cost) AS 'Missing or oversized GCP aggregates';
ASSERT (SELECT COUNTIF(cost_before_credits IS NULL OR credits IS NULL OR service IS NULL OR currency IS NULL) = 0 FROM daily_cost) AS 'Invalid GCP aggregate';
ASSERT (SELECT COUNT(DISTINCT provider) = 2 FROM daily_cost) AS 'Missing native GCP or Databricks Marketplace billing';

EXECUTE IMMEDIATE FORMAT("""
  EXPORT DATA OPTIONS(uri='%sdata-*.parquet', format='PARQUET', overwrite=true)
  AS SELECT * FROM daily_cost
""", base_uri);

-- This is extraction freshness, not proof of complete billing history.
EXECUTE IMMEDIATE FORMAT("""
  EXPORT DATA OPTIONS(uri='%scomplete-*.json', format='JSON', overwrite=true)
  AS SELECT 3 AS schema_version, 'daily' AS granularity,
    'finops_and_databricks_marketplace' AS billing_scope, @run_id AS run_id,
    FORMAT_TIMESTAMP('%%Y-%%m-%%dT%%H:%%M:%%E6SZ', @extracted_at, 'UTC') AS extracted_at,
    (SELECT COUNT(*) FROM daily_cost) AS row_count, 'COMPLETE' AS status
""", base_uri)
USING run_id AS run_id, extracted_at AS extracted_at;

SELECT run_id, base_uri, extracted_at, (SELECT COUNT(*) FROM daily_cost) AS exported_rows;
