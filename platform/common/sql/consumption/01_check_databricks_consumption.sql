-- CONSUMPTION / STEP 1B: read-only DBU availability check.
-- Run separately from the Azure check with YOUR existing Databricks identity.
-- This does not test the Cloud Run service principal's permissions.
-- Permission errors: share the error; do not grant broad system-table access.
-- The two workspace IDs below are the existing project workspaces only.
-- Data is limited to September 2026 onward, when these project runs occurred.
-- Empty results mean no matching available data, NOT zero consumption.
-- Real account telemetry: do not publish these results to the public portfolio.

-- 1. Available periods for the two project workspaces; DBU records only.
SELECT
    workspace_id,
    CASE workspace_id
      WHEN '8259550392658865' THEN 'Frankfurt'
      WHEN '8259550830613689' THEN 'Belgium'
    END AS workspace_label,
    min(usage_date) AS first_available_usage_date,
    max(usage_date) AS last_available_usage_date,
    count(*) AS billing_records,
    count_if(record_type = 'RETRACTION') AS retraction_records,
    count_if(record_type = 'RESTATEMENT') AS restatement_records
FROM system.billing.usage
WHERE cloud = 'GCP'
  AND workspace_id IN ('8259550392658865', '8259550830613689')
  AND usage_date >= DATE '2026-09-01'
  AND usage_unit = 'DBU'
GROUP BY workspace_id
ORDER BY workspace_label;

-- 2. Monthly NET DBUs by workspace, billing SKU and originating product.
-- usage_date is the source usage date, not the later record-ingestion date.
-- ORIGINAL + signed RETRACTION + RESTATEMENT must all remain in the SUM.
-- DBUs are not kWh or kgCO2e. No conversion factor is invented here.
-- Totals cover workspace activity, including interactive/automatic workloads:
-- they are NOT an exact allocation to the FinOps pipeline or to DEV/PROD.
-- SKU/product separation keeps free/automatic usage visible as distinct records.
-- Reference: https://docs.databricks.com/gcp/en/admin/system-tables/billing
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
    sum(usage_quantity) AS net_dbu,
    count(*) AS billing_records
FROM system.billing.usage
WHERE cloud = 'GCP'
  AND workspace_id IN ('8259550392658865', '8259550830613689')
  AND usage_date >= DATE '2026-09-01'
  AND usage_unit = 'DBU'
GROUP BY date_format(usage_date, 'yyyy-MM'), workspace_id,
         sku_name, billing_origin_product, usage_unit
ORDER BY usage_month DESC, workspace_label, sku_name, billing_origin_product;
