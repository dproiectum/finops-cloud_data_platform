CREATE OR REPLACE TABLE {dm_top_resources} USING DELTA AS
SELECT
  r.resource_group_name,
  r.resource_name,
  l.region,
  SUM(f.billed_cost) AS total_billed_cost
FROM {fact_cost_usage} AS f
JOIN {dim_resource} AS r
  ON f.resource_sk = r.resource_sk
JOIN {dim_location} AS l
  ON f.location_sk = l.location_sk
GROUP BY r.resource_group_name, r.resource_name, l.region
ORDER BY total_billed_cost DESC
LIMIT 100;
