-- PLATFORM MONITORING / STEP 3: read-only controls after script 03.
-- Run with your own identity; this does not test the dashboard service principal.
-- Successful assert_true returns NULL. Empty telemetry is NOT zero consumption.
-- All record types are included, including signed billing corrections.
-- Billing can arrive/correct later: these controls describe the available data
-- at execution, not a final invoice. October 2026 is still an open month.

-- 1. Require matching records and preserve each monthly workspace/SKU/product.
WITH expected AS (
    SELECT
        date_format(usage_date, 'yyyy-MM') AS usage_month,
        workspace_id, sku_name, billing_origin_product, usage_unit,
        sum(usage_quantity) AS net_dbu,
        count(*) AS billing_records,
        min(usage_date) AS first_available_usage_date,
        max(usage_date) AS last_available_usage_date
    FROM system.billing.usage
    WHERE cloud = 'GCP'
      AND workspace_id IN ('8259550392658865', '8259550830613689')
      AND usage_date >= DATE '2026-09-01'
      AND usage_unit = 'DBU'
    GROUP BY date_format(usage_date, 'yyyy-MM'), workspace_id,
             sku_name, billing_origin_product, usage_unit
), mismatches AS (
    SELECT 1
    FROM expected AS e
    FULL OUTER JOIN finops_ops.monitoring.v_databricks_consumption_monthly AS v
      ON e.usage_month <=> v.usage_month
     AND e.workspace_id <=> v.workspace_id
     AND e.sku_name <=> v.sku_name
     AND e.billing_origin_product <=> v.billing_origin_product
     AND e.usage_unit <=> v.usage_unit
    WHERE NOT (e.net_dbu <=> v.net_dbu)
       OR NOT (e.billing_records <=> v.billing_records)
       OR NOT (e.first_available_usage_date <=> v.first_available_usage_date)
       OR NOT (e.last_available_usage_date <=> v.last_available_usage_date)
       OR NOT ((e.sku_name = 'GENIE_FREE_USAGE') <=> v.is_genie_free_usage)
)
SELECT assert_true(
    (SELECT count(*) FROM expected) > 0
    AND (SELECT count(*) FROM mismatches) = 0,
    'CONTROL FAILED: DBU telemetry is empty or monthly source/view totals differ'
) AS databricks_consumption_control;

-- 2. Separate Genie free usage from other DBU SKUs; no price conversion here.
-- Do not add Azure quantities to DBUs or compare workspace costs from DBUs alone.
SELECT
    usage_month, workspace_label, sku_name, billing_origin_product, usage_unit,
    is_genie_free_usage, net_dbu, billing_records,
    first_available_usage_date, last_available_usage_date
FROM finops_ops.monitoring.v_databricks_consumption_monthly
ORDER BY usage_month DESC, workspace_label, sku_name, billing_origin_product;
