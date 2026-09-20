CREATE OR REPLACE TABLE {dm_executive_summary_monthly} USING DELTA AS
SELECT
  billing_month,
  COUNT(*) AS charge_lines,
  COUNT(DISTINCT ResourceId) AS active_resources,
  COUNT(DISTINCT ServiceName) AS consumed_services,
  coalesce(SUM(BilledCost), 0) AS billed_cost,
  coalesce(SUM(EffectiveCost), 0) AS effective_cost,
  coalesce(SUM(ListCost), 0) AS list_cost,
  coalesce(SUM(ListCost), 0) - coalesce(SUM(EffectiveCost), 0)
    AS total_savings_vs_list
FROM {silver_central}
WHERE billing_month IS NOT NULL
GROUP BY billing_month;
