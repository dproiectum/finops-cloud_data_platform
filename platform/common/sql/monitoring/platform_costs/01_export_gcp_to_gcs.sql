-- BIGQUERY ONLY. Run manually first, then schedule daily in location EU.
-- No local download and no service-account key in Databricks.
-- Unique export directory per full script execution; COMPLETE follows data export.
-- overwrite=true is required for a non-empty destination bucket. Only objects
-- with the exact generated export URIs can be replaced; no objects are deleted.
-- Always rerun the whole script to generate a new run_id, not an export alone.
-- Review estimated scan bytes and the destination bucket's location/permissions.
DECLARE extracted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP();
DECLARE run_id STRING DEFAULT CONCAT(FORMAT_TIMESTAMP('%Y%m%dT%H%M%SZ', extracted_at, 'UTC'), '_', REPLACE(GENERATE_UUID(), '-', ''));
DECLARE base_uri STRING DEFAULT CONCAT('gs://dtl_finops/platform_costs/extracts/gcp/', run_id, '/');

CREATE TEMP TABLE monthly_cost AS
SELECT
  FORMAT_TIMESTAMP('%Y-%m', usage_start_time, 'UTC') AS month,
  'GCP' AS provider,
  service.description AS service,
  currency,
  CAST(SUM(CAST(cost AS NUMERIC)) AS STRING) AS cost_before_credits,
  CAST(SUM(IFNULL((SELECT SUM(CAST(credit.amount AS NUMERIC)) FROM UNNEST(credits) AS credit), 0)) AS STRING) AS credits,
  CAST(NULL AS STRING) AS usage_quantity,
  '' AS usage_unit,
  'billing_export' AS cost_basis,
  'partial' AS period_status
FROM `global-repeater-355412.finops_billing.gcp_billing_export_v1_01C7B0_D31E31_1E865E`
WHERE project.id = 'global-repeater-355412'
  AND usage_start_time >= TIMESTAMP '2026-09-01 00:00:00+00'
  AND usage_start_time < extracted_at
GROUP BY month, service, currency;

ASSERT (SELECT COUNT(*) BETWEEN 1 AND 10000 FROM monthly_cost) AS 'Missing or oversized GCP aggregates';
ASSERT (SELECT COUNTIF(cost_before_credits IS NULL OR credits IS NULL OR service IS NULL OR currency IS NULL) = 0 FROM monthly_cost) AS 'Invalid GCP aggregate';

EXECUTE IMMEDIATE FORMAT("""
  EXPORT DATA OPTIONS(uri='%sdata-*.parquet', format='PARQUET', overwrite=true)
  AS SELECT * FROM monthly_cost
""", base_uri);

-- This is extraction freshness, not proof of complete billing history.
EXECUTE IMMEDIATE FORMAT("""
  EXPORT DATA OPTIONS(uri='%scomplete-*.json', format='JSON', overwrite=true)
  AS SELECT 1 AS schema_version, @run_id AS run_id,
    FORMAT_TIMESTAMP('%%Y-%%m-%%dT%%H:%%M:%%E6SZ', @extracted_at, 'UTC') AS extracted_at,
    (SELECT COUNT(*) FROM monthly_cost) AS row_count, 'COMPLETE' AS status
""", base_uri)
USING run_id AS run_id, extracted_at AS extracted_at;

SELECT run_id, base_uri, extracted_at, (SELECT COUNT(*) FROM monthly_cost) AS exported_rows;
