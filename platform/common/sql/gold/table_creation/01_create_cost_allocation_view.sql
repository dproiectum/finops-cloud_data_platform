-- Synthetic business allocation, one output row per authoritative Silver charge.
-- Do not infer this from the Type-1 billing-scope dimension: a subscription may
-- contain several regions and different source cost centers. No source is rewritten.
CREATE OR REPLACE VIEW {cost_allocation_view} AS
WITH normalized AS (
  SELECT source.*,
    x_CostCenter AS cost_center_source,
    lower(trim(coalesce(x_CostCenter, ''))) AS source_center_normalized,
    lower(trim(coalesce(Region, ''))) AS allocation_region_normalized
  FROM {silver_central} AS source
), classified AS (
  SELECT *,
    CASE
      WHEN source_center_normalized NOT IN
        ('', 'unknown', 'unallocated', 'unallocated costs', 'no cost center assigned')
        THEN 'SOURCE'
      WHEN allocation_region_normalized IN
        ('west europe', 'north europe', 'france central', 'sweden central', 'uk south')
        THEN 'REGION_EUROPE'
      WHEN allocation_region_normalized = 'global' THEN 'GLOBAL_CORPORATE'
      WHEN allocation_region_normalized IN ({corporate_regions_sql})
        THEN 'REGION_CORPORATE'
      ELSE 'UNALLOCATED'
    END AS allocation_method
  FROM normalized
)
SELECT *,
  CASE allocation_method
    WHEN 'SOURCE' THEN trim(cost_center_source)
    WHEN 'REGION_EUROPE' THEN 'CostCenter_Europe'
    WHEN 'GLOBAL_CORPORATE' THEN 'CostCenter_Corporate'
    WHEN 'REGION_CORPORATE' THEN 'CostCenter_Corporate'
    ELSE 'Unallocated Costs'
  END AS cost_center_allocated,
  'REGION_FALLBACK_V1' AS allocation_policy_version
FROM classified;
