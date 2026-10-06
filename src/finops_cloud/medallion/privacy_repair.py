"""Explicit historical text repair; never called by an ingestion job.

The operator supplies the checksum-verified generator privacy module. Reuse its
policy rather than introduce another set of text replacements in the platform.
Dry-run is read-only. Apply requires paused jobs/dashboard reads and clean RAW
files already published. Delta versions are printed for manual recovery.
"""
from __future__ import annotations

import hashlib
import json
import re
from uuid import uuid4

from finops_cloud.audit.runs import start_run, finish_run
from finops_cloud.medallion.delta import delta_version, table_exists
from finops_cloud.medallion.gold import refresh_datamarts
from finops_cloud.medallion.initialize import business_tables, DERIVED_TABLES, GOLD_TABLE_KEYS
from finops_cloud.medallion.privacy import POLICY_VERSION, assert_source_privacy, privacy_expressions, privacy_condition

CONFIRMATION = 'APPLY_DATASET_PRIVACY_REPAIR'


def quoted_table(name):
    if not re.fullmatch(r'[A-Za-z0-9_]+\.[A-Za-z0-9_]+\.[A-Za-z0-9_]+', name):
        raise ValueError('Expected a three-part project table name')
    return '.'.join('`' + part + '`' for part in name.split('.'))


def quoted_column(name):
    return '`' + name.replace('`', '``') + '`'


def protected_column(name):
    lower = name.lower()
    return (lower.endswith(('_id', '_sk')) or name.endswith('Id')
            or lower in {'environment', 'application_code', 'billing_month'}
            or lower.endswith('cost') or lower.endswith('quantity')
            or lower in {'billingperiodstart', 'billingperiodend', 'chargeperiodstart', 'chargeperiodend'})


def plan_table(spark, name, columns=None, environment=None):
    frame = spark.table(name)
    if environment is not None:
        frame = frame.where(f"environment = '{environment}'")
    if columns is None:
        columns = [f.name for f in frame.schema.fields
                   if f.dataType.simpleString() == 'string' and not f.name.startswith('_')]
    if not columns:
        return {}
    counts = frame.selectExpr(*privacy_expressions(columns)).first().asDict()
    return {name: int(count) for name, count in counts.items() if count}


def money_snapshot(spark, name):
    """Compare month-level counts and four cost bases with decimal aggregation."""
    from pyspark.sql import functions as F
    frame = spark.table(name)
    available = set(frame.columns)
    if 'billing_month' in available:
        period = F.col('billing_month')
    elif 'BillingPeriodStart' in available:
        period = F.substring(F.col('BillingPeriodStart').cast('string'), 1, 7)
    else:
        period = F.lit('ALL')
    costs = [column for column in frame.columns
             if column.lower().replace('_', '') in {
                 'billedcost', 'effectivecost', 'listcost', 'contractedcost',
                 'totalbilledcost', 'totaleffectivecost', 'totallistcost', 'totalcontractedcost'}]
    aggregates = [F.count('*').alias('rows')]
    aggregates += [F.sum(F.col(c).cast('decimal(38,12)')).alias(c) for c in costs]
    return [r.asDict() for r in frame.groupBy(period.alias('period')).agg(*aggregates).orderBy('period').collect()]


def project_tags(rows, sanitizer):
    """Rekey sanitized tags by the SAME hash formula as Gold SQL; deduplicate."""
    mapping, tags = {}, {}
    for row in rows:
        old, key, value = row['tag_sk'], row['tag_key'], row['tag_value']
        if old in mapping or key is None or value is None:
            raise ValueError('Invalid or duplicate existing tag key; repair refused')
        key, value = sanitizer(key).strip(), sanitizer(value).strip()
        if not key or not value:
            raise ValueError('Sanitization produced an empty tag')
        new = hashlib.sha256(f'tag||{key}||{value}'.encode()).hexdigest()
        mapping[old] = new
        if new in tags and tags[new] != (new, key, value):
            raise ValueError('Unexpected tag hash collision')
        tags[new] = (new, key, value)
    return sorted(tags.values()), sorted(mapping.items())


