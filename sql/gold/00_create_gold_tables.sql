-- Idempotent physical model for the Databricks Gold layer.
-- SHA-256 surrogate keys are strings so that key generation is deterministic.

CREATE TABLE IF NOT EXISTS {dim_date} (
  date_sk BIGINT NOT NULL,
  date DATE NOT NULL,
  year INT NOT NULL,
  quarter INT NOT NULL,
  month INT NOT NULL,
  month_name STRING NOT NULL,
  week INT NOT NULL,
  day INT NOT NULL,
  day_of_week INT NOT NULL,
  day_name STRING NOT NULL,
  is_month_start BOOLEAN NOT NULL,
  is_month_end BOOLEAN NOT NULL
) USING DELTA;

CREATE TABLE IF NOT EXISTS {dim_billing_scope} (
  billing_scope_sk STRING NOT NULL,
  billing_account_id STRING,
  billing_account_name STRING,
  billing_account_type STRING,
  sub_account_id STRING,
  sub_account_name STRING,
  sub_account_type STRING,
  account_name STRING,
  account_owner_id STRING,
  billing_profile_id STRING,
  billing_profile_name STRING,
  invoice_section_id STRING,
  invoice_section_name STRING,
  customer_id STRING,
  customer_name STRING,
  cost_center STRING,
  cost_allocation_rule_name STRING,
  valid_from TIMESTAMP,
  valid_to TIMESTAMP,
  is_current BOOLEAN NOT NULL
) USING DELTA;

CREATE TABLE IF NOT EXISTS {dim_resource} (
  resource_sk STRING NOT NULL,
  resource_id STRING,
  resource_name STRING,
  resource_type STRING,
  provider_resource_type STRING,
  resource_group_name STRING,
  tags_raw STRING,
  application_code STRING,
  application_name STRING,
  application_owner_id STRING,
  application_owner_email STRING,
  application_business_owner STRING,
  valid_from TIMESTAMP,
  valid_to TIMESTAMP,
  is_current BOOLEAN NOT NULL
) USING DELTA;

CREATE TABLE IF NOT EXISTS {dim_service} (
  service_sk STRING NOT NULL,
  service_name STRING,
  service_category STRING,
  provider_name STRING,
  publisher_id STRING,
  publisher_name STRING,
  publisher_category STRING,
  reseller_id STRING,
  reseller_name STRING
) USING DELTA;

CREATE TABLE IF NOT EXISTS {dim_sku} (
  sku_sk STRING NOT NULL,
  sku_id STRING,
  sku_price_id STRING,
  sku_description STRING,
  sku_details STRING,
  meter_id STRING,
  meter_name STRING,
  meter_category STRING,
  meter_subcategory STRING,
  offer_id STRING,
  order_id STRING,
  order_name STRING,
  part_number STRING,
  sku_region STRING,
  sku_service_family STRING,
  sku_term STRING,
  sku_tier STRING,
  sku_is_credit_eligible BOOLEAN
) USING DELTA;

CREATE TABLE IF NOT EXISTS {dim_location} (
  location_sk STRING NOT NULL,
  region STRING,
  availability_zone STRING,
  sku_region STRING
) USING DELTA;

CREATE TABLE IF NOT EXISTS {dim_commitment_discount} (
  commitment_sk STRING NOT NULL,
  commitment_discount_id STRING,
  commitment_discount_name STRING,
  commitment_discount_category STRING,
  commitment_discount_type STRING
) USING DELTA;

CREATE TABLE IF NOT EXISTS {dim_pricing} (
  pricing_sk STRING NOT NULL,
  pricing_category STRING,
  pricing_subcategory STRING,
  pricing_unit STRING,
  pricing_unit_description STRING,
  pricing_currency STRING,
  partner_credit_applied BOOLEAN
) USING DELTA;

CREATE TABLE IF NOT EXISTS {dim_charge_type} (
  charge_type_sk STRING NOT NULL,
  charge_category STRING,
  charge_subcategory STRING,
  charge_frequency STRING
) USING DELTA;

CREATE TABLE IF NOT EXISTS {dim_tag} (
  tag_sk STRING NOT NULL,
  tag_key STRING NOT NULL,
  tag_value STRING NOT NULL
) USING DELTA;

CREATE TABLE IF NOT EXISTS {bridge_resource_tag} (
  resource_sk STRING NOT NULL,
  tag_sk STRING NOT NULL,
  valid_from TIMESTAMP,
  valid_to TIMESTAMP
) USING DELTA;

CREATE TABLE IF NOT EXISTS {fact_cost_usage} (
  cost_usage_sk STRING NOT NULL,
  charge_id STRING,
  billing_month STRING NOT NULL,
  billing_scope_sk STRING,
  resource_sk STRING,
  service_sk STRING,
  sku_sk STRING,
  location_sk STRING,
  pricing_sk STRING,
  commitment_sk STRING,
  charge_type_sk STRING,
  billing_period_start_date_sk BIGINT,
  billing_period_end_date_sk BIGINT,
  charge_period_start_date_sk BIGINT,
  charge_period_end_date_sk BIGINT,
  service_period_start_date_sk BIGINT,
  service_period_end_date_sk BIGINT,
  exchange_rate_date_sk BIGINT,
  billed_cost DECIMAL(38, 18),
  effective_cost DECIMAL(38, 18),
  list_cost DECIMAL(38, 18),
  list_unit_price DECIMAL(38, 18),
  billed_cost_usd DECIMAL(38, 18),
  effective_cost_usd DECIMAL(38, 18),
  on_demand_cost DECIMAL(38, 18),
  on_demand_cost_usd DECIMAL(38, 18),
  billed_unit_price DECIMAL(38, 18),
  effective_unit_price DECIMAL(38, 18),
  on_demand_unit_price DECIMAL(38, 18),
  usage_quantity DECIMAL(38, 18),
  usage_unit STRING,
  pricing_quantity DECIMAL(38, 18),
  pricing_block_size DECIMAL(38, 18),
  partner_credit_rate DECIMAL(38, 18),
  billing_exchange_rate DECIMAL(38, 18),
  charge_description STRING,
  billing_currency STRING,
  ingestion_timestamp TIMESTAMP,
  source_system STRING,
  focus_version STRING,
  contract_version STRING,
  batch_id STRING
) USING DELTA
PARTITIONED BY (billing_month)
TBLPROPERTIES (
  'delta.enableChangeDataFeed' = 'true'
);
