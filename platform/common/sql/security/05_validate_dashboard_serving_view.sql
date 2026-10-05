-- Read-only view consistency, not end-to-end authorization evidence.
-- Stop on any error. Execute after 04_create_dashboard_serving_view.sql.

WITH source AS (
    SELECT COUNT(*) AS rows, coalesce(SUM(BilledCost), 0) AS billed,
           coalesce(SUM(ListCost), 0) AS list,
           coalesce(SUM(ContractedCost), 0) AS contracted,
           coalesce(SUM(EffectiveCost), 0) AS effective
    FROM finops_prod.silver.focus_cost_usage_central
), serving AS (
    SELECT COUNT(*) AS rows, coalesce(SUM(billed_cost), 0) AS billed,
           coalesce(SUM(list_cost), 0) AS list,
           coalesce(SUM(contracted_cost), 0) AS contracted,
           coalesce(SUM(effective_cost), 0) AS effective
    FROM finops_prod.datamart.v_dashboard_charge_scoped
)
SELECT assert_true(
    source.rows = serving.rows AND source.billed = serving.billed
      AND source.list = serving.list AND source.contracted = serving.contracted
      AND source.effective = serving.effective,
    'SERVING CONTROL FAILED: charge rows or cost columns changed'
)
FROM source CROSS JOIN serving;

-- Allocation and monetary totals must also agree with the shared Gold policy.
WITH expected AS (
    SELECT billing_month, cost_center_allocated AS cost_center,
           COUNT(*) AS rows, coalesce(SUM(BilledCost), 0) AS billed
    FROM finops_prod.gold.v_cost_allocation
    GROUP BY billing_month, cost_center_allocated
), serving AS (
    SELECT billing_month, cost_center, COUNT(*) AS rows,
           coalesce(SUM(billed_cost), 0) AS billed
    FROM finops_prod.datamart.v_dashboard_charge_scoped
    GROUP BY billing_month, cost_center
)
SELECT assert_true(COUNT(*) = 0,
    'SERVING CONTROL FAILED: allocation differs from the shared Gold policy')
FROM expected FULL OUTER JOIN serving
  ON expected.billing_month = serving.billing_month
 AND expected.cost_center = serving.cost_center
WHERE expected.billing_month IS NULL OR serving.billing_month IS NULL
   OR expected.rows <> serving.rows OR expected.billed <> serving.billed;

-- Public datamart and protected charge-grain mode must agree before filtering.
WITH serving AS (
    SELECT billing_month, cost_center, coalesce(SUM(billed_cost), 0) AS billed
    FROM finops_prod.datamart.v_dashboard_charge_scoped
    GROUP BY billing_month, cost_center
), public AS (
    SELECT billing_month, cost_center, coalesce(SUM(total_billed_cost), 0) AS billed
    FROM finops_prod.datamart.dm_cost_by_scope_service_month
    GROUP BY billing_month, cost_center
)
SELECT assert_true(COUNT(*) = 0,
    'SERVING CONTROL FAILED: public and protected allocation totals differ')
FROM serving FULL OUTER JOIN public
  ON serving.billing_month = public.billing_month
 AND serving.cost_center = public.cost_center
WHERE serving.billing_month IS NULL OR public.billing_month IS NULL
   OR serving.billed <> public.billed;

SELECT assert_true(
    COUNT(DISTINCT application_code) = 2,
    'SERVING CONTROL FAILED: both demo applications must have charge-grain records'
)
FROM finops_prod.datamart.v_dashboard_charge_scoped
WHERE application_code IN ('APP00013057', 'BSN0003965');

-- Reference totals for manually comparing the two application-owner sessions.
SELECT application_code, billing_month, COUNT(*) AS charge_lines,
       coalesce(SUM(billed_cost), 0) AS billed_cost,
       coalesce(SUM(list_cost), 0) AS list_cost,
       coalesce(SUM(contracted_cost), 0) AS contracted_cost,
       coalesce(SUM(effective_cost), 0) AS effective_cost,
       coalesce(SUM(list_cost), 0) - coalesce(SUM(effective_cost), 0) AS realized_savings
FROM finops_prod.datamart.v_dashboard_charge_scoped
WHERE application_code IN ('APP00013057', 'BSN0003965')
GROUP BY application_code, billing_month
ORDER BY application_code, billing_month;

SELECT 'PASS: serving view preserves source costs; test application enforcement separately'
    AS result;
