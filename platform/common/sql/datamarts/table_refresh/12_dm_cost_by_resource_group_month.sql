CREATE OR REPLACE TABLE {dm_cost_by_resource_group_month} USING DELTA AS
SELECT
  f.billing_month,
  r.resource_group_name,
  SUM(f.billed_cost) AS total_billed_cost,
  COUNT(DISTINCT r.resource_id) AS resource_count
FROM {fact_cost_usage} AS f
JOIN {dim_resource} AS r
  ON f.resource_sk = r.resource_sk
GROUP BY f.billing_month, r.resource_group_name;
