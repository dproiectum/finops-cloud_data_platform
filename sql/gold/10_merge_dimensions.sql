-- Dimension loading for one complete billing month.
-- Billing scope and resource are maintained as Type 1 dimensions. Other keys
-- include every descriptive attribute and therefore keep distinct variants.

MERGE INTO {dim_date} AS target
USING (
  WITH dates AS (
    SELECT DISTINCT date_value AS date
    FROM (
      SELECT explode(array(
        to_date(BillingPeriodStart),
        to_date(BillingPeriodEnd),
        to_date(ChargePeriodStart),
        to_date(ChargePeriodEnd),
        to_date(x_ServicePeriodStart),
        to_date(x_ServicePeriodEnd),
        to_date(x_BillingExchangeRateDate)
      )) AS date_value
      FROM {source_month}
    )
    WHERE date_value IS NOT NULL
  )
  SELECT
    CAST(date_format(date, 'yyyyMMdd') AS BIGINT) AS date_sk,
    date,
    year(date) AS year,
    quarter(date) AS quarter,
    month(date) AS month,
    date_format(date, 'MMMM') AS month_name,
    weekofyear(date) AS week,
    dayofmonth(date) AS day,
    weekday(date) + 1 AS day_of_week,
    date_format(date, 'EEEE') AS day_name,
    date = trunc(date, 'MONTH') AS is_month_start,
    date = last_day(date) AS is_month_end
  FROM dates
) AS source
ON target.date_sk = source.date_sk
WHEN MATCHED THEN UPDATE SET *
WHEN NOT MATCHED THEN INSERT *;

MERGE INTO {dim_billing_scope} AS target
USING (
  WITH base AS (
    SELECT
      coalesce(nullif(trim(BillingAccountId), ''), 'Unknown') AS billing_account_id,
      coalesce(nullif(trim(BillingAccountName), ''), 'Unknown') AS billing_account_name,
      coalesce(nullif(trim(BillingAccountType), ''), 'Unknown') AS billing_account_type,
      coalesce(nullif(trim(SubAccountId), ''), 'Unknown') AS sub_account_id,
      coalesce(nullif(trim(SubAccountName), ''), 'Unknown') AS sub_account_name,
      coalesce(nullif(trim(SubAccountType), ''), 'Unknown') AS sub_account_type,
      coalesce(nullif(trim(x_AccountName), ''), 'Unknown') AS account_name,
      coalesce(nullif(trim(x_AccountOwnerId), ''), 'Unknown') AS account_owner_id,
      coalesce(nullif(trim(x_BillingProfileId), ''), 'Unknown') AS billing_profile_id,
      coalesce(nullif(trim(x_BillingProfileName), ''), 'Unknown') AS billing_profile_name,
      coalesce(nullif(trim(x_InvoiceSectionId), ''), 'Unknown') AS invoice_section_id,
      coalesce(nullif(trim(x_InvoiceSectionName), ''), 'Unknown') AS invoice_section_name,
      coalesce(nullif(trim(x_CustomerId), ''), 'Unknown') AS customer_id,
      coalesce(nullif(trim(x_CustomerName), ''), 'Unknown') AS customer_name,
      coalesce(nullif(trim(x_CostCenter), ''), 'Unknown') AS cost_center,
      coalesce(nullif(trim(x_CostAllocationRuleName), ''), 'Unknown') AS cost_allocation_rule_name,
      coalesce(ChargePeriodStart, CAST(BillingPeriodStart AS TIMESTAMP)) AS event_time,
      _ingested_at
    FROM {source_month}
  ), ranked AS (
    SELECT
      sha2(concat_ws('||', 'billing_scope', billing_account_id,
        sub_account_id, billing_profile_id), 256) AS billing_scope_sk,
      *,
      min(event_time) OVER (
        PARTITION BY billing_account_id, sub_account_id, billing_profile_id
      ) AS valid_from,
      row_number() OVER (
        PARTITION BY billing_account_id, sub_account_id, billing_profile_id
        ORDER BY event_time DESC, _ingested_at DESC
      ) AS row_rank
    FROM base
  )
  SELECT
    billing_scope_sk, billing_account_id, billing_account_name,
    billing_account_type, sub_account_id, sub_account_name, sub_account_type,
    account_name, account_owner_id, billing_profile_id, billing_profile_name,
    invoice_section_id, invoice_section_name, customer_id, customer_name,
    cost_center, cost_allocation_rule_name, valid_from,
    CAST(NULL AS TIMESTAMP) AS valid_to, true AS is_current
  FROM ranked
  WHERE row_rank = 1
) AS source
ON target.billing_scope_sk = source.billing_scope_sk
WHEN MATCHED THEN UPDATE SET
  target.billing_account_id = source.billing_account_id,
  target.billing_account_name = source.billing_account_name,
  target.billing_account_type = source.billing_account_type,
  target.sub_account_id = source.sub_account_id,
  target.sub_account_name = source.sub_account_name,
  target.sub_account_type = source.sub_account_type,
  target.account_name = source.account_name,
  target.account_owner_id = source.account_owner_id,
  target.billing_profile_id = source.billing_profile_id,
  target.billing_profile_name = source.billing_profile_name,
  target.invoice_section_id = source.invoice_section_id,
  target.invoice_section_name = source.invoice_section_name,
  target.customer_id = source.customer_id,
  target.customer_name = source.customer_name,
  target.cost_center = source.cost_center,
  target.cost_allocation_rule_name = source.cost_allocation_rule_name,
  target.valid_from = CASE
    WHEN target.valid_from IS NULL OR source.valid_from < target.valid_from
      THEN source.valid_from
    ELSE target.valid_from
  END,
  target.valid_to = CAST(NULL AS TIMESTAMP),
  target.is_current = true
