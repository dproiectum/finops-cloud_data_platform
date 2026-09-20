CREATE OR REPLACE TABLE {dm_cost_by_subscription_month} USING DELTA AS
SELECT
  f.billing_month,
  bs.sub_account_id AS subscription_id,
  bs.sub_account_name AS subscription_name,
  SUM(f.billed_cost) AS total_billed_cost,
  COUNT(DISTINCT r.resource_id) AS resource_count
FROM {fact_cost_usage} AS f
JOIN {dim_billing_scope} AS bs
  ON f.billing_scope_sk = bs.billing_scope_sk
JOIN {dim_resource} AS r
  ON f.resource_sk = r.resource_sk
GROUP BY f.billing_month, bs.sub_account_id, bs.sub_account_name;
