"""Collect small validated platform-cost aggregates and publish one GCS object.

Run through the repository notebook: it adds the dashboard package to sys.path
so collection and serving use exactly the same publication contract.
"""

from datetime import date, datetime, timezone
from decimal import Decimal, localcontext
import hashlib
import json
import re
from uuid import uuid4

from finops_cloud.sql.runner import sql_text


VOLUME = '/Volumes/finops_ops/monitoring/platform_cost_files'
MONTHLY = 'finops_ops.monitoring.platform_cost_monthly'
DAILY = 'finops_ops.monitoring.platform_cost_daily'
AUDIT = 'finops_ops.monitoring.platform_cost_collection_run'
MAX_ROWS = 10000
MAX_BYTES = 4 * 1024 * 1024
RUN_NAME = re.compile(r'^\d{8}T\d{6}Z_[a-f0-9]{32}$')
SQL = 'monitoring/platform_costs/02_collect_databricks_daily.sql'


def latest_complete_export(fs, now):
    """Never mix shards from successive exports or consume unfinished exports."""
    from platform_costs.snapshot import check_freshness
    base = VOLUME + '/extracts/gcp'
    directories = sorted((item.name.rstrip('/') for item in fs.ls(base)
                          if RUN_NAME.fullmatch(item.name.rstrip('/'))), reverse=True)
    for name in directories[:20]:
        directory = base + '/' + name
        files = fs.ls(directory)
        manifests = [item for item in files if re.fullmatch(r'complete-\d+\.json', item.name)]
        if not manifests:
            continue
        if len(manifests) != 1 or manifests[0].size > 16384:
            raise ValueError('Invalid GCP completion manifest.')
        manifest = json.loads(fs.head(directory + '/' + manifests[0].name, 16384))
        if not isinstance(manifest, dict):
            raise ValueError('Invalid GCP completion manifest.')
        version = manifest.get('schema_version')
        if type(version) is not int and not (isinstance(version, str) and version in {'1', '2'}):
            raise ValueError('Unsupported GCP manifest version.')
        version = int(version)
        expected = {'schema_version', 'run_id', 'extracted_at', 'row_count', 'status'}
        if version == 2:
            expected.add('granularity')
        if not isinstance(manifest, dict) or set(manifest) != expected:
            raise ValueError('Unexpected GCP manifest fields.')
        if version not in {1, 2} or manifest['run_id'] != name or manifest['status'] != 'COMPLETE':
            raise ValueError('Inconsistent GCP completion manifest.')
        if version == 2 and manifest['granularity'] != 'daily':
            raise ValueError('Unsupported GCP export granularity.')
        raw_count = manifest['row_count']  # BigQuery JSON represents INT64 as strings.
        if not (type(raw_count) is int or isinstance(raw_count, str) and re.fullmatch(r'[0-9]+', raw_count)):
            raise ValueError('Invalid GCP row count.')
        count = int(raw_count)
        if not 1 <= count <= MAX_ROWS:
            raise ValueError('Invalid GCP row count.')
        check_freshness(manifest['extracted_at'], now)
        if not any(re.fullmatch(r'data-\d+\.parquet', item.name) for item in files):
            raise ValueError('Completed GCP export has no data shards.')
        return directory, {**manifest, 'schema_version': version, 'row_count': count}
    raise ValueError('No completed GCP export found; run the BigQuery export first.')


def prepare_payload(gcp_rows, databricks_rows, manifest, now):
    from platform_costs.snapshot import build_payload
    from platform_costs.model import COLUMNS, monthly_from_daily
    if len(gcp_rows) != manifest['row_count']:
        raise ValueError('GCP export row count differs from its completion manifest.')
    for rows, provider in ((gcp_rows, 'GCP'), (databricks_rows, 'Databricks')):
        if not rows or any(row.get('provider') != provider for row in rows):
            raise ValueError('Missing source or wrong source provider.')
        if any(row.get('period_status') != 'partial' for row in rows):
            raise ValueError('Automatic collection cannot declare billing months closed.')
    daily_records = None
    if str(manifest['schema_version']) == '2':
        daily_records = gcp_rows + databricks_rows
        monthly = monthly_from_daily(daily_records)
        records = [{key: row[key] for key in COLUMNS} for row in monthly.to_dict('records')]
    else:
        # Transitional monthly GCP export: keep the published format monthly.
        # Never display partial Databricks-only daily data as a combined daily source.
        if databricks_rows and 'usage_date' in databricks_rows[0]:
            monthly = monthly_from_daily(databricks_rows)
            databricks_rows = [{key: row[key] for key in COLUMNS} for row in monthly.to_dict('records')]
        records = gcp_rows + databricks_rows
    return build_payload(records, generated_at=now.isoformat(),
                         gcp_extracted_at=manifest['extracted_at'], daily_records=daily_records)


def exact_decimal(value):
    """Reject precision loss instead of letting Spark silently round or overflow."""
    if value is None or value == '':
        return None
    decimal = Decimal(str(value))
    with localcontext() as context:
        context.prec = 80
        normalized = decimal.normalize()
        if not decimal.is_finite() or normalized.as_tuple().exponent < -18 or abs(decimal) >= Decimal('1e20'):
            raise ValueError('A platform cost decimal cannot fit DECIMAL(38,18) exactly.')
    return decimal