WHEN NOT MATCHED THEN INSERT *;

MERGE INTO {dim_resource} AS target
USING (
  WITH base AS (
    SELECT
      coalesce(nullif(trim(ProviderName), ''), 'Unknown') AS provider_name,
      coalesce(nullif(trim(ResourceId), ''), 'Unknown') AS resource_id,
      coalesce(nullif(trim(ResourceName), ''), 'Unknown') AS resource_name,
      coalesce(nullif(trim(ResourceType), ''), 'Unknown') AS resource_type,
      coalesce(nullif(trim(x_ResourceType), ''), 'Unknown') AS provider_resource_type,
      coalesce(nullif(trim(x_ResourceGroupName), ''), 'Unknown') AS resource_group_name,
      coalesce(Tags, '') AS tags_raw,
      coalesce(nullif(trim(element_at(from_json(Tags, 'MAP<STRING,STRING>'), 'ApplicationCode-Symphony')), ''), 'Unknown') AS application_code,
      coalesce(nullif(trim(element_at(from_json(Tags, 'MAP<STRING,STRING>'), 'ApplicationName-Symphony')), ''), 'Unknown') AS application_name,
      coalesce(nullif(trim(element_at(from_json(Tags, 'MAP<STRING,STRING>'), 'IDSApplicationOwner-Symphony')), ''), 'Unknown') AS application_owner_id,
      coalesce(nullif(trim(element_at(from_json(Tags, 'MAP<STRING,STRING>'), 'IDSApplicationOwner-Email-Symphony')), ''), 'Unknown') AS application_owner_email,
      coalesce(nullif(trim(element_at(from_json(Tags, 'MAP<STRING,STRING>'), 'ApplicationBusinessOwner-Symphony')), ''), 'Unknown') AS application_business_owner,
      coalesce(ChargePeriodStart, CAST(BillingPeriodStart AS TIMESTAMP)) AS event_time,
      _ingested_at
    FROM {source_month}
  ), ranked AS (
    SELECT
      sha2(concat_ws('||', 'resource', provider_name, resource_id), 256) AS resource_sk,
      *,
      min(event_time) OVER (
        PARTITION BY provider_name, resource_id
      ) AS valid_from,
      row_number() OVER (
        PARTITION BY provider_name, resource_id
        ORDER BY event_time DESC, _ingested_at DESC
      ) AS row_rank
    FROM base
  )
  SELECT
    resource_sk, resource_id, resource_name, resource_type,
    provider_resource_type, resource_group_name, tags_raw, application_code,
    application_name, application_owner_id, application_owner_email,
    application_business_owner, valid_from,
    CAST(NULL AS TIMESTAMP) AS valid_to, true AS is_current
  FROM ranked
  WHERE row_rank = 1
) AS source
ON target.resource_sk = source.resource_sk
WHEN MATCHED THEN UPDATE SET
  target.resource_id = source.resource_id,
  target.resource_name = source.resource_name,
  target.resource_type = source.resource_type,
  target.provider_resource_type = source.provider_resource_type,
  target.resource_group_name = source.resource_group_name,
  target.tags_raw = source.tags_raw,
  target.application_code = source.application_code,
  target.application_name = source.application_name,
  target.application_owner_id = source.application_owner_id,
  target.application_owner_email = source.application_owner_email,
  target.application_business_owner = source.application_business_owner,
  target.valid_from = CASE
    WHEN target.valid_from IS NULL OR source.valid_from < target.valid_from
      THEN source.valid_from
    ELSE target.valid_from
  END,
  target.valid_to = CAST(NULL AS TIMESTAMP),
  target.is_current = true
