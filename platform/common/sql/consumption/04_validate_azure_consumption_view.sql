-- CONSUMPTION / STEP 2C: read-only controls after script 02.
-- Execute all three statements. Successful assert_true returns NULL, not FAIL.
-- Stop on any CONTROL FAILED error and share it; no pipeline needs re-running.
-- Reconcile each application/service/SKU/unit, including NULL dimensions.
-- The last table reports measurement coverage, NOT full-month completeness.

-- 1. Require loaded Usage rows and account for every measurement/missing row.
WITH source_count AS (
    SELECT count(*) AS usage_rows
    FROM finops_prod.gold.v_cost_allocation
    WHERE ChargeCategory = 'Usage'
), view_counts AS (
    SELECT
        sum(usage_rows) AS usage_rows,
        count_if(
            environment <> 'prod' OR environment IS NULL
            OR usage_rows <= 0
            OR measured_usage_rows < 0 OR missing_measurement_rows < 0
            OR negative_quantity_rows < 0
            OR negative_quantity_rows > measured_usage_rows
            OR measured_usage_rows + missing_measurement_rows <> usage_rows
            OR (consumed_unit IS NULL AND consumed_quantity IS NOT NULL)
        ) AS invalid_groups
    FROM finops_prod.datamart.v_consumption_monthly
)
SELECT assert_true(
    source_count.usage_rows > 0
    AND source_count.usage_rows = view_counts.usage_rows
    AND view_counts.invalid_groups = 0,
    'CONTROL FAILED: Azure consumption rows or measurement counters differ'
) AS azure_row_control
FROM source_count CROSS JOIN view_counts;

-- 2. Quantities must match the source, with their signs and NULLs preserved.
WITH normalized_source AS (
    SELECT
        billing_month,
        nullif(trim(element_at(
            from_json(Tags, 'MAP<STRING,STRING>'),
            'ApplicationCode-Symphony'
        )), '') AS application_code,
        ServiceName AS service_name,
        SkuId AS sku_id,
        CASE WHEN lower(trim(ConsumedUnit)) = 'unknown' THEN NULL
             ELSE nullif(trim(ConsumedUnit), '')
        END AS consumed_unit,
        ConsumedQuantity AS consumed_quantity
    FROM finops_prod.gold.v_cost_allocation
    WHERE ChargeCategory = 'Usage'
), expected AS (
    SELECT
        billing_month, application_code, service_name, sku_id, consumed_unit,
        sum(CASE WHEN consumed_unit IS NOT NULL THEN consumed_quantity END)
            AS consumed_quantity,
        count(*) AS usage_rows,
        count_if(consumed_quantity IS NOT NULL AND consumed_unit IS NOT NULL)
            AS measured_usage_rows,
        count_if(consumed_quantity IS NULL OR consumed_unit IS NULL)
            AS missing_measurement_rows,
        count_if(consumed_quantity < 0 AND consumed_unit IS NOT NULL)
            AS negative_quantity_rows
    FROM normalized_source
    GROUP BY billing_month, application_code, service_name, sku_id, consumed_unit
), mismatches AS (
    SELECT 1
    FROM expected AS e
    FULL OUTER JOIN finops_prod.datamart.v_consumption_monthly AS v
      ON e.billing_month <=> v.billing_month
     AND e.application_code <=> v.application_code
     AND e.service_name <=> v.service_name
     AND e.sku_id <=> v.sku_id
     AND e.consumed_unit <=> v.consumed_unit
    WHERE NOT (e.usage_rows <=> v.usage_rows)
       OR NOT (e.consumed_quantity <=> v.consumed_quantity)
       OR NOT (e.measured_usage_rows <=> v.measured_usage_rows)
       OR NOT (e.missing_measurement_rows <=> v.missing_measurement_rows)
       OR NOT (e.negative_quantity_rows <=> v.negative_quantity_rows)
)
SELECT assert_true(
    count(*) = 0,
    'CONTROL FAILED: Azure consumption differs by application, service, SKU or unit'
) AS azure_quantity_control
FROM mismatches;

-- 3. Human-readable result. Dates show available rows only, not month closure.
SELECT
    billing_month,
    sum(usage_rows) AS usage_rows,
    sum(measured_usage_rows) AS measured_usage_rows,
    sum(missing_measurement_rows) AS missing_measurement_rows,
    sum(negative_quantity_rows) AS negative_quantity_rows,
    round(100.0 * sum(measured_usage_rows) / sum(usage_rows), 2)
        AS measured_usage_coverage_pct,
    min(first_loaded_charge_date) AS first_loaded_charge_date,
    max(last_loaded_charge_date) AS last_loaded_charge_date,
    CASE WHEN sum(measured_usage_rows) = 0 THEN 'NO_USABLE_USAGE'
         WHEN sum(missing_measurement_rows) > 0 THEN 'READY_WITH_MISSING_VALUES'
         ELSE 'READY'
    END AS measurement_status
FROM finops_prod.datamart.v_consumption_monthly
GROUP BY billing_month
ORDER BY billing_month;
