-- DATABRICKS SQL. Read-only: does not create/modify any table or grant.
-- Two project workspaces only; no workspace/job/cluster/user ID in the output.
-- Daily grain follows usage_start_time, UTC; monthly totals derive from these rows.
-- Intervals crossing midnight are attributed to their UTC start day, not prorated.
-- Free Genie is not priced or included.
-- Signed retractions/restatements stay signed; no record_type filter.
-- Prices must cover the WHOLE usage interval; missing/ambiguous pricing yields NULL cost.
-- Explicit decimal price arithmetic, never implicit STRING-to-DOUBLE conversion.
-- Do not turn NULL cost into zero. This is a published-list estimate, not an invoice.
-- All periods are marked partial until source completeness is confirmed.
-- Source: https://docs.databricks.com/gcp/en/admin/system-tables/pricing
WITH priced_usage AS (
  SELECT
    date_format(usage.usage_start_time, 'yyyy-MM-dd') AS usage_date,
    date_format(usage.usage_start_time, 'yyyy-MM') AS month,
    usage.sku_name AS service,
    usage.usage_quantity,
    CASE WHEN count(prices.sku_name) = 1 AND
              min(try_cast(coalesce(prices.pricing.effective_list.default, prices.pricing.default) AS DECIMAL(18,9))) =
              min(try_cast(coalesce(prices.pricing.effective_list.default, prices.pricing.default) AS DECIMAL(38,18)))
         THEN min(try_cast(coalesce(prices.pricing.effective_list.default, prices.pricing.default) AS DECIMAL(18,9)))
         ELSE NULL END AS unit_price
  FROM system.billing.usage AS usage
  LEFT JOIN system.billing.list_prices AS prices
    ON usage.cloud = prices.cloud
   AND usage.sku_name = prices.sku_name
   AND usage.usage_unit = prices.usage_unit
   AND prices.currency_code = 'USD'
   AND usage.usage_start_time >= prices.price_start_time
   AND (prices.price_end_time IS NULL OR
        (usage.usage_start_time < prices.price_end_time AND usage.usage_end_time <= prices.price_end_time))
  WHERE usage.workspace_id IN ('8259550392658865', '8259550830613689')
    AND usage.usage_start_time >= TIMESTAMP '2026-09-01 00:00:00'
    AND usage.usage_start_time < current_timestamp()
    AND usage.cloud = 'GCP'
    AND usage.usage_unit = 'DBU'
    AND usage.sku_name <> 'GENIE_FREE_USAGE'
  GROUP BY usage.record_id, date_format(usage.usage_start_time, 'yyyy-MM-dd'),
           date_format(usage.usage_start_time, 'yyyy-MM'),
           usage.sku_name, usage.usage_quantity
)
SELECT
  usage_date,
  month,
  'Databricks' AS provider,
  service,
  'USD' AS currency,
  CASE WHEN count_if(unit_price IS NULL OR try_cast(usage_quantity AS DECIMAL(30,18)) IS NULL) > 0 THEN NULL
       ELSE CAST(sum(try_cast(usage_quantity AS DECIMAL(30,18)) * unit_price) AS DECIMAL(38,16)) END AS cost_before_credits,
  CAST(NULL AS DECIMAL(38, 12)) AS credits,
  sum(usage_quantity) AS usage_quantity,
  'DBU' AS usage_unit,
  'list_estimate' AS cost_basis,
  'partial' AS period_status
FROM priced_usage
GROUP BY usage_date, month, service
ORDER BY usage_date, service;
