-- STEP 08 - Read-only controls after a PROD canary or historical load.

SELECT 'bronze.focus_billing_raw' AS table_name, count(*) AS row_count
FROM `finops_prod`.`bronze`.`focus_billing_raw`
UNION ALL
SELECT 'silver.focus_cost_usage', count(*)
FROM `finops_prod`.`silver`.`focus_cost_usage`
UNION ALL
SELECT 'silver.focus_cost_usage_central', count(*)
FROM `finops_prod`.`silver`.`focus_cost_usage_central`
UNION ALL
SELECT 'gold.fact_finops_cost_usage', count(*)
FROM `finops_prod`.`gold`.`fact_finops_cost_usage`
UNION ALL
SELECT 'datamart.dm_monthly_billing', count(*)
FROM `finops_prod`.`datamart`.`dm_monthly_billing`;

-- Expected result: one row per loaded month, with all four differences at zero.
WITH bronze AS (
  SELECT
    date_format(to_date(BillingPeriodStart), 'yyyy-MM') AS billing_month,
    count(*) AS bronze_rows,
    sum(CAST(BilledCost AS DECIMAL(38,6))) AS bronze_billed_cost
  FROM `finops_prod`.`bronze`.`focus_billing_raw`
  GROUP BY date_format(to_date(BillingPeriodStart), 'yyyy-MM')
), silver AS (
  SELECT
    billing_month,
    count(*) AS silver_rows,
    sum(CAST(BilledCost AS DECIMAL(38,6))) AS silver_billed_cost
  FROM `finops_prod`.`silver`.`focus_cost_usage_central`
  GROUP BY billing_month
), gold AS (
  SELECT
    billing_month,
    count(*) AS gold_rows,
    sum(CAST(billed_cost AS DECIMAL(38,6))) AS gold_billed_cost
  FROM `finops_prod`.`gold`.`fact_finops_cost_usage`
  GROUP BY billing_month
), months AS (
  SELECT billing_month FROM bronze
  UNION
  SELECT billing_month FROM silver
  UNION
  SELECT billing_month FROM gold
)
SELECT
  months.billing_month,
  bronze.bronze_rows,
  silver.silver_rows,
  gold.gold_rows,
  bronze.bronze_rows - silver.silver_rows AS bronze_silver_row_difference,
  silver.silver_rows - gold.gold_rows AS silver_gold_row_difference,
  bronze.bronze_billed_cost - silver.silver_billed_cost
    AS bronze_silver_cost_difference,
  silver.silver_billed_cost - gold.gold_billed_cost
    AS silver_gold_cost_difference
FROM months
LEFT JOIN bronze USING (billing_month)
LEFT JOIN silver USING (billing_month)
LEFT JOIN gold USING (billing_month)
ORDER BY months.billing_month;

SELECT environment, billing_month, status, authoritative_source, updated_at
FROM `finops_ops`.`audit`.`month_status`
WHERE environment = 'prod'
ORDER BY billing_month;

WITH latest AS (
  SELECT *,
    row_number() OVER (
      PARTITION BY environment, billing_month
      ORDER BY reconciled_at DESC
    ) AS rn
  FROM `finops_ops`.`audit`.`monthly_reconciliation`
  WHERE environment = 'prod'
)
SELECT environment, billing_month, status,
       billing_rows, after_rows, after_billing_difference, reconciled_at
FROM latest
WHERE rn = 1
ORDER BY billing_month;

-- Expected result: no row. Historical failures remain visible, but only the
-- latest run of each PROD pipeline/month must be successful.
WITH latest AS (
  SELECT *,
    row_number() OVER (
      PARTITION BY environment, pipeline_name, billing_month
      ORDER BY started_at DESC
    ) AS rn
  FROM `finops_ops`.`audit`.`pipeline_run`
  WHERE environment = 'prod'
)
SELECT run_id, pipeline_name, billing_month, status, started_at, message
FROM latest
WHERE rn = 1 AND status <> 'SUCCESS'
ORDER BY started_at;

