-- Manual STEP 7 setup, workspace-belgium, PROD synthetic dataset.
-- Execute with the existing view owner's business-data read permissions.
-- This ordinary view stores no duplicate data and follows Silver publications.
-- It is NOT a Unity Catalog row-filter policy. The backend can read all rows;
-- the protected application must apply its live viewer predicate before aggregation.
-- No Tags blob or source-file path is exposed to application owners.

CREATE OR REPLACE VIEW finops_prod.datamart.v_dashboard_charge_scoped AS
WITH tagged AS (
    SELECT *, from_json(Tags, 'MAP<STRING,STRING>') AS application_tags
    FROM finops_prod.silver.focus_cost_usage_central
)
SELECT
    'prod' AS environment,
    billing_month,
    to_date(ChargePeriodStart) AS date,
    ResourceId AS resource_id,
    coalesce(nullif(trim(ResourceName), ''), 'Unknown') AS resource_name,
    coalesce(nullif(trim(x_ResourceGroupName), ''), 'Unknown') AS resource_group_name,
    RegionName AS region,
    ServiceName AS service_name,
    coalesce(nullif(trim(x_CostCenter), ''), 'Unallocated') AS cost_center,
    coalesce(nullif(trim(SubAccountId), ''), 'Unknown') AS subscription_id,
    coalesce(nullif(trim(SubAccountName), ''), 'Unknown') AS subscription_name,
    SkuId AS sku_id,
    x_SkuMeterCategory AS meter_category,
    x_SkuMeterName AS meter_name,
    ChargeCategory AS charge_category,
    ChargeSubcategory AS charge_subcategory,
    ChargeFrequency AS charge_frequency,
    nullif(trim(element_at(application_tags, 'ApplicationCode-Symphony')), '')
        AS application_code,
    coalesce(nullif(trim(element_at(application_tags, 'ApplicationName-Symphony')), ''),
        'Unknown') AS application_name,
    coalesce(nullif(trim(element_at(application_tags, 'IDSApplicationOwner-Symphony')), ''),
        'Unknown') AS application_owner_id,
    coalesce(nullif(trim(element_at(application_tags, 'IDSApplicationOwner-Email-Symphony')), ''),
        'Unknown') AS application_owner_email,
    coalesce(nullif(trim(element_at(application_tags, 'ApplicationBusinessOwner-Symphony')), ''),
        'Unknown') AS application_business_owner,
    BilledCost AS billed_cost,
    EffectiveCost AS effective_cost,
    ListCost AS list_cost,
    ContractedCost AS contracted_cost,
    BillingCurrency AS billing_currency,
    _ingestion_run_id AS ingestion_run_id,
    _ingested_at AS ingested_at,
    CASE
      WHEN ChargeCategory = 'Adjustment' THEN 'adjustment'
      WHEN ChargeCategory = 'Usage' AND PricingCategory = 'Commitment-Based'
        AND CommitmentDiscountType = 'Reservation' THEN 'reservation'
      WHEN ChargeCategory = 'Usage' AND PricingCategory = 'Commitment-Based'
        AND CommitmentDiscountType = 'Savings Plan' THEN 'savings_plan'
      WHEN ChargeCategory = 'Usage' AND PricingCategory = 'On-Demand' THEN 'usage_on_demand'
      WHEN ChargeCategory = 'Usage' AND PricingCategory = 'Dynamic' THEN 'usage_dynamic'
      ELSE 'other'
    END AS effective_cost_component
FROM tagged;
