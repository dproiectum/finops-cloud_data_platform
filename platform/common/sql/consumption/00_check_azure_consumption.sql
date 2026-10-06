-- CONSUMPTION / STEP 1A: read-only feasibility check, workspace-belgium, PROD.
-- Run statements in order in SQL Editor on the existing SQL Warehouse.
-- No source upload, ingestion run, table/view replacement or permission change.
-- If statement 1 does not return PASS, stop and share that result.
-- These are synthetic Azure consumption records, NOT energy/carbon measurements.

-- 1. Verify fields on the already published allocation view, not on local files.
-- Metadata can also be invisible when your account lacks the required access.
SELECT
    'AZURE_CONSUMPTION_FIELDS' AS control_name,
    CASE WHEN count(DISTINCT lower(column_name)) = 6
         THEN 'PASS'
         ELSE 'CHECK_REQUIRED: missing fields, missing view or insufficient access'
    END AS status,
    sort_array(collect_set(column_name)) AS available_fields
FROM finops_prod.information_schema.columns
WHERE table_schema = 'gold'
  AND table_name = 'v_cost_allocation'
  AND lower(column_name) IN (
      'billing_month', 'chargecategory', 'servicename', 'skuid',
      'consumedquantity', 'consumedunit'
  );

-- 2. Monthly coverage: evaluate quantity/unit completeness on Usage charges.
-- Missing data is not zero; other charge categories are not physical consumption.
WITH monthly AS (
    SELECT
        billing_month,
        count(*) AS charge_rows,
        count_if(ChargeCategory = 'Usage') AS usage_rows,
        count_if(
            ChargeCategory = 'Usage'
            AND ConsumedQuantity IS NOT NULL
            AND nullif(trim(ConsumedUnit), '') IS NOT NULL
            AND lower(trim(ConsumedUnit)) <> 'unknown'
        ) AS usable_usage_rows,
        count_if(
            ChargeCategory = 'Usage'
            AND (
                ConsumedQuantity IS NULL
                OR nullif(trim(ConsumedUnit), '') IS NULL
                OR lower(trim(ConsumedUnit)) = 'unknown'
            )
        ) AS missing_quantity_or_unit_rows,
        count_if(ChargeCategory = 'Usage' AND ConsumedQuantity < 0)
            AS negative_quantity_rows,
        count_if(
            ChargeCategory <> 'Usage' AND ConsumedQuantity IS NOT NULL
        ) AS non_usage_rows_with_quantity
    FROM finops_prod.gold.v_cost_allocation
    GROUP BY billing_month
)
SELECT *,
    CASE WHEN usage_rows = 0 THEN NULL
         ELSE round(100.0 * usable_usage_rows / usage_rows, 2)
    END AS usable_usage_coverage_pct,
    CASE
      WHEN billing_month IS NULL THEN 'CHECK_REQUIRED: missing billing month'
      WHEN usage_rows = 0 THEN 'NO_USAGE_ROWS'
      WHEN usable_usage_rows = 0 THEN 'NO_USABLE_USAGE'
      WHEN missing_quantity_or_unit_rows > 0 THEN 'READY_WITH_MISSING_VALUES'
      ELSE 'READY'
    END AS consumption_status
FROM monthly
ORDER BY billing_month;

-- 3. Sample for the latest loaded month, not necessarily a closed/full month.
-- Keep service, SKU and unit separate: never sum Hours, GB and Units together.
-- Signed quantities are retained; no absolute-value or zero-clipping adjustment.
WITH latest_month AS (
    SELECT max(billing_month) AS billing_month
    FROM finops_prod.gold.v_cost_allocation
)
SELECT
    source.billing_month,
    source.ServiceName AS service_name,
    source.SkuId AS sku_id,
    trim(source.ConsumedUnit) AS consumed_unit,
    sum(source.ConsumedQuantity) AS consumed_quantity,
    count(*) AS usage_rows
FROM finops_prod.gold.v_cost_allocation AS source
JOIN latest_month ON source.billing_month = latest_month.billing_month
WHERE source.ChargeCategory = 'Usage'
  AND source.ConsumedQuantity IS NOT NULL
  AND nullif(trim(source.ConsumedUnit), '') IS NOT NULL
  AND lower(trim(source.ConsumedUnit)) <> 'unknown'
GROUP BY source.billing_month, source.ServiceName, source.SkuId,
         trim(source.ConsumedUnit)
ORDER BY service_name, sku_id, consumed_unit
LIMIT 50;