def _collect(frame):
    rows = frame.limit(MAX_ROWS + 1).collect()
    if len(rows) > MAX_ROWS:
        raise ValueError('Platform cost export exceeds the row limit.')
    return [row.asDict(recursive=True) for row in rows]


def _aggregate_frame(spark, records, run_id, now, *, daily=False):
    # Table schema is explicit: all-null GCP usage/Databricks credits stay typed.
    schema = ('month string, provider string, service string, currency string, '
              'cost_before_credits decimal(38,18), credits decimal(38,18), '
              'usage_quantity decimal(38,18), usage_unit string, cost_basis string, '
              'period_status string, collection_run_id string, collected_at timestamp')
    if daily:
        schema = 'usage_date date, ' + schema
    data = []
    for row in records:
        values = (row['month'], row['provider'], row['service'], row['currency'],
                     exact_decimal(row['cost_before_credits']), exact_decimal(row['credits']),
                     exact_decimal(row['usage_quantity']), row['usage_unit'], row['cost_basis'],
                     row['period_status'], run_id, now.replace(tzinfo=None))
        data.append((date.fromisoformat(row['usage_date']), *values) if daily else values)
    return spark.createDataFrame(data, schema)


def _monthly_frame(spark, records, run_id, now):
    return _aggregate_frame(spark, records, run_id, now)


def _daily_frame(spark, records, run_id, now):
    return _aggregate_frame(spark, records, run_id, now, daily=True)


def _audit(spark, run_id, started, status, manifest, gcp_count, db_count, digest=None):
    from platform_costs.snapshot import utc_timestamp
    schema = ('run_id string, started_at timestamp, finished_at timestamp, status string, '
              'gcp_export_run_id string, gcp_extracted_at timestamp, gcp_rows int, '
              'databricks_rows int, snapshot_sha256 string, error_code string')
    extracted = utc_timestamp(manifest['extracted_at']).replace(tzinfo=None) if manifest else None
    data = [(run_id, started.replace(tzinfo=None), datetime.now(timezone.utc).replace(tzinfo=None),
             status, manifest['run_id'] if manifest else None, extracted,
             gcp_count, db_count, digest, None if status == 'PUBLISHED' else 'COLLECTION_FAILED')]
    spark.createDataFrame(data, schema).write.mode('append').insertInto(AUDIT)


def run(spark, dbutils, *, confirmation='', dry_run=True):
    """Preview is default; publication requires an explicit reviewed Job parameter."""
    if not dry_run and confirmation != 'PUBLISH_PLATFORM_COSTS':
        raise ValueError('Set confirmation=PUBLISH_PLATFORM_COSTS to enable writes.')
    spark.conf.set('spark.sql.session.timeZone', 'UTC')
    started = datetime.now(timezone.utc)
    run_id = uuid4().hex
    manifest = None
    gcp_count = db_count = 0
    try:
        directory, manifest = latest_complete_export(dbutils.fs, started)
        gcp_frame = spark.read.parquet(directory + '/data-*.parquet')
        db_frame = spark.sql(sql_text(SQL))
        gcp_rows, db_rows = _collect(gcp_frame), _collect(db_frame)
        gcp_count, db_count = len(gcp_rows), len(db_rows)
        payload = prepare_payload(gcp_rows, db_rows, manifest, started)
        content = json.dumps(payload, allow_nan=False, separators=(',', ':'))
        if len(content.encode('utf-8')) > MAX_BYTES:
            raise ValueError('Platform cost snapshot exceeds its publication size limit.')
        monthly = _monthly_frame(spark, payload['records'], run_id, started)
        daily_records = payload.get('daily_records')
        daily = _daily_frame(spark, daily_records, run_id, started) if daily_records is not None else None
        summary = {'status': 'PREVIEW' if dry_run else 'PUBLISHED',
                   'gcp_rows': gcp_count, 'databricks_rows': db_count,
                   'gcp_extracted_at': manifest['extracted_at'],
                   'period_status': 'partial', 'collection_run_id': run_id,
                   'granularity': 'daily' if daily_records is not None else 'monthly',
                   'daily_rows': len(daily_records or [])}
        if dry_run:
            return summary
        # Additive setup must already have been executed manually.
        expected = monthly.columns
        if spark.table(MONTHLY).columns != expected:
            raise ValueError('Unexpected platform cost table schema; no overwrite allowed.')
        if daily is not None and spark.table(DAILY).columns != daily.columns:
            raise ValueError('Unexpected daily cost schema; run 03_create_monitoring_objects.sql first.')
        spark.table(AUDIT).limit(0).collect()
        # Delta replacement is one snapshot, not append: reruns cannot duplicate costs.
        monthly.write.mode('overwrite').insertInto(MONTHLY)
        if daily is not None:
            daily.write.mode('overwrite').insertInto(DAILY)
        # Use one object write, not a cloud filesystem rename/copy; never remove old output first.
        dbutils.fs.mkdirs(VOLUME + '/published')
        dbutils.fs.put(VOLUME + '/published/latest.json', content, overwrite=True)
        digest = hashlib.sha256(content.encode('utf-8')).hexdigest()
        _audit(spark, run_id, started, 'PUBLISHED', manifest, gcp_count, db_count, digest)
        return summary
    except Exception:
        if not dry_run:
            try:
                _audit(spark, run_id, started, 'FAILED', manifest, gcp_count, db_count)
            except Exception:
                pass  # Preserve the original diagnostic, never log credentials/error bodies.
        raise
