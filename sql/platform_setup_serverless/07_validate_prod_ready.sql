-- STEP 07 - Read-only preflight before the first PROD load.
-- Run this file once, while PROD is still empty. It must fail after PROD is loaded.

-- Expected table counts: Bronze=2, Silver=2, Gold=12, Datamart=14.
SELECT table_schema, count(*) AS table_count
FROM `finops_prod`.`information_schema`.`tables`
WHERE table_schema IN ('bronze', 'silver', 'gold', 'datamart')
GROUP BY table_schema
ORDER BY table_schema;

-- A temporary view keeps the 30-table inventory readable and reusable by the
-- blocking assertion below. It does not create a persistent Unity Catalog object.
CREATE OR REPLACE TEMP VIEW prod_preload_row_counts AS
SELECT 'bronze.focus_daily_raw' AS table_name, count(*) AS row_count FROM `finops_prod`.`bronze`.`focus_daily_raw`
UNION ALL SELECT 'bronze.focus_billing_raw', count(*) FROM `finops_prod`.`bronze`.`focus_billing_raw`
UNION ALL SELECT 'silver.focus_cost_usage', count(*) FROM `finops_prod`.`silver`.`focus_cost_usage`
UNION ALL SELECT 'silver.focus_cost_usage_central', count(*) FROM `finops_prod`.`silver`.`focus_cost_usage_central`
UNION ALL SELECT 'gold.dim_date', count(*) FROM `finops_prod`.`gold`.`dim_date`
UNION ALL SELECT 'gold.dim_billing_scope', count(*) FROM `finops_prod`.`gold`.`dim_billing_scope`
UNION ALL SELECT 'gold.dim_resource', count(*) FROM `finops_prod`.`gold`.`dim_resource`
UNION ALL SELECT 'gold.dim_service', count(*) FROM `finops_prod`.`gold`.`dim_service`
UNION ALL SELECT 'gold.dim_sku', count(*) FROM `finops_prod`.`gold`.`dim_sku`
UNION ALL SELECT 'gold.dim_location', count(*) FROM `finops_prod`.`gold`.`dim_location`
UNION ALL SELECT 'gold.dim_commitment_discount', count(*) FROM `finops_prod`.`gold`.`dim_commitment_discount`
UNION ALL SELECT 'gold.dim_pricing', count(*) FROM `finops_prod`.`gold`.`dim_pricing`
UNION ALL SELECT 'gold.dim_charge_type', count(*) FROM `finops_prod`.`gold`.`dim_charge_type`
UNION ALL SELECT 'gold.dim_tag', count(*) FROM `finops_prod`.`gold`.`dim_tag`
UNION ALL SELECT 'gold.bridge_resource_tag', count(*) FROM `finops_prod`.`gold`.`bridge_resource_tag`
UNION ALL SELECT 'gold.fact_finops_cost_usage', count(*) FROM `finops_prod`.`gold`.`fact_finops_cost_usage`
UNION ALL SELECT 'datamart.dm_monthly_billing', count(*) FROM `finops_prod`.`datamart`.`dm_monthly_billing`
UNION ALL SELECT 'datamart.dm_daily_billing', count(*) FROM `finops_prod`.`datamart`.`dm_daily_billing`
UNION ALL SELECT 'datamart.dm_cost_by_scope_service_month', count(*) FROM `finops_prod`.`datamart`.`dm_cost_by_scope_service_month`
UNION ALL SELECT 'datamart.dm_top_services', count(*) FROM `finops_prod`.`datamart`.`dm_top_services`
UNION ALL SELECT 'datamart.dm_top_resources', count(*) FROM `finops_prod`.`datamart`.`dm_top_resources`
UNION ALL SELECT 'datamart.dm_cost_by_charge_type', count(*) FROM `finops_prod`.`datamart`.`dm_cost_by_charge_type`
UNION ALL SELECT 'datamart.dm_sku_cost', count(*) FROM `finops_prod`.`datamart`.`dm_sku_cost`
UNION ALL SELECT 'datamart.dm_savings_monthly', count(*) FROM `finops_prod`.`datamart`.`dm_savings_monthly`
UNION ALL SELECT 'datamart.dm_executive_summary_monthly', count(*) FROM `finops_prod`.`datamart`.`dm_executive_summary_monthly`
UNION ALL SELECT 'datamart.dm_top_resources_monthly', count(*) FROM `finops_prod`.`datamart`.`dm_top_resources_monthly`
UNION ALL SELECT 'datamart.dm_data_quality_monthly', count(*) FROM `finops_prod`.`datamart`.`dm_data_quality_monthly`
UNION ALL SELECT 'datamart.dm_cost_by_resource_group_month', count(*) FROM `finops_prod`.`datamart`.`dm_cost_by_resource_group_month`
UNION ALL SELECT 'datamart.dm_cost_by_subscription_month', count(*) FROM `finops_prod`.`datamart`.`dm_cost_by_subscription_month`
UNION ALL SELECT 'datamart.dm_cost_by_application_owner_month', count(*) FROM `finops_prod`.`datamart`.`dm_cost_by_application_owner_month`;

