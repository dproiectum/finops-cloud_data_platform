-- JOB RUN COST MONITORING
--
-- Replace target_job_id and target_job_run_id with the values shown in the
-- Databricks run URL: /jobs/<job_id>/runs/<run_id>.
-- Billing records usually arrive after the run; an empty result immediately
-- after completion does not mean that the run consumed zero DBUs.

DECLARE OR REPLACE VARIABLE target_workspace_id STRING DEFAULT '8259550830613689';
DECLARE OR REPLACE VARIABLE target_job_name STRING DEFAULT 'finops-daily-dev-to-prod';
DECLARE OR REPLACE VARIABLE target_job_id STRING DEFAULT '';
DECLARE OR REPLACE VARIABLE target_job_run_id STRING DEFAULT '';
DECLARE OR REPLACE VARIABLE target_cluster_id STRING DEFAULT '5925-212130-elwuj3uu';

-- 1. Find recent run IDs when they are not yet known.
WITH latest_jobs AS (
  SELECT workspace_id, job_id, name
  FROM (
    SELECT *,
           row_number() OVER (
             PARTITION BY workspace_id, job_id
             ORDER BY change_time DESC
           ) AS rn
    FROM system.lakeflow.jobs
    WHERE workspace_id = target_workspace_id
  )
  WHERE rn = 1 AND delete_time IS NULL
), run_summary AS (
  SELECT
    runs.workspace_id,
    runs.job_id,
    runs.run_id,
    min(runs.period_start_time) AS run_start_time_utc,
    max(runs.period_end_time) AS run_end_time_utc,
    max_by(runs.result_state, runs.period_end_time) AS result_state,
    max_by(runs.job_parameters, runs.period_end_time) AS job_parameters
  FROM system.lakeflow.job_run_timeline AS runs
  WHERE runs.workspace_id = target_workspace_id
  GROUP BY runs.workspace_id, runs.job_id, runs.run_id
)
SELECT
  jobs.name AS job_name,
  runs.job_id,
  runs.run_id AS job_run_id,
  runs.run_start_time_utc,
  runs.run_end_time_utc,
  timestampdiff(SECOND, runs.run_start_time_utc, runs.run_end_time_utc)
    AS elapsed_seconds,
  runs.result_state,
  runs.job_parameters
FROM run_summary AS runs
JOIN latest_jobs AS jobs
  ON runs.workspace_id = jobs.workspace_id
 AND runs.job_id = jobs.job_id
WHERE jobs.name = target_job_name
ORDER BY runs.run_start_time_utc DESC
LIMIT 20;

-- 2. Task durations for the selected run. Job timelines normally arrive
-- within about one hour after the task finishes.
SELECT
  task_key,
  min(period_start_time) AS task_start_time_utc,
  max(period_end_time) AS task_end_time_utc,
  sum(unix_timestamp(period_end_time) - unix_timestamp(period_start_time))
    AS execution_seconds,
  max_by(result_state, period_end_time) AS result_state,
  flatten(collect_set(compute_ids)) AS compute_ids
FROM system.lakeflow.job_task_run_timeline
WHERE workspace_id = target_workspace_id
  AND job_id = target_job_id
  AND job_run_id = target_job_run_id
GROUP BY task_key
ORDER BY task_start_time_utc;

-- 3. Exact Databricks DBUs and list cost for Serverless or Job Compute.
-- For All-Purpose Classic, job_run_id is not populated in billing records, so
-- this section normally returns no row and section 4 must be used instead.
WITH priced_exact_usage AS (
  SELECT
    usage.sku_name,
    usage.usage_unit,
    prices.currency_code,
    usage.usage_quantity,
    usage.usage_quantity
      * coalesce(
          prices.pricing.effective_list.default,
          prices.pricing.default
        ) AS list_cost
  FROM system.billing.usage AS usage
  LEFT JOIN system.billing.list_prices AS prices
    ON usage.cloud = prices.cloud
   AND usage.sku_name = prices.sku_name
   AND usage.usage_unit = prices.usage_unit
   AND prices.currency_code = 'USD'
   AND usage.usage_end_time >= prices.price_start_time
   AND (
        prices.price_end_time IS NULL
        OR usage.usage_end_time < prices.price_end_time
   )
  WHERE usage.workspace_id = target_workspace_id
    AND usage.usage_metadata.job_id = target_job_id
    AND usage.usage_metadata.job_run_id = target_job_run_id
)
SELECT
  'EXACT_JOB_RUN_METADATA' AS allocation_method,
  sku_name,
  usage_unit,
  currency_code,
  round(sum(usage_quantity), 6) AS consumed_units,
  round(sum(list_cost), 4) AS databricks_list_cost