WHEN NOT MATCHED THEN INSERT *;

MERGE INTO {dim_service} AS target
USING (
  WITH normalized AS (
    SELECT DISTINCT
      coalesce(nullif(trim(ServiceName), ''), 'Unknown') AS service_name,
      coalesce(nullif(trim(ServiceCategory), ''), 'Unknown') AS service_category,
      coalesce(nullif(trim(ProviderName), ''), 'Unknown') AS provider_name,
      coalesce(nullif(trim(x_PublisherId), ''), 'Unknown') AS publisher_id,
      coalesce(nullif(trim(PublisherName), ''), 'Unknown') AS publisher_name,
      coalesce(nullif(trim(x_PublisherCategory), ''), 'Unknown') AS publisher_category,
      coalesce(nullif(trim(x_ResellerId), ''), 'Unknown') AS reseller_id,
      coalesce(nullif(trim(x_ResellerName), ''), 'Unknown') AS reseller_name
    FROM {source_month}
  )
  SELECT sha2(concat_ws('||', 'service', service_name, service_category,
    provider_name, publisher_id, publisher_name, publisher_category,
    reseller_id, reseller_name), 256) AS service_sk, *
  FROM normalized
) AS source
ON target.service_sk = source.service_sk
WHEN NOT MATCHED THEN INSERT *;

MERGE INTO {dim_sku} AS target
USING (
  WITH normalized AS (
    SELECT DISTINCT
      coalesce(nullif(trim(SkuId), ''), 'Unknown') AS sku_id,
      coalesce(nullif(trim(SkuPriceId), ''), 'Unknown') AS sku_price_id,
      coalesce(x_SkuDescription, '') AS sku_description,
      coalesce(x_SkuDetails, '') AS sku_details,
      coalesce(nullif(trim(x_SkuMeterId), ''), 'Unknown') AS meter_id,
      coalesce(nullif(trim(x_SkuMeterName), ''), 'Unknown') AS meter_name,
      coalesce(nullif(trim(x_SkuMeterCategory), ''), 'Unknown') AS meter_category,
      coalesce(nullif(trim(x_SkuMeterSubcategory), ''), 'Unknown') AS meter_subcategory,
      coalesce(nullif(trim(x_SkuOfferId), ''), 'Unknown') AS offer_id,
      coalesce(nullif(trim(x_SkuOrderId), ''), 'Unknown') AS order_id,
      coalesce(nullif(trim(x_SkuOrderName), ''), 'Unknown') AS order_name,
      coalesce(nullif(trim(x_SkuPartNumber), ''), 'Unknown') AS part_number,
      coalesce(nullif(trim(x_SkuRegion), ''), 'Unknown') AS sku_region,
      coalesce(nullif(trim(x_SkuServiceFamily), ''), 'Unknown') AS sku_service_family,
      coalesce(nullif(trim(x_SkuTerm), ''), 'Unknown') AS sku_term,
      coalesce(nullif(trim(x_SkuTier), ''), 'Unknown') AS sku_tier,
      x_SkuIsCreditEligible AS sku_is_credit_eligible
    FROM {source_month}
  )
  SELECT sha2(concat_ws('||', 'sku', sku_id, sku_price_id, sku_description,
    sku_details, meter_id, meter_name, meter_category, meter_subcategory,
    offer_id, order_id, order_name, part_number, sku_region,
    sku_service_family, sku_term, sku_tier,
    coalesce(CAST(sku_is_credit_eligible AS STRING), 'Unknown')), 256) AS sku_sk, *
  FROM normalized
) AS source
ON target.sku_sk = source.sku_sk
WHEN NOT MATCHED THEN INSERT *;

