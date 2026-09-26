CREATE OR REPLACE TABLE {dm_daily_billing} USING DELTA AS
SELECT
  d.date,
  SUM(f.billed_cost) AS daily_billed_cost
FROM {fact_cost_usage} AS f
JOIN {dim_date} AS d
  ON f.charge_period_start_date_sk = d.date_sk
GROUP BY d.date;
