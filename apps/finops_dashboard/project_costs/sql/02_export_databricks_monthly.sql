-- DATABRICKS SQL. Read-only: does not create/modify any table or grant.
-- Two project workspaces only; no workspace/job/cluster/user ID in the output.
-- Usage month follows usage_start_time, UTC. Free Genie is not priced or included.
-- Signed retractions/restatements stay signed; no record_type filter.
-- Prices must cover the WHOLE usage interval; missing pricing yields NULL cost.
-- Do not turn NULL cost into zero. This is a published-list estimate, not an invoice.
-- All periods are marked partial until source completeness is confirmed.
-- Source: https://docs.databricks.com/gcp/en/admin/system-tables/pricing
SET TIME ZONE 'UTC';

WITH priced_usage AS (
  SELECT
    date_format(usage.usage_start_time, 'yyyy-MM') AS month,
    usage.sku_name AS service,
    usage.usage_quantity,
    coalesce(prices.pricing.effective_list.default, prices.pricing.default) AS unit_price
  FROM system.billing.usage AS usage
  LEFT JOIN system.billing.list_prices AS prices
    ON usage.cloud = prices.cloud
   AND usage.sku_name = prices.sku_name
   AND usage.usage_unit = prices.usage_unit
   AND prices.currency_code = 'USD'
   AND usage.usage_start_time >= prices.price_start_time
   AND (prices.price_end_time IS NULL OR usage.usage_end_time <= prices.price_end_time)
  WHERE usage.workspace_id IN ('8259550392658865', '8259550830613689')
    AND usage.cloud = 'GCP'
    AND usage.usage_unit = 'DBU'
    AND usage.sku_name <> 'GENIE_FREE_USAGE'
)
SELECT
  month,
  'Databricks' AS provider,
  service,
  'USD' AS currency,
  CASE WHEN count_if(unit_price IS NULL) > 0 THEN NULL
       ELSE sum(usage_quantity * unit_price) END AS cost_before_credits,
  CAST(NULL AS DECIMAL(38, 12)) AS credits,
  sum(usage_quantity) AS usage_quantity,
  'DBU' AS usage_unit,
  'list_estimate' AS cost_basis,
  'partial' AS period_status
FROM priced_usage
GROUP BY month, service
ORDER BY month, service;