-- Expected result: no row.
SELECT _source_file, count(DISTINCT _ingestion_run_id) AS ingestion_runs
FROM `finops_prod`.`bronze`.`focus_billing_raw`
GROUP BY _source_file
HAVING count(DISTINCT _ingestion_run_id) > 1;

-- Expected duplicate_keys = 0 for every loaded month.
SELECT
  billing_month,
  count(*) AS fact_rows,
  count(DISTINCT cost_usage_sk) AS distinct_fact_keys,
  count(*) - count(DISTINCT cost_usage_sk) AS duplicate_keys
FROM `finops_prod`.`gold`.`fact_finops_cost_usage`
GROUP BY billing_month
ORDER BY billing_month;

-- Expected duplicate_charge_ids=0 and null_critical_count=0.
SELECT billing_month, row_count, duplicate_charge_ids, null_critical_count
FROM `finops_ops`.`audit`.`month_snapshot`
WHERE environment = 'prod' AND capture_stage = 'AFTER'
ORDER BY billing_month, captured_at;

-- Bronze preserves source defects; PROD Silver must contain the same contract
-- fallback that was validated in DEV.
WITH bronze AS (
  SELECT
    date_format(to_date(BillingPeriodStart), 'yyyy-MM') AS billing_month,
    sum(CASE WHEN ServiceName IS NULL THEN 1 ELSE 0 END)
      AS source_service_name_nulls
  FROM `finops_prod`.`bronze`.`focus_billing_raw`
  GROUP BY date_format(to_date(BillingPeriodStart), 'yyyy-MM')
), silver AS (
  SELECT
    billing_month,
    sum(CASE WHEN ServiceName IS NULL THEN 1 ELSE 0 END)
      AS silver_service_name_nulls
  FROM `finops_prod`.`silver`.`focus_cost_usage_central`
  GROUP BY billing_month
)
SELECT
  coalesce(bronze.billing_month, silver.billing_month) AS billing_month,
  coalesce(bronze.source_service_name_nulls, 0) AS source_service_name_nulls,
  coalesce(silver.silver_service_name_nulls, 0) AS silver_service_name_nulls
FROM bronze
FULL OUTER JOIN silver ON bronze.billing_month = silver.billing_month
ORDER BY billing_month;

-- Shared OPS must retain independent histories for DEV and PROD.
SELECT environment, count(*) AS pipeline_runs
FROM `finops_ops`.`audit`.`pipeline_run`
GROUP BY environment
ORDER BY environment;

-- The assertions below turn the SQL Job task red on a blocking PROD failure.
SELECT assert_true(
  count(*) > 0,
  'CONTROL FAILED: PROD Gold contains no loaded row'
)
FROM `finops_prod`.`gold`.`fact_finops_cost_usage`;

WITH bronze AS (
  SELECT date_format(to_date(BillingPeriodStart), 'yyyy-MM') AS billing_month,
         count(*) AS row_count,
         sum(CAST(BilledCost AS DECIMAL(38,6))) AS billed_cost
  FROM `finops_prod`.`bronze`.`focus_billing_raw`
  GROUP BY date_format(to_date(BillingPeriodStart), 'yyyy-MM')
), silver AS (
  SELECT billing_month, count(*) AS row_count,
         sum(CAST(BilledCost AS DECIMAL(38,6))) AS billed_cost
  FROM `finops_prod`.`silver`.`focus_cost_usage_central`
  GROUP BY billing_month
), gold AS (
  SELECT billing_month, count(*) AS row_count,
         sum(CAST(billed_cost AS DECIMAL(38,6))) AS billed_cost
  FROM `finops_prod`.`gold`.`fact_finops_cost_usage`
  GROUP BY billing_month
), months AS (
  SELECT billing_month FROM bronze
  UNION SELECT billing_month FROM silver
  UNION SELECT billing_month FROM gold
), mismatches AS (
  SELECT months.billing_month
  FROM months
  LEFT JOIN bronze USING (billing_month)
  LEFT JOIN silver USING (billing_month)
  LEFT JOIN gold USING (billing_month)
  WHERE bronze.row_count IS NULL OR silver.row_count IS NULL OR gold.row_count IS NULL
     OR bronze.billed_cost IS NULL OR silver.billed_cost IS NULL OR gold.billed_cost IS NULL
     OR bronze.row_count <> silver.row_count
     OR silver.row_count <> gold.row_count
     OR abs(bronze.billed_cost - silver.billed_cost) >= 0.005
     OR abs(silver.billed_cost - gold.billed_cost) >= 0.005
)
SELECT assert_true(
  count(*) = 0,
  'CONTROL FAILED: PROD Bronze, Silver, and Gold do not reconcile by month'
)
FROM mismatches;

