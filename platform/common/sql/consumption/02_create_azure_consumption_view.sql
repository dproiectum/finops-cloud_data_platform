-- CONSUMPTION / STEP 2A: manual, additive setup in workspace-belgium.
-- Run with your existing account in SQL Editor, not with the public app identity.
-- This ordinary view stores no data and does not change the ingestion pipelines.
-- Prerequisites: PROD Gold allocation view, Tags and ChargePeriodStart available.
-- Keep application, service, SKU and unit separate. Never sum heterogeneous units.
-- Missing measurements remain NULL, not zero. Signed corrections are preserved.
-- This is NOT an access-control policy: the protected app must apply its live
-- environment/application authorization BEFORE aggregating across applications.
-- No emails, raw Tags, source paths, energy or carbon estimates are exposed.
-- OR REPLACE affects only this new view. Re-run as its owner; review any future
-- grants separately because replacement can reset view-specific privileges.

CREATE OR REPLACE VIEW finops_prod.datamart.v_consumption_monthly
COMMENT 'Synthetic Azure Usage consumption by application, service, SKU and unit; loaded periods only, not carbon'
AS
WITH usage_rows AS (
    SELECT
        'prod' AS environment,
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
        ConsumedQuantity AS consumed_quantity,
        to_date(ChargePeriodStart) AS charge_date
    FROM finops_prod.gold.v_cost_allocation
    WHERE ChargeCategory = 'Usage'
)
SELECT
    environment,
    billing_month,
    application_code,
    service_name,
    sku_id,
    consumed_unit,
    sum(CASE WHEN consumed_unit IS NOT NULL THEN consumed_quantity END)
        AS consumed_quantity,
    count(*) AS usage_rows,
    count_if(consumed_quantity IS NOT NULL AND consumed_unit IS NOT NULL)
        AS measured_usage_rows,
    count_if(consumed_quantity IS NULL OR consumed_unit IS NULL)
        AS missing_measurement_rows,
    count_if(consumed_quantity < 0 AND consumed_unit IS NOT NULL)
        AS negative_quantity_rows,
    min(charge_date) AS first_loaded_charge_date,
    max(charge_date) AS last_loaded_charge_date
FROM usage_rows
GROUP BY environment, billing_month, application_code, service_name, sku_id,
         consumed_unit;