MERGE INTO {dim_location} AS target
USING (
  WITH normalized AS (
    SELECT DISTINCT
      coalesce(nullif(trim(Region), ''), 'Unknown') AS region,
      'Unknown' AS availability_zone,
      coalesce(nullif(trim(x_SkuRegion), ''), 'Unknown') AS sku_region
    FROM {source_month}
  )
  SELECT sha2(concat_ws('||', 'location', region, availability_zone, sku_region), 256) AS location_sk, *
  FROM normalized
) AS source
ON target.location_sk = source.location_sk
WHEN NOT MATCHED THEN INSERT *;

MERGE INTO {dim_commitment_discount} AS target
USING (
  WITH normalized AS (
    SELECT DISTINCT
      coalesce(nullif(trim(CommitmentDiscountId), ''), 'Unknown') AS commitment_discount_id,
      coalesce(nullif(trim(CommitmentDiscountName), ''), 'Unknown') AS commitment_discount_name,
      coalesce(nullif(trim(CommitmentDiscountCategory), ''), 'Unknown') AS commitment_discount_category,
      coalesce(nullif(trim(CommitmentDiscountType), ''), 'Unknown') AS commitment_discount_type
    FROM {source_month}
  )
  SELECT sha2(concat_ws('||', 'commitment', commitment_discount_id,
    commitment_discount_name, commitment_discount_category,
    commitment_discount_type), 256) AS commitment_sk, *
  FROM normalized
) AS source
ON target.commitment_sk = source.commitment_sk
WHEN NOT MATCHED THEN INSERT *;

MERGE INTO {dim_pricing} AS target
USING (
  WITH normalized AS (
    SELECT DISTINCT
      coalesce(nullif(trim(PricingCategory), ''), 'Unknown') AS pricing_category,
      coalesce(nullif(trim(x_PricingSubcategory), ''), 'Unknown') AS pricing_subcategory,
      coalesce(nullif(trim(PricingUnit), ''), 'Unknown') AS pricing_unit,
      coalesce(nullif(trim(x_PricingUnitDescription), ''), 'Unknown') AS pricing_unit_description,
      coalesce(nullif(trim(x_PricingCurrency), ''), nullif(trim(BillingCurrency), ''), 'Unknown') AS pricing_currency,
      x_PartnerCreditApplied AS partner_credit_applied
    FROM {source_month}
  )
  SELECT sha2(concat_ws('||', 'pricing', pricing_category,
    pricing_subcategory, pricing_unit, pricing_unit_description,
    pricing_currency, coalesce(CAST(partner_credit_applied AS STRING), 'Unknown')), 256) AS pricing_sk, *
  FROM normalized
) AS source
ON target.pricing_sk = source.pricing_sk
WHEN NOT MATCHED THEN INSERT *;

MERGE INTO {dim_charge_type} AS target
USING (
  WITH normalized AS (
    SELECT DISTINCT
      coalesce(nullif(trim(ChargeCategory), ''), 'Unknown') AS charge_category,
      'Unknown' AS charge_subcategory,
      coalesce(nullif(trim(ChargeFrequency), ''), 'Unknown') AS charge_frequency
    FROM {source_month}
  )
  SELECT sha2(concat_ws('||', 'charge_type', charge_category,
    charge_subcategory, charge_frequency), 256) AS charge_type_sk, *
  FROM normalized
) AS source
ON target.charge_type_sk = source.charge_type_sk
WHEN NOT MATCHED THEN INSERT *;