WITH gold_months AS (
  SELECT DISTINCT billing_month
  FROM `finops_prod`.`gold`.`fact_finops_cost_usage`
), latest AS (
  SELECT *,
    row_number() OVER (
      PARTITION BY environment, billing_month
      ORDER BY reconciled_at DESC
    ) AS rn
  FROM `finops_ops`.`audit`.`monthly_reconciliation`
  WHERE environment = 'prod'
), latest_per_month AS (
  SELECT billing_month, status, after_billing_difference
  FROM latest
  WHERE rn = 1
), mismatches AS (
  SELECT coalesce(gold_months.billing_month, latest_per_month.billing_month)
    AS billing_month
  FROM gold_months
  FULL OUTER JOIN latest_per_month
    ON gold_months.billing_month = latest_per_month.billing_month
  WHERE gold_months.billing_month IS NULL
     OR latest_per_month.billing_month IS NULL
     OR latest_per_month.status <> 'PASSED'
     OR latest_per_month.after_billing_difference IS NULL
     OR abs(latest_per_month.after_billing_difference) >= 0.005
)
SELECT assert_true(
  count(*) = 0,
  'CONTROL FAILED: latest PROD reconciliation is absent, failed, or non-zero'
)
FROM mismatches;

WITH latest AS (
  SELECT *,
    row_number() OVER (
      PARTITION BY environment, pipeline_name, billing_month
      ORDER BY started_at DESC
    ) AS rn
  FROM `finops_ops`.`audit`.`pipeline_run`
  WHERE environment = 'prod'
)
SELECT assert_true(
  count(*) = 0,
  'CONTROL FAILED: latest PROD pipeline run is not successful'
)
FROM latest
WHERE rn = 1 AND status <> 'SUCCESS';

SELECT assert_true(
  count(*) = 0,
  'CONTROL FAILED: a PROD Bronze source belongs to multiple ingestion runs'
)
FROM (
  SELECT _source_file
  FROM `finops_prod`.`bronze`.`focus_billing_raw`
  GROUP BY _source_file
  HAVING count(DISTINCT _ingestion_run_id) > 1
) AS duplicate_source_ingestions;

SELECT assert_true(
  count(*) = 0,
  'CONTROL FAILED: duplicate PROD Gold fact keys exist'
)
FROM (
  SELECT cost_usage_sk
  FROM `finops_prod`.`gold`.`fact_finops_cost_usage`
  GROUP BY cost_usage_sk
  HAVING count(*) > 1
) AS duplicate_fact_keys;

SELECT assert_true(
  count(*) = 0,
  'CONTROL FAILED: a PROD AFTER snapshot contains duplicates or critical nulls'
)
FROM `finops_ops`.`audit`.`month_snapshot`
WHERE environment = 'prod'
  AND capture_stage = 'AFTER'
  AND (duplicate_charge_ids <> 0 OR null_critical_count <> 0);

SELECT assert_true(
  count(*) = 0,
  'CONTROL FAILED: PROD Silver still contains a null ServiceName'
)
FROM `finops_prod`.`silver`.`focus_cost_usage_central`
WHERE ServiceName IS NULL;

