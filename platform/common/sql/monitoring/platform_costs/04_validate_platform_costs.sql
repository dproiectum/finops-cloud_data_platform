-- DATABRICKS ONLY. Execute after successful publication.
SELECT assert_true(COUNT(*) > 0, 'Platform costs are empty')
FROM finops_ops.monitoring.platform_cost_monthly;

SELECT assert_true(COUNT(DISTINCT provider) = 2, 'Both platform cost sources are required')
FROM finops_ops.monitoring.platform_cost_monthly;

SELECT assert_true(COUNT(*) = 0, 'Duplicate platform cost keys') FROM (
  SELECT month, provider, service, currency, cost_basis
  FROM finops_ops.monitoring.platform_cost_monthly
  GROUP BY month, provider, service, currency, cost_basis HAVING COUNT(*) > 1
);

SELECT month, provider, currency, COUNT(*) AS service_rows,
       SUM(cost_before_credits) AS cost_before_credits,
       SUM(credits) AS signed_credits, SUM(usage_quantity) AS net_dbu,
       MAX(collected_at) AS collected_at
FROM finops_ops.monitoring.platform_cost_monthly
GROUP BY month, provider, currency ORDER BY month, provider, currency;

SELECT * FROM finops_ops.monitoring.platform_cost_collection_run
ORDER BY finished_at DESC LIMIT 20;

-- Daily rollout: these controls require an export/collection in daily format.
SELECT assert_true(COUNT(*) > 0, 'Daily platform costs are empty')
FROM finops_ops.monitoring.platform_cost_daily;

SELECT assert_true(COUNT(*) = 0, 'Duplicate daily platform cost keys') FROM (
  SELECT usage_date, month, provider, service, currency, cost_basis
  FROM finops_ops.monitoring.platform_cost_daily
  GROUP BY usage_date, month, provider, service, currency, cost_basis HAVING COUNT(*) > 1
);

SELECT assert_true(COUNT(*) = 0, 'Inconsistent daily usage date')
FROM finops_ops.monitoring.platform_cost_daily
WHERE date_format(usage_date, 'yyyy-MM') <> month OR usage_date > current_date();

WITH daily_totals AS (
  SELECT month, provider, service, currency, cost_basis,
         SUM(cost_before_credits) AS cost, SUM(credits) AS credits,
         SUM(usage_quantity) AS dbu, MAX(collection_run_id) AS run_id
  FROM finops_ops.monitoring.platform_cost_daily
  GROUP BY month, provider, service, currency, cost_basis
)
SELECT assert_true(COUNT(*) = 0, 'Daily/monthly snapshots do not reconcile')
FROM finops_ops.monitoring.platform_cost_monthly AS monthly
FULL OUTER JOIN daily_totals AS daily
USING (month, provider, service, currency, cost_basis)
WHERE NOT (monthly.cost_before_credits <=> daily.cost)
   OR NOT (monthly.credits <=> daily.credits)
   OR NOT (monthly.usage_quantity <=> daily.dbu)
   OR NOT (monthly.collection_run_id <=> daily.run_id);

SELECT provider, currency, COUNT(*) AS daily_service_rows,
       MIN(usage_date) AS first_recorded_day, MAX(usage_date) AS last_recorded_day,
       MAX(collected_at) AS collected_at
FROM finops_ops.monitoring.platform_cost_daily
GROUP BY provider, currency;
