CREATE OR REPLACE TABLE {dm_top_services} USING DELTA AS
SELECT
  s.service_category,
  s.service_name,
  SUM(f.billed_cost) AS total_billed_cost
FROM {fact_cost_usage} AS f
JOIN {dim_service} AS s
  ON f.service_sk = s.service_sk
GROUP BY s.service_category, s.service_name
ORDER BY total_billed_cost DESC
LIMIT 30;