-- Expected result: 30 rows, all with row_count = 0.
SELECT table_name, row_count
FROM prod_preload_row_counts
ORDER BY table_name;

-- Expected result: five rows, all with row_count = 0 for environment=prod.
SELECT 'pipeline_run' AS table_name, count(*) AS row_count
FROM `finops_ops`.`audit`.`pipeline_run` WHERE environment = 'prod'
UNION ALL SELECT 'month_snapshot', count(*)
FROM `finops_ops`.`audit`.`month_snapshot` WHERE environment = 'prod'
UNION ALL SELECT 'monthly_reconciliation', count(*)
FROM `finops_ops`.`audit`.`monthly_reconciliation` WHERE environment = 'prod'
UNION ALL SELECT 'month_status', count(*)
FROM `finops_ops`.`audit`.`month_status` WHERE environment = 'prod'
UNION ALL SELECT 'file_archive', count(*)
FROM `finops_ops`.`audit`.`file_archive` WHERE environment = 'prod'
ORDER BY table_name;

-- Blocking preflight controls. Successful assert_true calls return NULL.
WITH expected(schema_name, expected_count) AS (
  SELECT * FROM VALUES
    ('bronze', 2),
    ('silver', 2),
    ('gold', 12),
    ('datamart', 14)
), actual AS (
  SELECT table_schema AS schema_name, count(*) AS actual_count
  FROM `finops_prod`.`information_schema`.`tables`
  WHERE table_schema IN ('bronze', 'silver', 'gold', 'datamart')
  GROUP BY table_schema
), mismatches AS (
  SELECT expected.schema_name
  FROM expected
  LEFT JOIN actual USING (schema_name)
  WHERE actual.actual_count IS NULL
     OR actual.actual_count <> expected.expected_count
)
SELECT assert_true(
  count(*) = 0,
  'CONTROL FAILED: PROD does not contain the expected 30 tables'
)
FROM mismatches;

SELECT assert_true(
  count(*) = 0,
  'CONTROL FAILED: at least one PROD business table is not empty'
)
FROM prod_preload_row_counts
WHERE row_count <> 0;

SELECT assert_true(
  (SELECT count(*) FROM `finops_ops`.`audit`.`pipeline_run` WHERE environment = 'prod') = 0
  AND (SELECT count(*) FROM `finops_ops`.`audit`.`month_snapshot` WHERE environment = 'prod') = 0
  AND (SELECT count(*) FROM `finops_ops`.`audit`.`monthly_reconciliation` WHERE environment = 'prod') = 0
  AND (SELECT count(*) FROM `finops_ops`.`audit`.`month_status` WHERE environment = 'prod') = 0
  AND (SELECT count(*) FROM `finops_ops`.`audit`.`file_archive` WHERE environment = 'prod') = 0,
  'CONTROL FAILED: PROD audit history already exists before its first load'
);

DROP VIEW prod_preload_row_counts;

