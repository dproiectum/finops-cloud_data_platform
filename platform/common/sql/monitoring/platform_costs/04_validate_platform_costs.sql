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
