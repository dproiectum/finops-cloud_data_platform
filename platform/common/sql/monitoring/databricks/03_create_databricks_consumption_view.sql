-- PLATFORM MONITORING / STEP 2: manual, additive operational telemetry view.
-- Run as YOUR Databricks account, which passed the system.billing.usage check.
-- No grants to the public dashboard and no change to existing audit views.
-- The separate schema organizes real telemetry, but is NOT a deny policy:
-- inherited catalog/schema privileges must still be reviewed before app access.
-- This ordinary view stores no billing copy and needs no ingestion/reload Job.
-- Monthly DBUs cover all matching workspace activity, NOT one pipeline's cost.
-- ORIGINAL + signed RETRACTION + RESTATEMENT stay in the SUM.
-- GENIE_FREE_USAGE is explicitly identified, not counted as a paid-cost proxy.
-- No price, currency, kWh or kgCO2e is calculated.
-- OR REPLACE affects only the new view; re-run as its owner. It can reset
-- view-specific grants. Nothing here grants permissions or publishes telemetry.
-- Reference: https://docs.databricks.com/gcp/en/admin/system-tables/billing

CREATE SCHEMA IF NOT EXISTS finops_ops.monitoring
COMMENT 'Operational consumption telemetry; not a public dashboard data source';

CREATE OR REPLACE VIEW finops_ops.monitoring.v_databricks_consumption_monthly
COMMENT 'Net DBUs for the two FinOps project workspaces since September 2026; real operational telemetry'
AS
SELECT
    date_format(usage_date, 'yyyy-MM') AS usage_month,
    workspace_id,
    CASE workspace_id
      WHEN '8259550392658865' THEN 'Frankfurt'
      WHEN '8259550830613689' THEN 'Belgium'
    END AS workspace_label,
    sku_name,
    billing_origin_product,
    usage_unit,
    sku_name = 'GENIE_FREE_USAGE' AS is_genie_free_usage,
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
         sku_name, billing_origin_product, usage_unit;