def source_volume_uri(uri, config):
    """Normalize metadata file paths; do not read unrelated locations."""
    uri = uri.removeprefix('dbfs:')
    prefix = f'gs://{config.gcs_bucket}/{config.active_prefix.strip("/")}/'
    if uri.startswith(prefix):
        uri = config.source_volume.rstrip('/') + '/' + uri[len(prefix):]
    if not uri.startswith(config.source_volume.rstrip('/') + '/') or not uri.endswith('.parquet'):
        raise ValueError('Loaded source lineage is outside the configured RAW Volume')
    if any(part in {'.', '..'} for part in uri.split('/')):
        raise ValueError('Invalid source path traversal')
    return uri


def verify_source_copy(spark, bronze, raw, uri, changes, udf_name):
    """Require uploaded RAW to equal the cleaned Bronze multiset, not just totals.

    SHA-256 row fingerprints plus multiplicities check all values, including
    identifiers, dates and tags. No ordering or invented Parquet line numbers.
    """
    from pyspark.sql import functions as F
    before = spark.table(bronze).where(F.col('_source_file') == uri)
    columns = sorted(c for c in before.columns if not c.startswith('_'))
    if sorted(raw.columns) != columns:
        raise ValueError(f'RAW schema columns differ from loaded Bronze: {uri}')
    expected = before.select(*columns)
    for column in changes:
        if column in columns:
            expected = expected.withColumn(column, F.call_udf(udf_name, F.col(column)))
    actual = raw.select(*columns)
    if [f.dataType for f in expected.schema.fields] != [f.dataType for f in actual.schema.fields]:
        raise ValueError(f'RAW schema types differ from loaded Bronze: {uri}')
    def fingerprints(frame):
        payload = F.to_json(F.struct(*[F.col(c) for c in columns]), options={'ignoreNullFields': 'false'})
        return frame.select(F.sha2(payload, 256).alias('row_hash')).groupBy('row_hash').count()
    old, new = fingerprints(expected), fingerprints(actual)
    if old.exceptAll(new).limit(1).count() or new.exceptAll(old).limit(1).count():
        raise ValueError(f'Uploaded RAW is not an exact cleaned copy of loaded Bronze: {uri}; no table updated')


