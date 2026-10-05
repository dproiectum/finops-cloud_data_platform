CREATE OR REPLACE TABLE {dm_cost_by_scope_service_month} USING DELTA AS
SELECT
  billing_month,
  cost_center_allocated AS cost_center,
  coalesce(nullif(trim(x_CustomerName), ''), 'Unknown') AS customer_name,
  coalesce(nullif(trim(ServiceCategory), ''), 'Unknown') AS service_category,
  coalesce(nullif(trim(ServiceName), ''), 'Unknown') AS service_name,
  SUM(BilledCost) AS total_billed_cost
FROM {cost_allocation_view}
GROUP BY billing_month, cost_center_allocated,
  coalesce(nullif(trim(x_CustomerName), ''), 'Unknown'),
  coalesce(nullif(trim(ServiceCategory), ''), 'Unknown'),
  coalesce(nullif(trim(ServiceName), ''), 'Unknown');
