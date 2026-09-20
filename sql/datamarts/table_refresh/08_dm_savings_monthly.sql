CREATE OR REPLACE TABLE {dm_savings_monthly} USING DELTA AS
SELECT
  billing_month,
  coalesce(SUM(ListCost), 0) AS list_cost,
  coalesce(SUM(ContractedCost), 0) AS contracted_cost,
  coalesce(SUM(EffectiveCost), 0) AS effective_cost,
  coalesce(SUM(ListCost), 0) - coalesce(SUM(ContractedCost), 0)
    AS negotiated_savings,
  coalesce(SUM(ContractedCost), 0) - coalesce(SUM(EffectiveCost), 0)
    AS commitment_savings,
  coalesce(SUM(ListCost), 0) - coalesce(SUM(EffectiveCost), 0)
    AS total_savings_vs_list,
  CASE
    WHEN coalesce(SUM(ListCost), 0) = 0 THEN 0
    ELSE 100 * (coalesce(SUM(ListCost), 0) - coalesce(SUM(EffectiveCost), 0))
      / SUM(ListCost)
  END AS savings_rate
FROM {silver_central}
WHERE billing_month IS NOT NULL
GROUP BY billing_month;
