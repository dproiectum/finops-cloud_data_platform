CREATE OR REPLACE TABLE {dm_savings_monthly} USING DELTA AS
WITH classified AS (
  SELECT
    billing_month, ListCost, ContractedCost, EffectiveCost,
    -- Each source row belongs to exactly one effective-cost component.
    -- These are allocations of EffectiveCost, not upfront contract purchases.
    CASE
      WHEN ChargeCategory = 'Adjustment' THEN 'adjustment'
      WHEN ChargeCategory = 'Usage' AND PricingCategory = 'Commitment-Based'
        AND CommitmentDiscountType = 'Reservation' THEN 'reservation'
      WHEN ChargeCategory = 'Usage' AND PricingCategory = 'Commitment-Based'
        AND CommitmentDiscountType = 'Savings Plan' THEN 'savings_plan'
      WHEN ChargeCategory = 'Usage' AND PricingCategory = 'On-Demand'
        THEN 'usage_on_demand'
      WHEN ChargeCategory = 'Usage' AND PricingCategory = 'Dynamic'
        THEN 'usage_dynamic'
      ELSE 'other'
    END AS effective_cost_component
  FROM {silver_central}
  WHERE billing_month IS NOT NULL
)
SELECT
  billing_month,
  coalesce(SUM(ListCost), 0) AS list_cost,
  coalesce(SUM(ContractedCost), 0) AS contracted_cost,
  coalesce(SUM(EffectiveCost), 0) AS effective_cost,
  coalesce(SUM(ListCost), 0) - coalesce(SUM(ContractedCost), 0)
    AS negotiated_savings,
  coalesce(SUM(CASE WHEN effective_cost_component = 'reservation'
    THEN EffectiveCost ELSE 0 END), 0) AS reservation,
  coalesce(SUM(CASE WHEN effective_cost_component = 'savings_plan'
    THEN EffectiveCost ELSE 0 END), 0) AS savings_plan,
  coalesce(SUM(CASE WHEN effective_cost_component = 'usage_on_demand'
    THEN EffectiveCost ELSE 0 END), 0) AS usage_on_demand,
  coalesce(SUM(CASE WHEN effective_cost_component = 'usage_dynamic'
    THEN EffectiveCost ELSE 0 END), 0) AS usage_dynamic,
  coalesce(SUM(CASE WHEN effective_cost_component = 'adjustment'
    THEN EffectiveCost ELSE 0 END), 0) AS adjustment,
  coalesce(SUM(CASE WHEN effective_cost_component = 'other'
    THEN EffectiveCost ELSE 0 END), 0) AS other_effective_cost,
  -- Retained for existing consumers, but no longer displayed in the dashboard.
  coalesce(SUM(ContractedCost), 0) - coalesce(SUM(EffectiveCost), 0)
    AS commitment_savings,
  coalesce(SUM(ListCost), 0) - coalesce(SUM(EffectiveCost), 0)
    AS total_savings_vs_list,
  CASE
    WHEN coalesce(SUM(ListCost), 0) = 0 THEN 0
    ELSE 100 * (coalesce(SUM(ListCost), 0) - coalesce(SUM(EffectiveCost), 0))
      / SUM(ListCost)
  END AS savings_rate
FROM classified
GROUP BY billing_month;
