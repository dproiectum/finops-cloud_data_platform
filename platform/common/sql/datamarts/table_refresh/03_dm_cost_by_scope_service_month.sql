CREATE OR REPLACE TABLE {dm_cost_by_scope_service_month} USING DELTA AS
SELECT
  f.billing_month,
  bs.cost_center,
  bs.customer_name,
  s.service_category,
  s.service_name,
  SUM(f.billed_cost) AS total_billed_cost
FROM {fact_cost_usage} AS f
JOIN {dim_billing_scope} AS bs
  ON f.billing_scope_sk = bs.billing_scope_sk
JOIN {dim_service} AS s
  ON f.service_sk = s.service_sk
GROUP BY f.billing_month, bs.cost_center, bs.customer_name,
         s.service_category, s.service_name;
