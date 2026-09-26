-- STEP 06 - Read-only checks after both environments were initialized.
-- Expected table counts: Bronze=2, Silver=2, Gold=12, Datamart=14 per catalog.

SELECT 'finops_dev' AS table_catalog, table_schema, count(*) AS table_count
FROM `finops_dev`.`information_schema`.`tables`
WHERE table_schema IN ('bronze', 'silver', 'gold', 'datamart')
GROUP BY table_schema
UNION ALL
SELECT 'finops_prod' AS table_catalog, table_schema, count(*) AS table_count
FROM `finops_prod`.`information_schema`.`tables`
WHERE table_schema IN ('bronze', 'silver', 'gold', 'datamart')
GROUP BY table_schema
ORDER BY table_catalog, table_schema;

-- Expected result: 60 rows, all with row_count = 0.
SELECT 'finops_dev.bronze.focus_daily_raw' AS table_name, count(*) AS row_count FROM `finops_dev`.`bronze`.`focus_daily_raw`
UNION ALL SELECT 'finops_dev.bronze.focus_billing_raw', count(*) FROM `finops_dev`.`bronze`.`focus_billing_raw`
UNION ALL SELECT 'finops_dev.silver.focus_cost_usage', count(*) FROM `finops_dev`.`silver`.`focus_cost_usage`
UNION ALL SELECT 'finops_dev.silver.focus_cost_usage_central', count(*) FROM `finops_dev`.`silver`.`focus_cost_usage_central`
UNION ALL SELECT 'finops_dev.gold.dim_date', count(*) FROM `finops_dev`.`gold`.`dim_date`
UNION ALL SELECT 'finops_dev.gold.dim_billing_scope', count(*) FROM `finops_dev`.`gold`.`dim_billing_scope`
UNION ALL SELECT 'finops_dev.gold.dim_resource', count(*) FROM `finops_dev`.`gold`.`dim_resource`
UNION ALL SELECT 'finops_dev.gold.dim_service', count(*) FROM `finops_dev`.`gold`.`dim_service`
UNION ALL SELECT 'finops_dev.gold.dim_sku', count(*) FROM `finops_dev`.`gold`.`dim_sku`
UNION ALL SELECT 'finops_dev.gold.dim_location', count(*) FROM `finops_dev`.`gold`.`dim_location`
UNION ALL SELECT 'finops_dev.gold.dim_commitment_discount', count(*) FROM `finops_dev`.`gold`.`dim_commitment_discount`
UNION ALL SELECT 'finops_dev.gold.dim_pricing', count(*) FROM `finops_dev`.`gold`.`dim_pricing`
UNION ALL SELECT 'finops_dev.gold.dim_charge_type', count(*) FROM `finops_dev`.`gold`.`dim_charge_type`
UNION ALL SELECT 'finops_dev.gold.dim_tag', count(*) FROM `finops_dev`.`gold`.`dim_tag`
UNION ALL SELECT 'finops_dev.gold.bridge_resource_tag', count(*) FROM `finops_dev`.`gold`.`bridge_resource_tag`
UNION ALL SELECT 'finops_dev.gold.fact_finops_cost_usage', count(*) FROM `finops_dev`.`gold`.`fact_finops_cost_usage`
UNION ALL SELECT 'finops_dev.datamart.dm_monthly_billing', count(*) FROM `finops_dev`.`datamart`.`dm_monthly_billing`
UNION ALL SELECT 'finops_dev.datamart.dm_daily_billing', count(*) FROM `finops_dev`.`datamart`.`dm_daily_billing`
UNION ALL SELECT 'finops_dev.datamart.dm_cost_by_scope_service_month', count(*) FROM `finops_dev`.`datamart`.`dm_cost_by_scope_service_month`
UNION ALL SELECT 'finops_dev.datamart.dm_top_services', count(*) FROM `finops_dev`.`datamart`.`dm_top_services`
UNION ALL SELECT 'finops_dev.datamart.dm_top_resources', count(*) FROM `finops_dev`.`datamart`.`dm_top_resources`
UNION ALL SELECT 'finops_dev.datamart.dm_cost_by_charge_type', count(*) FROM `finops_dev`.`datamart`.`dm_cost_by_charge_type`
UNION ALL SELECT 'finops_dev.datamart.dm_sku_cost', count(*) FROM `finops_dev`.`datamart`.`dm_sku_cost`
UNION ALL SELECT 'finops_dev.datamart.dm_savings_monthly', count(*) FROM `finops_dev`.`datamart`.`dm_savings_monthly`
UNION ALL SELECT 'finops_dev.datamart.dm_executive_summary_monthly', count(*) FROM `finops_dev`.`datamart`.`dm_executive_summary_monthly`
UNION ALL SELECT 'finops_dev.datamart.dm_top_resources_monthly', count(*) FROM `finops_dev`.`datamart`.`dm_top_resources_monthly`
UNION ALL SELECT 'finops_dev.datamart.dm_data_quality_monthly', count(*) FROM `finops_dev`.`datamart`.`dm_data_quality_monthly`
UNION ALL SELECT 'finops_dev.datamart.dm_cost_by_resource_group_month', count(*) FROM `finops_dev`.`datamart`.`dm_cost_by_resource_group_month`
UNION ALL SELECT 'finops_dev.datamart.dm_cost_by_subscription_month', count(*) FROM `finops_dev`.`datamart`.`dm_cost_by_subscription_month`
UNION ALL SELECT 'finops_dev.datamart.dm_cost_by_application_owner_month', count(*) FROM `finops_dev`.`datamart`.`dm_cost_by_application_owner_month`
UNION ALL SELECT 'finops_prod.bronze.focus_daily_raw', count(*) FROM `finops_prod`.`bronze`.`focus_daily_raw`
UNION ALL SELECT 'finops_prod.bronze.focus_billing_raw', count(*) FROM `finops_prod`.`bronze`.`focus_billing_raw`
UNION ALL SELECT 'finops_prod.silver.focus_cost_usage', count(*) FROM `finops_prod`.`silver`.`focus_cost_usage`
UNION ALL SELECT 'finops_prod.silver.focus_cost_usage_central', count(*) FROM `finops_prod`.`silver`.`focus_cost_usage_central`
UNION ALL SELECT 'finops_prod.gold.dim_date', count(*) FROM `finops_prod`.`gold`.`dim_date`
UNION ALL SELECT 'finops_prod.gold.dim_billing_scope', count(*) FROM `finops_prod`.`gold`.`dim_billing_scope`
UNION ALL SELECT 'finops_prod.gold.dim_resource', count(*) FROM `finops_prod`.`gold`.`dim_resource`
UNION ALL SELECT 'finops_prod.gold.dim_service', count(*) FROM `finops_prod`.`gold`.`dim_service`
UNION ALL SELECT 'finops_prod.gold.dim_sku', count(*) FROM `finops_prod`.`gold`.`dim_sku`
UNION ALL SELECT 'finops_prod.gold.dim_location', count(*) FROM `finops_prod`.`gold`.`dim_location`
UNION ALL SELECT 'finops_prod.gold.dim_commitment_discount', count(*) FROM `finops_prod`.`gold`.`dim_commitment_discount`
UNION ALL SELECT 'finops_prod.gold.dim_pricing', count(*) FROM `finops_prod`.`gold`.`dim_pricing`
UNION ALL SELECT 'finops_prod.gold.dim_charge_type', count(*) FROM `finops_prod`.`gold`.`dim_charge_type`
UNION ALL SELECT 'finops_prod.gold.dim_tag', count(*) FROM `finops_prod`.`gold`.`dim_tag`
UNION ALL SELECT 'finops_prod.gold.bridge_resource_tag', count(*) FROM `finops_prod`.`gold`.`bridge_resource_tag`
UNION ALL SELECT 'finops_prod.gold.fact_finops_cost_usage', count(*) FROM `finops_prod`.`gold`.`fact_finops_cost_usage`
UNION ALL SELECT 'finops_prod.datamart.dm_monthly_billing', count(*) FROM `finops_prod`.`datamart`.`dm_monthly_billing`
UNION ALL SELECT 'finops_prod.datamart.dm_daily_billing', count(*) FROM `finops_prod`.`datamart`.`dm_daily_billing`
UNION ALL SELECT 'finops_prod.datamart.dm_cost_by_scope_service_month', count(*) FROM `finops_prod`.`datamart`.`dm_cost_by_scope_service_month`
UNION ALL SELECT 'finops_prod.datamart.dm_top_services', count(*) FROM `finops_prod`.`datamart`.`dm_top_services`
UNION ALL SELECT 'finops_prod.datamart.dm_top_resources', count(*) FROM `finops_prod`.`datamart`.`dm_top_resources`
UNION ALL SELECT 'finops_prod.datamart.dm_cost_by_charge_type', count(*) FROM `finops_prod`.`datamart`.`dm_cost_by_charge_type`
UNION ALL SELECT 'finops_prod.datamart.dm_sku_cost', count(*) FROM `finops_prod`.`datamart`.`dm_sku_cost`
UNION ALL SELECT 'finops_prod.datamart.dm_savings_monthly', count(*) FROM `finops_prod`.`datamart`.`dm_savings_monthly`
UNION ALL SELECT 'finops_prod.datamart.dm_executive_summary_monthly', count(*) FROM `finops_prod`.`datamart`.`dm_executive_summary_monthly`
UNION ALL SELECT 'finops_prod.datamart.dm_top_resources_monthly', count(*) FROM `finops_prod`.`datamart`.`dm_top_resources_monthly`
UNION ALL SELECT 'finops_prod.datamart.dm_data_quality_monthly', count(*) FROM `finops_prod`.`datamart`.`dm_data_quality_monthly`
UNION ALL SELECT 'finops_prod.datamart.dm_cost_by_resource_group_month', count(*) FROM `finops_prod`.`datamart`.`dm_cost_by_resource_group_month`
UNION ALL SELECT 'finops_prod.datamart.dm_cost_by_subscription_month', count(*) FROM `finops_prod`.`datamart`.`dm_cost_by_subscription_month`
UNION ALL SELECT 'finops_prod.datamart.dm_cost_by_application_owner_month', count(*) FROM `finops_prod`.`datamart`.`dm_cost_by_application_owner_month`
ORDER BY table_name;

-- Expected result: five rows, all with row_count = 0.
SELECT 'pipeline_run' AS table_name, count(*) AS row_count FROM `finops_ops`.`audit`.`pipeline_run`
UNION ALL SELECT 'month_snapshot', count(*) FROM `finops_ops`.`audit`.`month_snapshot`
UNION ALL SELECT 'monthly_reconciliation', count(*) FROM `finops_ops`.`audit`.`monthly_reconciliation`
UNION ALL SELECT 'month_status', count(*) FROM `finops_ops`.`audit`.`month_status`
UNION ALL SELECT 'file_archive', count(*) FROM `finops_ops`.`audit`.`file_archive`
ORDER BY table_name;

SHOW VOLUMES IN `finops_raw`.`landing`;
LIST '/Volumes/finops_raw/landing/focus/monthly';
