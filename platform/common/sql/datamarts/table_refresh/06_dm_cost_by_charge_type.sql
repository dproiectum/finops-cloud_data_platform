CREATE OR REPLACE TABLE {dm_cost_by_charge_type} USING DELTA AS
SELECT
  f.billing_month,
  c.charge_category,
  c.charge_subcategory,
  c.charge_frequency,
  SUM(f.billed_cost) AS total_billed_cost
FROM {fact_cost_usage} AS f
JOIN {dim_charge_type} AS c
  ON f.charge_type_sk = c.charge_type_sk
GROUP BY f.billing_month, c.charge_category,
         c.charge_subcategory, c.charge_frequency;
