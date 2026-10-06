"""Read-only privacy and financial controls; the targeted repair is retired.

Rebuild managed business tables from verified clean RAW with privacy_rebuild.
No text mapping, Python executor UDF, tag rekeying or separate bridge repair.
"""
from __future__ import annotations

import re
from finops_cloud.medallion.initialize import business_tables
from finops_cloud.medallion.privacy import POLICY_VERSION, privacy_expressions


def quoted_table(name):
    if not re.fullmatch(r'[A-Za-z0-9_]+\.[A-Za-z0-9_]+\.[A-Za-z0-9_]+', name):
        raise ValueError('Expected a three-part project table name')
    return '.'.join(chr(96) + part + chr(96) for part in name.split('.'))


def plan_table(spark, name, columns=None, environment=None):
    """One aggregate over known text patterns; returns counts, never values."""
    frame = spark.table(name)
    if environment is not None:
        if environment not in {'dev', 'prod'}:
            raise ValueError('Unexpected environment')
        frame = frame.where(f"environment = '{environment}'")
    if columns is None:
        columns = [f.name for f in frame.schema.fields
                   if f.dataType.simpleString() == 'string' and not f.name.startswith('_')]
    if not columns:
        return {}
    counts = frame.selectExpr(*privacy_expressions(columns)).first().asDict()
    return {column: int(count) for column, count in counts.items() if count}


def money_snapshot(spark, name):
    """Month-level row counts and decimal cost totals; no writes."""
    from pyspark.sql import functions as F
    frame = spark.table(name)
    available = set(frame.columns)
    if 'billing_month' in available:
        period = F.col('billing_month')
    elif 'BillingPeriodStart' in available:
        period = F.substring(F.col('BillingPeriodStart').cast('string'), 1, 7)
    else:
        period = F.lit('ALL')
    costs = [c for c in frame.columns if c.lower().replace('_', '') in {
        'billedcost', 'effectivecost', 'listcost', 'contractedcost',
        'totalbilledcost', 'totaleffectivecost', 'totallistcost', 'totalcontractedcost',
        'monthlybilledcost'}]
    aggregates = [F.count('*').alias('rows')]
    aggregates += [F.sum(F.col(c).cast('decimal(38,12)')).alias(c) for c in costs]
    return [r.asDict() for r in frame.groupBy(period.alias('period')).agg(*aggregates)
            .orderBy('period').collect()]


def source_volume_uri(uri, config):
    """Normalize loaded lineage, confined to the configured RAW Volume."""
    if not isinstance(uri, str):
        raise ValueError('Missing source lineage')
    uri = uri.removeprefix('dbfs:')
    prefix = f'gs://{config.gcs_bucket}/{config.active_prefix.strip("/")}/'
    if uri.startswith(prefix):
        uri = config.source_volume.rstrip('/') + '/' + uri[len(prefix):]
    if not uri.startswith(config.source_volume.rstrip('/') + '/') or not uri.endswith('.parquet'):
        raise ValueError('Loaded source lineage is outside the configured RAW Volume')
    if any(part in {'.', '..'} for part in uri.split('/')):
        raise ValueError('Invalid source path traversal')
    return uri


def run(spark, config, policy, confirmation=''):
    """Compatibility entry point: inventory only, never APPLY."""
    if confirmation:
        raise ValueError('Privacy repair APPLY is retired; use rebuild_clean_environment.ipynb')
    if config.environment not in {'dev', 'prod'} or policy.POLICY_VERSION != POLICY_VERSION:
        raise ValueError('Unexpected environment or policy')
    findings = {t: plan_table(spark, t) for t in business_tables(config)
                if spark.catalog.tableExists(t)}
    return {'status': 'DRY_RUN', 'environment': config.environment,
            'findings': {t: c for t, c in findings.items() if c},
            'next': 'Follow docs/privacy_rebuild.md; no managed data was changed.'}


def run_targeted(*args, **kwargs):
    """Refuse old notebook calls retained in a Workspace or Git history."""
    raise ValueError('Targeted privacy repair is retired; use rebuild_clean_environment.ipynb')