def run(spark, config, policy, confirmation=''):
    """Plan by default; explicitly apply in DEV, validate, then apply in PROD.

    Historical Delta versions still contain old text until a separately approved
    retention cleanup. No VACUUM, catalog drop, fact reload or entitlement update.
    """
    if config.environment not in {'dev', 'prod'} or policy.POLICY_VERSION != POLICY_VERSION:
        raise ValueError('Unexpected environment or privacy policy')
    if confirmation not in {'', CONFIRMATION}:
        raise ValueError('Invalid confirmation; no writes performed')
    tables = [t for t in business_tables(config) if table_exists(spark, t)]
    if not tables:
        raise ValueError('No loaded business tables; use normal initialization instead')
    scope = f'{config.operations_catalog}.security.business_scope'
    plan = {t: plan_table(spark, t) for t in tables}
    if table_exists(spark, scope):
        plan[scope] = plan_table(spark, scope, ['application_name'], config.environment)
    if not confirmation:
        return {'status': 'DRY_RUN', 'environment': config.environment,
                'findings': {t: c for t, c in plan.items() if c},
                'next': 'Publish verified clean RAW files, pause jobs and dashboard reads, then set the exact confirmation.'}

    from pyspark import cloudpickle
    from pyspark.sql import functions as F, types as T
    # The independent module exists on the driver, not on executors. Serialize
    # its pure text function by value instead of adding a production dependency.
    cloudpickle.register_pickle_by_value(policy)
    sanitizer = policy.sanitize_text
    udf_name = 'finops_privacy_' + uuid4().hex
    spark.udf.register(udf_name, sanitizer, T.StringType())
    sources = [config.table(k, layer) for k, layer in DERIVED_TABLES
               if table_exists(spark, config.table(k, layer))]
    # Preflight every loaded source BEFORE any update; normal jobs must not
    # restore the previous names on their next run.
    uris = {}
    bronze_sources = [config.table(k, layer) for k, layer in DERIVED_TABLES if layer == 'bronze'
                      and table_exists(spark, config.table(k, layer))]
    for table in bronze_sources:
        if '_source_file' not in spark.table(table).columns:
            raise ValueError('Source lineage is missing; repair refused')
        for row in spark.table(table).select('_source_file').distinct().collect():
            uri = row[0]
            if uri in uris and uris[uri] != table:
                raise ValueError('The same source appears in two Bronze tables; review lineage first')
            uris[uri] = table
    if not uris or None in uris:
        raise ValueError('Source lineage is empty or null; repair refused')
    for uri in sorted(uris):
        path = source_volume_uri(uri, config)
        raw = spark.read.parquet(path)
        assert_source_privacy(raw, path)
        verify_source_copy(spark, uris[uri], raw, uri, plan.get(uris[uri], {}), udf_name)

    mutable = sources + [config.table(k, 'gold') for k in GOLD_TABLE_KEYS
                         if k not in {'dim_tag', 'bridge_resource_tag', 'fact_cost_usage'}
                         and table_exists(spark, config.table(k, 'gold'))]
    for table in mutable:
        protected = [c for c in plan.get(table, {}) if protected_column(c)]
        if protected:
            raise ValueError(f'Privacy findings in protected keys/financial fields: {table}, {protected}; no updates performed')
        # JSON repair must not corrupt a map or change an application entitlement key.
        for column in plan.get(table, {}):
            if column in {'Tags', 'tags_raw', 'x_SkuDetails', 'sku_details'}:
                old = F.from_json(F.col(column), 'MAP<STRING,STRING>')
                new = F.from_json(F.call_udf(udf_name, F.col(column)), 'MAP<STRING,STRING>')
                invalid = ~F.size(old).eqNullSafe(F.size(new))
                if column in {'Tags', 'tags_raw'}:
                    invalid = invalid | ~old.getItem('ApplicationCode-Symphony').eqNullSafe(new.getItem('ApplicationCode-Symphony'))
                if spark.table(table).where(invalid).limit(1).count():
                    raise ValueError(f'JSON structure or application code would change: {table}.{column}; no updates performed')

    physical = [t for t in tables if spark.catalog.getTable(t).tableType.upper() != 'VIEW']
    if table_exists(spark, scope):
        physical.append(scope)
    versions = {t: delta_version(spark, t) for t in physical}
    print('RECOVERY VERSIONS (save this output before continuing): ' + json.dumps(versions), flush=True)
    for table, version in versions.items():
        print(f'-- Manual recovery only: RESTORE TABLE {quoted_table(table)} TO VERSION AS OF {version};')
    fact = config.table('fact_cost_usage', 'gold')
    protected_money = sources + [fact, config.table('dm_monthly_billing', 'datamart')]
    baseline = {t: money_snapshot(spark, t) for t in protected_money if table_exists(spark, t)}
    run_id = start_run(spark, config, 'privacy_repair')
    bridge_stage = None
    try:
        tag_table, bridge_table = config.table('dim_tag', 'gold'), config.table('bridge_resource_tag', 'gold')
        new_tag_frame = None
        if plan.get(tag_table):
            tag_frame = spark.table(tag_table)
            if set(tag_frame.columns) != {'tag_sk', 'tag_key', 'tag_value'} or tag_frame.limit(100001).count() > 100000:
                raise ValueError('Unexpected or oversized tag dimension; use a reviewed distributed migration')
            tag_rows = [r.asDict() for r in tag_frame.select('tag_sk', 'tag_key', 'tag_value').collect()]
            tags, mapping = project_tags(tag_rows, sanitizer)
            new_tag_frame = spark.createDataFrame(tags, tag_frame.select('tag_sk', 'tag_key', 'tag_value').schema)
            map_frame = spark.createDataFrame(mapping, 'old_tag_sk string, new_tag_sk string')
            bridge = spark.table(bridge_table)
            if set(bridge.columns) != {'resource_sk', 'tag_sk', 'valid_from', 'valid_to'}:
                raise ValueError('Unexpected bridge schema; repair refused')
            if bridge.where('valid_to IS NOT NULL').limit(1).count():
                raise ValueError('Closed tag intervals need a separately reviewed temporal migration')
            joined = bridge.join(F.broadcast(map_frame), bridge.tag_sk == map_frame.old_tag_sk, 'left')
            if joined.where(F.col('new_tag_sk').isNull()).limit(1).count():
                raise ValueError('Orphan tag relationship exists before repair')
            new_bridge = joined.groupBy('resource_sk', F.col('new_tag_sk').alias('tag_sk')).agg(
                F.min('valid_from').alias('valid_from'),
                F.when(F.count('*') > F.count('valid_to'), F.lit(None).cast('timestamp'))
                 .otherwise(F.max('valid_to')).alias('valid_to'),
            )
            bridge_stage = config.schema('gold') + '._privacy_bridge_' + uuid4().hex
            new_bridge.select(*bridge.columns).write.format('delta').mode('errorifexists').saveAsTable(bridge_stage)
            print('Temporary clean bridge for this run: ' + bridge_stage, flush=True)
            print(f'Tags before/after canonical deduplication: {len(tag_rows)}/{len(tags)}', flush=True)

        for table in mutable:
            columns = list(plan.get(table, {}))
            if columns:
                assignments = ', '.join(f'{quoted_column(c)} = {udf_name}({quoted_column(c)})' for c in columns)
                condition = ' OR '.join('(' + privacy_condition(c) + ')' for c in columns)
                spark.sql(f'UPDATE {quoted_table(table)} SET {assignments} WHERE {condition}').collect()
        if new_tag_frame is not None:
            view = 'finops_privacy_tags_' + uuid4().hex
            new_tag_frame.createOrReplaceTempView(view)
            try:
                tag_fields = ', '.join(quoted_column(c) for c in spark.table(tag_table).columns)
                spark.sql(f'INSERT OVERWRITE {quoted_table(tag_table)} SELECT {tag_fields} FROM {view}').collect()
                fields = ', '.join(quoted_column(c) for c in spark.table(bridge_table).columns)
                spark.sql(f'INSERT OVERWRITE {quoted_table(bridge_table)} SELECT {fields} FROM {quoted_table(bridge_stage)}').collect()
            finally:
                spark.catalog.dropTempView(view)
            orphans = spark.table(bridge_table).join(spark.table(tag_table).select('tag_sk'), 'tag_sk', 'left_anti')
            if orphans.limit(1).count():
                raise ValueError('Orphan tag relationship after repair; keep jobs paused')
        if plan.get(scope):
            spark.sql(f"UPDATE {quoted_table(scope)} SET application_name = {udf_name}(application_name) WHERE environment = '{config.environment}'").collect()
        refresh_datamarts(spark, config)
        for table, before in baseline.items():
            if money_snapshot(spark, table) != before:
                raise ValueError(f'Financial baseline changed: {table}; keep jobs paused and use the recovery versions')
        remaining = {t: plan_table(spark, t) for t in tables}
        if table_exists(spark, scope):
            remaining[scope] = plan_table(spark, scope, ['application_name'], config.environment)
        if any(remaining.values()):
            raise ValueError('Residual privacy findings remain; keep jobs paused')
        finish_run(spark, config, run_id, 'SUCCESS', 'Targeted text repair; costs and application keys preserved; old Delta versions require restricted retention.')
        if bridge_stage:
            spark.sql(f'DROP TABLE {quoted_table(bridge_stage)}').collect()
        return {'status': 'PASS', 'environment': config.environment, 'run_id': run_id,
                'policy_version': POLICY_VERSION, 'recovery_versions': versions,
                'limits': 'Current snapshots only. Old Delta versions, GCS object versions, operator logs and original local files are not erased.'}
    except Exception as exc:
        finish_run(spark, config, run_id, 'FAILED', str(exc))
        print('STOP: keep jobs and dashboard paused. Do not blindly rerun or restore only one side of the tag relationship.', flush=True)
        if bridge_stage:
            print('Retained clean staging table for diagnosis: ' + bridge_stage, flush=True)
        raise
