-- Normalize JSON resource tags and maintain the many-to-many bridge.

MERGE INTO {dim_tag} AS target
USING (
  WITH exploded AS (
    SELECT explode(map_entries(from_json(Tags, 'MAP<STRING,STRING>'))) AS tag
    FROM {source_month}
    WHERE Tags IS NOT NULL AND trim(Tags) <> ''
  ), normalized AS (
    SELECT DISTINCT trim(tag.key) AS tag_key, trim(tag.value) AS tag_value
    FROM exploded
    WHERE tag.key IS NOT NULL AND trim(tag.key) <> ''
      AND tag.value IS NOT NULL AND trim(tag.value) <> ''
  )
  SELECT
    sha2(concat_ws('||', 'tag', tag_key, tag_value), 256) AS tag_sk,
    tag_key,
    tag_value
  FROM normalized
) AS source
ON target.tag_sk = source.tag_sk
WHEN NOT MATCHED THEN INSERT *;

MERGE INTO {bridge_resource_tag} AS target
USING (
  WITH exploded AS (
    SELECT
      sha2(concat_ws('||', 'resource',
        coalesce(nullif(trim(ProviderName), ''), 'Unknown'),
        coalesce(nullif(trim(ResourceId), ''), 'Unknown')
      ), 256) AS resource_sk,
      explode(map_entries(from_json(Tags, 'MAP<STRING,STRING>'))) AS tag,
      coalesce(ChargePeriodStart, CAST(BillingPeriodStart AS TIMESTAMP)) AS valid_from
    FROM {source_month}
    WHERE Tags IS NOT NULL AND trim(Tags) <> ''
  ), normalized AS (
    SELECT
      resource_sk,
      trim(tag.key) AS tag_key,
      trim(tag.value) AS tag_value,
      min(valid_from) AS valid_from
    FROM exploded
    WHERE tag.key IS NOT NULL AND trim(tag.key) <> ''
      AND tag.value IS NOT NULL AND trim(tag.value) <> ''
    GROUP BY resource_sk, trim(tag.key), trim(tag.value)
  )
  SELECT
    resource_sk,
    sha2(concat_ws('||', 'tag', tag_key, tag_value), 256) AS tag_sk,
    valid_from,
    CAST(NULL AS TIMESTAMP) AS valid_to
  FROM normalized
) AS source
ON target.resource_sk = source.resource_sk AND target.tag_sk = source.tag_sk
WHEN MATCHED THEN UPDATE SET
  target.valid_from = CASE
    WHEN target.valid_from IS NULL OR source.valid_from < target.valid_from
      THEN source.valid_from
    ELSE target.valid_from
  END,
  target.valid_to = CAST(NULL AS TIMESTAMP)
WHEN NOT MATCHED THEN INSERT *;
