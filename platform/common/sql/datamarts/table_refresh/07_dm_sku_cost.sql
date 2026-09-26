CREATE OR REPLACE TABLE {dm_sku_cost} USING DELTA AS
SELECT
  s.sku_id,
  s.meter_category,
  s.meter_name,
  SUM(f.billed_cost) AS total_billed_cost
FROM {fact_cost_usage} AS f
JOIN {dim_sku} AS s
  ON f.sku_sk = s.sku_sk
GROUP BY s.sku_id, s.meter_category, s.meter_name
ORDER BY total_billed_cost DESC
LIMIT 100;
