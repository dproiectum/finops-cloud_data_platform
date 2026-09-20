CREATE OR REPLACE TABLE {dm_monthly_billing} USING DELTA AS
SELECT
  f.billing_month,
  SUM(f.billed_cost) AS monthly_billed_cost
FROM {fact_cost_usage} AS f
GROUP BY f.billing_month;