FROM priced_exact_usage
GROUP BY sku_name, usage_unit, currency_code
ORDER BY sku_name;

-- 4. All-Purpose Classic estimate.
-- Billing records identify the cluster but not the Job run. The query therefore
-- prorates every cluster billing interval by its overlap with the run window.
-- Keep this cluster dedicated to the measured Job during the run; concurrent
-- notebooks or Jobs would be included in the estimate.
WITH run_bounds AS (
  SELECT
    min(period_start_time) AS run_start_time_utc,
    max(period_end_time) AS run_end_time_utc
  FROM system.lakeflow.job_run_timeline
  WHERE workspace_id = target_workspace_id
    AND job_id = target_job_id
    AND run_id = target_job_run_id
), overlapping_usage AS (
  SELECT
    usage.sku_name,
    usage.usage_unit,
    usage.usage_quantity,
    usage.usage_start_time,
    usage.usage_end_time,
    greatest(
      0,
      unix_timestamp(least(usage.usage_end_time, bounds.run_end_time_utc))
        - unix_timestamp(greatest(usage.usage_start_time, bounds.run_start_time_utc))
    ) AS overlap_seconds,
    greatest(
      1,
      unix_timestamp(usage.usage_end_time)
        - unix_timestamp(usage.usage_start_time)
    ) AS billing_interval_seconds
  FROM system.billing.usage AS usage
  CROSS JOIN run_bounds AS bounds
  WHERE usage.workspace_id = target_workspace_id
    AND usage.usage_metadata.cluster_id = target_cluster_id
    AND bounds.run_start_time_utc IS NOT NULL
    AND usage.usage_end_time > bounds.run_start_time_utc
    AND usage.usage_start_time < bounds.run_end_time_utc
), prorated_usage AS (
  SELECT
    sku_name,
    usage_unit,
    usage_end_time,
    usage_quantity * overlap_seconds / billing_interval_seconds
      AS estimated_usage_quantity
  FROM overlapping_usage
  WHERE overlap_seconds > 0
), priced_classic_usage AS (
  SELECT
    usage.sku_name,
    usage.usage_unit,
    prices.currency_code,
    usage.estimated_usage_quantity,
    usage.estimated_usage_quantity
      * coalesce(
          prices.pricing.effective_list.default,
          prices.pricing.default
        ) AS estimated_list_cost
  FROM prorated_usage AS usage
  LEFT JOIN system.billing.list_prices AS prices
    ON prices.cloud = 'GCP'
   AND usage.sku_name = prices.sku_name
   AND usage.usage_unit = prices.usage_unit
   AND prices.currency_code = 'USD'
   AND usage.usage_end_time >= prices.price_start_time
   AND (
        prices.price_end_time IS NULL
        OR usage.usage_end_time < prices.price_end_time
   )
)
SELECT
  'ESTIMATED_RUN_TIME_OVERLAP' AS allocation_method,
  sku_name,
  usage_unit,
  currency_code,
  round(sum(estimated_usage_quantity), 6) AS estimated_consumed_units,
  round(sum(estimated_list_cost), 4) AS estimated_databricks_list_cost
FROM priced_classic_usage
GROUP BY sku_name, usage_unit, currency_code
ORDER BY sku_name;

-- The monetary values above cover Databricks list-price consumption only.
-- For Classic Compute, add the Compute Engine cost of the driver/workers from
-- the GCP Cloud Billing export. Serverless prices already include the managed
-- cloud infrastructure in the Databricks serverless SKU.
