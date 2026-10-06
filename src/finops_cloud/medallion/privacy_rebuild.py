"""Manual, checkpointed business rebuild, reusing the monthly/daily pipelines.

Never called by a Job. No cross-table transaction or automatic restore: keep
jobs/dashboard paused after a failure and preserve the private checkpoint.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
import json
from pathlib import Path

from finops_cloud.medallion.delta import delta_version
from finops_cloud.medallion.initialize import business_tables
from finops_cloud.medallion.privacy_repair import (
    money_snapshot, plan_table, quoted_table, source_volume_uri,
)
from finops_cloud.pipelines.billing_backfill import month_range
from finops_cloud.sql.runner import render_sql, split_statements, table_context

BELGIUM_METASTORE = 'gcp:europe-west1:59a04d75-f8cd-4538-a893-9fa79922e4bb'
WORKSPACE_USERS = Path('/Workspace/Users')
STAGES = ('plan', 'reset', 'monthly', 'daily', 'validate', 'recover_charge_schema')
FORMAT = 'finops-business-rebuild-v1'


def _charge_schema_plan(spark, config):
    """Recognize only the known legacy attribute, never arbitrary schema drift."""
    expected = {
        config.table('dim_charge_type', 'gold'):
            {'charge_type_sk', 'charge_category', 'charge_frequency'},
        config.table('dm_cost_by_charge_type', 'datamart'):
            {'billing_month', 'charge_category', 'charge_frequency', 'total_billed_cost'},
    }
    legacy = []
    for table, columns in expected.items():
        actual = set(spark.table(table).columns)
        if actual == columns | {'charge_subcategory'}:
            legacy.append(table)
        elif actual != columns:
            raise ValueError(f'Unexpected charge schema; inspect before reset: {table}')
    return legacy


def _repair_empty_charge_schema(spark, config, legacy):
    """Use the SQL-owned schemas only after the business reset has left them empty."""
    if not legacy:
        return
    dimension = config.table('dim_charge_type', 'gold')
    mart = config.table('dm_cost_by_charge_type', 'datamart')
    fact = config.table('fact_cost_usage', 'gold')
    for table in (dimension, mart, fact):
        if spark.table(table).limit(1).count():
            raise ValueError('Charge schema replacement requires empty dimension, fact and mart')
    values = table_context(config)
    if dimension in legacy:
        ddl = render_sql('gold/table_creation/00_create_gold_tables.sql', values)
        prefix = f'CREATE TABLE IF NOT EXISTS {dimension} ('
        matches = [s for s in split_statements(ddl) if s.startswith(prefix)]
        if len(matches) != 1:
            raise ValueError('Cannot locate the SQL-owned charge dimension definition')
        replacement = matches[0].replace('CREATE TABLE IF NOT EXISTS', 'CREATE OR REPLACE TABLE', 1)
        spark.sql(replacement).collect()
    if mart in legacy:
        spark.sql(render_sql('datamarts/table_refresh/06_dm_cost_by_charge_type.sql', values)).collect()
    if _charge_schema_plan(spark, config):
        raise ValueError('Legacy charge schema remains; keep maintenance paused')


def _reset_business(spark, config, names):
    legacy = _charge_schema_plan(spark, config)  # Refuse unknown drift BEFORE truncation.
    for name in reversed(names):
        spark.sql(f'TRUNCATE TABLE {quoted_table(name)}').collect()
    for name in names:
        if spark.table(name).limit(1).count():
            raise ValueError('Reset did not leave every business table empty')
    _repair_empty_charge_schema(spark, config, legacy)
    return legacy


def validate_scope(config):
    if (config.environment not in {'dev', 'prod'}
            or config.catalog != f'finops_{config.environment}'
            or config.raw_catalog != 'finops_raw'
            or config.operations_catalog != 'finops_ops'
            or config.source_volume != '/Volumes/finops_raw/landing/focus'
            or config.schemas != {'bronze': 'bronze', 'silver': 'silver',
                                  'gold': 'gold', 'datamart': 'datamart'}):
        raise ValueError('Unexpected rebuild catalog/schema/RAW scope')
    names = business_tables(config)
    if len(names) != 30 or len(set(names)) != 30:
        raise ValueError('Expected exactly 30 distinct business tables')
    for name in names:
        quoted_table(name)
        if not name.startswith(config.catalog + '.'):
            raise ValueError('Cross-environment target refused')
    return names


def source_manifest(rows, config, months):
    """Active Silver lineage, never a discovery of all available daily RAW."""
    monthly, daily = {}, {}
    for row in rows:
        month, kind = row['billing_month'], row['_source_type']
        month_range(month, month)
        path = source_volume_uri(row['_source_file'], config)
        if kind == 'MONTHLY_BILLING':
            if path != config.billing_volume_uri(month):
                raise ValueError('Monthly lineage differs from configured billing path')
            monthly.setdefault(month, set()).add(path)
        elif kind == 'DAILY':
            if month in months:
                raise ValueError('Daily rows coexist with the authoritative monthly range')
            try:
                day = date.fromisoformat(path.rsplit('/', 1)[1].removesuffix('.parquet'))
            except ValueError as exc:
                raise ValueError('Unexpected daily file name') from exc
            if path != config.daily_volume_uri(day.isoformat()):
                raise ValueError('Daily lineage differs from configured daily path')
            if path in daily and daily[path] != month:
                raise ValueError('Daily source belongs to multiple billing months')
            daily[path] = month
        else:
            raise ValueError('Unknown or missing Silver source type')
    if set(monthly) != set(months) or any(len(paths) != 1 for paths in monthly.values()):
        raise ValueError('Requested monthly range must exactly match loaded monthly Silver')
    return {'monthly': [{'month': m, 'uri': next(iter(monthly[m]))} for m in months],
            'daily': [{'month': daily[p], 'uri': p} for p in sorted(daily)]}


def compare_money(expected, actual, *, tolerance='0'):
    """Counts exact, decimal totals exact except explicit mart tolerance."""
    def indexed(rows):
        result = {row['period']: row for row in rows}
        if len(result) != len(rows) or None in result:
            raise ValueError('Duplicate financial period')
        return result
    before, after = indexed(expected), indexed(actual)
    if before.keys() != after.keys():
        raise ValueError('Financial periods changed')
    for period in before:
        a, b = before[period], after[period]
        if a.keys() != b.keys() or a['rows'] != b['rows']:
            raise ValueError(f'Financial row count/columns changed for {period}')
        for column in a.keys() - {'period', 'rows'}:
            if a[column] is None or b[column] is None:
                if a[column] != b[column]:
                    raise ValueError(f'Financial NULL changed: {period}/{column}')
            elif abs(Decimal(str(a[column])) - Decimal(str(b[column]))) > Decimal(tolerance):
                raise ValueError(f'Financial amount changed: {period}/{column}')


def _control_path(path, config):
    path = Path(path).resolve()
    if (WORKSPACE_USERS.resolve() not in path.parents
            or path.name != f'rebuild_{config.environment}.json'
            or not path.parent.is_dir()
            or any((parent / '.git').exists() or (parent / 'src/finops_cloud').exists()
                   for parent in path.parents)):
        raise ValueError('Use an existing private Workspace folder outside Git, named rebuild_ENV.json')
    return path


def _save(path, state):
    state['updated_at'] = datetime.now(timezone.utc).isoformat()
    temporary = path.with_suffix('.json.tmp')
    temporary.write_text(json.dumps(state, indent=2, default=str), encoding='utf-8')
    temporary.replace(path)


def _versions(spark, names):
    versions = {name: delta_version(spark, name) for name in names}
    if any(v is None for v in versions.values()):
        raise ValueError('A required Delta table is missing')
    return versions


def _assert_versions(spark, state):
    if _versions(spark, state['expected_versions']) != state['expected_versions']:
        raise ValueError('Tables changed outside this checkpoint; stop and diagnose')


def _checkpoint_versions(spark, state, *, scope_label_updated=False):
    current = _versions(spark, state['expected_versions'])
    permitted = set(state['tables'])
    if scope_label_updated:
        permitted.add('finops_ops.security.business_scope')
    if any(current[t] != old for t, old in state['expected_versions'].items()
           if t not in permitted):
        raise ValueError('Security metadata changed outside the approved display-label update')
    state['expected_versions'] = current


def _assert_managed(spark, names):
    for name in names:
        detail = spark.sql(f'DESCRIBE DETAIL {quoted_table(name)}').first().asDict()
        metadata = spark.sql(f'DESCRIBE TABLE EXTENDED {quoted_table(name)}').collect()
        kind = next((str(r['data_type']).upper() for r in metadata
                     if r['col_name'] == 'Type'), None)
        if kind != 'MANAGED' or str(detail['format']).lower() != 'delta':
            raise ValueError(f'Only an existing managed Delta table may be reset: {name}')


def _lineage(spark, table):
    return [r.asDict() for r in spark.table(table)
            .select('billing_month', '_source_type', '_source_file').distinct().collect()]


def _guard_daily_status(spark, config, manifest):
    if not manifest['daily']:
        return
    from pyspark.sql import functions as F
    months = sorted({item['month'] for item in manifest['daily']})
    statuses = spark.table(config.table('month_status', 'ops')).where(
        (F.col('environment') == config.environment) & F.col('billing_month').isin(months))
    if statuses.where(F.col('status') != 'OPEN').limit(1).count():
        raise ValueError('Active daily months must be OPEN; no OPS status is reset automatically')


def _summary(state):
    return {'status': state['status'], 'environment': state['environment'],
            'completed': state['completed'], 'business_tables': 30,
            'monthly_files': len(state['sources']['monthly']),
            'active_daily_files': len(state['sources']['daily']),
            'replayed_months': state['monthly_done'], 'replayed_daily': len(state['daily_done']),
            'next': 'Keep jobs/dashboard paused until DEV and PROD plus profile checks pass.'}


def _business_scope_label(spark, config):
    """Only one environment-specific display label; never reseed entitlements."""
    table = quoted_table(f'{config.operations_catalog}.security.business_scope')
    env = config.environment
    rows = spark.sql(f"SELECT application_name FROM {table} WHERE environment = '{env}' "
                     "AND application_code = 'APP00013057'").collect()
    if len(rows) > 1 or any(str(r['application_name']).strip().lower()
                           not in {'ten data platform', 'data platform'} for r in rows):
        raise ValueError('Ambiguous/unexpected application scope label; inspect privately')
    if rows:
        spark.sql(f"UPDATE {table} SET application_name = 'Data Platform', "
                  f"updated_at = current_timestamp() WHERE environment = '{env}' "
                  "AND application_code = 'APP00013057'").collect()


def _validate(spark, config, state):
    for table, baseline in state['baseline'].items():
        compare_money(baseline, money_snapshot(spark, table),
                      tolerance=config.amount_tolerance if '.datamart.' in table else '0')
    for key in ('silver_canonical', 'silver_central'):
        if source_manifest(_lineage(spark, config.table(key, 'silver')), config,
                           state['months']) != state['sources']:
            raise ValueError('Rebuilt active source lineage differs from baseline')
    findings = {t: plan_table(spark, t) for t in state['tables']}
    findings = {t: counts for t, counts in findings.items() if counts}
    if findings:
        raise ValueError('Known privacy patterns remain (column counts only): ' + json.dumps(findings))
    bridge = quoted_table(config.table('bridge_resource_tag', 'gold'))
    resource = quoted_table(config.table('dim_resource', 'gold'))
    tag = quoted_table(config.table('dim_tag', 'gold'))
    orphan = spark.sql(f"SELECT count(*) AS n FROM {bridge} b LEFT JOIN {resource} r "
                       f"ON b.resource_sk = r.resource_sk LEFT JOIN {tag} t ON b.tag_sk = t.tag_sk "
                       "WHERE r.resource_sk IS NULL OR t.tag_sk IS NULL").first()['n']
    if orphan:
        raise ValueError('Orphan tag/resource bridge; stop before publication')
    labels = spark.sql(f"SELECT DISTINCT application_name FROM {resource} "
                       "WHERE application_code = 'APP00013057'").collect()
    if not labels or any(r['application_name'] != 'Data Platform' for r in labels):
        raise ValueError('APP00013057 must display Data Platform')
    _business_scope_label(spark, config)
    scope_findings = plan_table(spark, f'{config.operations_catalog}.security.business_scope',
                                ['application_name'], config.environment)
    if scope_findings:
        raise ValueError('Known privacy patterns remain in scope labels')


def _recover_first_month_charge_schema(spark, config, path, state, *, confirmation,
                                      jobs_paused, dashboard_paused, sources_verified):
    """Explicit restart of the diagnosed first-month failure, not a generic retry.

    Keep the original baseline/recovery versions. Discard only the partial first
    month by repeating the business reset, then repair the two empty schemas.
    OPS failure events and security assignments are never cleared.
    """
    if (state['status'] != 'FAILED' or state.get('failed_stage') != 'monthly'
            or state['completed'] != ['reset'] or state['monthly_done'] or state['daily_done']
            or state.get('charge_schema_recovery')):
        raise ValueError('Recovery is limited to the first monthly failure after reset')
    if (confirmation != f'RECOVER_{config.environment.upper()}_FIRST_MONTH_CHARGE_SCHEMA'
            or jobs_paused is not True or dashboard_paused is not True
            or sources_verified is not True):
        raise ValueError('Exact recovery confirmation and all maintenance acknowledgements required')
    dimension = config.table('dim_charge_type', 'gold')
    legacy = _charge_schema_plan(spark, config)
    if dimension not in legacy:
        raise ValueError('The diagnosed legacy charge dimension is not present')
    empty = [config.table(key, layer) for key, layer in (
        ('bronze_daily', 'bronze'), ('dim_charge_type', 'gold'),
        ('dim_tag', 'gold'), ('bridge_resource_tag', 'gold'), ('fact_cost_usage', 'gold'))]
    empty.extend(t for t in state['tables'] if '.datamart.' in t)
    if any(spark.table(t).limit(1).count() for t in empty):
        raise ValueError('Recovery refused: facts, tags, daily Bronze or datamarts contain rows')
    first = state['sources']['monthly'][0]
    wanted = {'monthly': [first], 'daily': []}
    for key in ('silver_canonical', 'silver_central'):
        if source_manifest(_lineage(spark, config.table(key, 'silver')), config,
                           [first['month']]) != wanted:
            raise ValueError('Recovery refused: Silver is not limited to the first planned monthly source')
    bronze_sources = spark.table(config.table('bronze_billing', 'bronze')).select(
        '_source_file', '_source_type').distinct().collect()
    if not bronze_sources or any(
            r['_source_type'] != 'MONTHLY_BILLING'
            or source_volume_uri(r['_source_file'], config) != first['uri']
            for r in bronze_sources):
        raise ValueError('Recovery refused: billing Bronze is not limited to the first planned source')
    _assert_managed(spark, state['tables'])
    _guard_daily_status(spark, config, state['sources'])
    current = _versions(spark, state['expected_versions'])
    if any(current[t] != old for t, old in state['expected_versions'].items()
           if t not in state['tables']):
        raise ValueError('Security metadata changed; schema recovery refused')
    # Preserve the failed checkpoint as a separate private file BEFORE any writes.
    backup = path.with_name(f'rebuild_{config.environment}.before-charge-schema-recovery.json')
    if backup.exists():
        raise ValueError('Recovery backup already exists; preserve it and diagnose')
    _save(backup, dict(state))
    state['charge_schema_recovery'] = {'status': 'RUNNING', 'backup': str(backup),
                                       'before_versions': current, 'tables': legacy}
    state['status'] = 'RUNNING'
    _save(path, state)
    try:
        # Detect a race since the checks above, without accepting security changes.
        if _versions(spark, current) != current:
            raise ValueError('Tables changed during recovery checks; stop and diagnose')
        _reset_business(spark, config, state['tables'])
        _checkpoint_versions(spark, state)
        state['charge_schema_recovery']['status'] = 'PASS'
        state['status'] = 'STAGE_PASS'
        state.pop('failed_stage', None)
        _save(path, state)
        return {**_summary(state), 'recovery': 'CHARGE_SCHEMA_REPAIRED', 'next_stage': 'monthly'}
    except Exception:
        state['status'] = 'FAILED'
        state['failed_stage'] = 'recover_charge_schema'
        state['charge_schema_recovery']['status'] = 'FAILED'
        _save(path, state)
        raise


def run_stage(spark, config, state_file, *, stage='plan', start_month='2025-01',
              end_month='2026-06', confirmation='', jobs_paused=False,
              dashboard_paused=False, sources_verified=False):
    """One explicit stage. PLAN writes only a private JSON checkpoint."""
    names = validate_scope(config)
    if stage not in STAGES:
        raise ValueError('Unknown rebuild stage')
    metastore = spark.sql('SELECT current_metastore() AS metastore').first()['metastore']
    if metastore != BELGIUM_METASTORE:
        raise ValueError('This rebuild is restricted to the Belgian metastore')
    path = _control_path(state_file, config)
    months = month_range(start_month, end_month)
    security = (f'{config.operations_catalog}.security.business_scope',
                f'{config.operations_catalog}.security.user_entitlement')
    if path.exists():
        state = json.loads(path.read_text(encoding='utf-8'))
        if (state.get('format') != FORMAT or state.get('environment') != config.environment
                or state.get('metastore') != metastore or state.get('tables') != list(names)
                or state.get('months') != months):
            raise ValueError('Checkpoint belongs to a different rebuild scope')
        if set(state['expected_versions']) != set((*names, *security)):
            raise ValueError('Checkpoint table inventory changed')
        stored_rows = [dict(billing_month=item['month'], _source_type=kind,
                            _source_file=item['uri'])
                       for key, kind in (('monthly', 'MONTHLY_BILLING'), ('daily', 'DAILY'))
                       for item in state['sources'][key]]
        if source_manifest(stored_rows, config, months) != state['sources']:
            raise ValueError('Checkpoint source manifest changed')
        if stage == 'recover_charge_schema':
            return _recover_first_month_charge_schema(
                spark, config, path, state, confirmation=confirmation,
                jobs_paused=jobs_paused, dashboard_paused=dashboard_paused,
                sources_verified=sources_verified)
        if state['status'] in {'FAILED', 'RUNNING'}:
            raise ValueError('Previous stage failed/interrupted; preserve checkpoint and diagnose, no blind retry')
        _assert_versions(spark, state)
        if stage == 'plan':
            return _summary(state)
    elif stage != 'plan':
        raise ValueError('Run plan first and preserve its private checkpoint')
    else:
        _assert_managed(spark, names)
        charge_schema_migrations = _charge_schema_plan(spark, config)
        versions = _versions(spark, (*names, *security))
        central, canonical = (config.table(key, 'silver')
                              for key in ('silver_central', 'silver_canonical'))
        sources = source_manifest(_lineage(spark, central), config, months)
        if source_manifest(_lineage(spark, canonical), config, months) != sources:
            raise ValueError('Canonical and central Silver source lineage differs')
        _guard_daily_status(spark, config, sources)
        for item in (*sources['monthly'], *sources['daily']):
            # Footer/schema only. This is not a full RAW privacy audit; the
            # operator must verify publication, and ingestion scans actual text.
            if not spark.read.parquet(item['uri']).columns:
                raise ValueError('Missing/invalid RAW source schema')
        measured = (canonical, central, config.table('fact_cost_usage', 'gold'),
                    config.table('dm_monthly_billing', 'datamart'))
        baseline = {t: money_snapshot(spark, t) for t in measured}
        if any(not rows for rows in baseline.values()):
            raise ValueError('Capture the baseline before any reset; a measured table is empty')
        compare_money(baseline[canonical], baseline[central])
        state = {'format': FORMAT, 'environment': config.environment, 'metastore': metastore,
                 'tables': list(names), 'months': months, 'sources': sources,
                 'baseline': baseline, 'recovery_versions': versions,
                 'expected_versions': versions, 'completed': [],
                 'charge_schema_migrations': charge_schema_migrations,
                 'monthly_done': [], 'daily_done': [], 'status': 'PLAN_READY'}
        _assert_versions(spark, state)
        _save(path, state)
        return _summary(state)
    if stage in state['completed']:
        return _summary(state)
    prerequisites = {'reset': [], 'monthly': ['reset'], 'daily': ['reset', 'monthly'],
                     'validate': ['reset', 'monthly', 'daily']}
    if not all(s in state['completed'] for s in prerequisites[stage]):
        raise ValueError('Execute reset -> monthly -> daily -> validate in order')
    if (confirmation != f'REBUILD_{config.environment.upper()}_BUSINESS_DATA'
            or jobs_paused is not True or dashboard_paused is not True
            or sources_verified is not True):
        raise ValueError('Exact confirmation and paused jobs/dashboard plus verified sources required')
    if stage == 'reset':
        _assert_managed(spark, names)
        _charge_schema_plan(spark, config)
    _guard_daily_status(spark, config, state['sources'])
    state['status'] = 'RUNNING'
    _save(path, state)
    try:
        if stage == 'reset':
            _reset_business(spark, config, names)
        elif stage == 'monthly':
            from finops_cloud.pipelines.monthly_close import run as close_month
            for item in state['sources']['monthly']:
                if item['month'] not in state['monthly_done']:
                    _assert_versions(spark, state)
                    print('Monthly replay:', item['month'], flush=True)
                    close_month(config.environment, item['month'], source_uri=item['uri'], archive=False)
                    state['monthly_done'].append(item['month'])
                    _checkpoint_versions(spark, state)
                    _save(path, state)
        elif stage == 'daily':
            from finops_cloud.pipelines.daily_incremental import run as ingest_daily
            from finops_cloud.audit.daily_controls import validate_daily_load
            for item in state['sources']['daily']:
                if item['uri'] not in state['daily_done']:
                    _assert_versions(spark, state)
                    print('Active daily replay:', item['uri'], flush=True)
                    ingest_daily(config.environment, item['uri'])
                    validate_daily_load(spark, config, item['uri'])
                    state['daily_done'].append(item['uri'])
                    _checkpoint_versions(spark, state)
                    _save(path, state)
        else:
            _validate(spark, config, state)
        state['completed'].append(stage)
        _checkpoint_versions(spark, state, scope_label_updated=stage == 'validate')
        state['status'] = 'PASS' if stage == 'validate' else 'STAGE_PASS'
        _save(path, state)
        return _summary(state)
    except Exception:
        state['status'] = 'FAILED'
        state['failed_stage'] = stage
        _save(path, state)
        raise
