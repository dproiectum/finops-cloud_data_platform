"""One-off, manually confirmed promotion of verified clean DEV tables to PROD.

This is not the daily pipeline. It never replays ingestion, copies OPS tables,
clears audit history, resets catalogs, or automatically restores failed copies.
"""
from __future__ import annotations

import json
from pathlib import Path

from finops_cloud.audit.runs import finish_run, set_month_status, start_run
from finops_cloud.medallion import privacy_rebuild as rebuild
from finops_cloud.medallion.gold import refresh_cost_allocation_view
from finops_cloud.medallion.privacy_repair import money_snapshot, quoted_table
from finops_cloud.sql.runner import split_statements, sql_text

FORMAT = 'finops-dev-to-prod-deep-clone-v1'
CONFIRMATION = 'PROMOTE_CLEAN_DEV_TO_PROD'
STAGES = ('plan', 'copy', 'validate')


def _scope(dev, prod):
    if dev.environment != 'dev' or prod.environment != 'prod':
        raise ValueError('Only DEV -> PROD is supported')
    for attribute in ('contract_version', 'focus_version', 'provider', 'currency',
                      'corporate_regions', 'source_volume', 'amount_tolerance'):
        if getattr(dev, attribute) != getattr(prod, attribute):
            raise ValueError(f'DEV/PROD configuration differs: {attribute}')
    return list(zip(rebuild.validate_scope(dev), rebuild.validate_scope(prod), strict=True))


def _private_path(path, prod):
    path = Path(path).resolve()
    if path.name != 'promote_dev_to_prod.json':
        raise ValueError('Promotion checkpoint must be named promote_dev_to_prod.json')
    # Reuse the Workspace-only, existing-folder and outside-Git path guard.
    rebuild._control_path(path.with_name('rebuild_prod.json'), prod)
    return path


def _schema(spark, table):
    return [[field.name, field.dataType.simpleString(), field.nullable]
            for field in spark.table(table).schema.fields]


def _grants(spark, table):
    rows = [r.asDict() for r in spark.sql(f'SHOW GRANTS ON TABLE {quoted_table(table)}').collect()]
    return sorted(rows, key=lambda r: json.dumps(r, sort_keys=True, default=str))


def _measured(config):
    return [config.table('silver_canonical', 'silver'), config.table('silver_central', 'silver'),
            config.table('fact_cost_usage', 'gold'), config.table('dm_monthly_billing', 'datamart')]


def _month_states(spark, config, sources):
    rows = spark.sql(
        f"SELECT billing_month, status, authoritative_source FROM "
        f"{quoted_table(config.table('month_status', 'ops'))} "
        f"WHERE environment = '{config.environment}'").collect()
    existing = {r['billing_month']: r for r in rows}
    if len(existing) != len(rows):
        raise ValueError('Duplicate PROD month statuses; inspect before promotion')
    result = []
    for kind, status, origin in (('monthly', 'CLOSED_DATA_LOADED', 'MONTHLY_BILLING'),
                                 ('daily', 'OPEN', 'DAILY')):
        for month in sorted({item['month'] for item in sources[kind]}):
            row = existing.get(month)
            allowed = {'CLOSED', 'CLOSED_DATA_LOADED'} if kind == 'monthly' else {'OPEN'}
            if row and (row['status'] not in allowed or row['authoritative_source'] != origin):
                raise ValueError(f'Unexpected PROD month state; do not overwrite blindly: {month}')
            result.append({'month': month, 'status': status, 'source': origin})
    return result


def _assert_versions(spark, state):
    if rebuild._versions(spark, state['source_versions']) != state['source_versions']:
        raise ValueError('DEV changed after the approved snapshot; stop and diagnose')
    if rebuild._versions(spark, state['expected_prod_versions']) != state['expected_prod_versions']:
        raise ValueError('PROD/OPS changed outside the promotion checkpoint; stop and diagnose')


def _summary(state):
    return {'status': state['status'], 'direction': 'dev -> prod',
            'business_tables': len(state['pairs']), 'copied_tables': len(state['copied']),
            'monthly_files': len(state['sources']['monthly']),
            'active_daily_files': len(state['sources']['daily']),
            'completed': state['completed'],
            'next': 'Keep jobs/dashboard paused; validate all four dashboard profiles after PASS.'}


def _plan(spark, dev, prod, path, dev_checkpoint, pairs):
    dev_path = rebuild._control_path(dev_checkpoint, dev)
    proof = json.loads(dev_path.read_text(encoding='utf-8'))
    if (proof.get('status') != 'PASS' or proof.get('environment') != 'dev'
            or proof.get('completed') != ['reset', 'monthly', 'daily', 'validate']):
        raise ValueError('Complete DEV monthly -> daily -> validate and obtain PASS first')
    months = proof.get('months', [])
    if not months:
        raise ValueError('DEV checkpoint has no approved monthly range')
    # Also verifies scope, manifest, private path and ALL original checkpoint versions.
    rebuild.run_stage(spark, dev, dev_path, stage='plan',
                      start_month=months[0], end_month=months[-1])
    if (proof['monthly_done'] != months
            or set(proof['daily_done']) != {s['uri'] for s in proof['sources']['daily']}):
        raise ValueError('DEV replay manifest is incomplete')
    sources = proof['sources']
    source_names, target_names = ([p[i] for p in pairs] for i in (0, 1))
    rebuild._assert_managed(spark, source_names)
    rebuild._assert_managed(spark, target_names)
    if rebuild._charge_schema_plan(spark, dev):
        raise ValueError('DEV still has the legacy charge schema')
    ops = (prod.table('month_status', 'ops'),
           f'{prod.operations_catalog}.security.business_scope',
           f'{prod.operations_catalog}.security.user_entitlement')
    source_versions = {name: proof['expected_versions'][name] for name in source_names}
    if rebuild._versions(spark, source_names) != source_versions:
        raise ValueError('DEV changed since its PASS checkpoint')
    target_versions = rebuild._versions(spark, (*target_names, *ops))
    dev_baseline = {t: money_snapshot(spark, t) for t in _measured(dev)}
    baseline = {t: money_snapshot(spark, t) for t in _measured(prod)}
    for source, target in zip(_measured(dev), _measured(prod), strict=True):
        if not baseline[target] or not dev_baseline[source]:
            raise ValueError('This maintenance expects existing, non-empty DEV and PROD financial references')
        tolerance = prod.amount_tolerance if '.datamart.' in target else '0'
        rebuild.compare_money(baseline[target], dev_baseline[source], tolerance=tolerance)
        rebuild.compare_money(proof['baseline'][source], dev_baseline[source], tolerance=tolerance)
    for key in ('silver_canonical', 'silver_central'):
        manifest = rebuild.source_manifest(rebuild._lineage(spark, prod.table(key, 'silver')),
                                           prod, months)
        if manifest != sources:
            raise ValueError('PROD has different active sources; copy refused to avoid losing data')
    # Counts/schemas and grants are recorded privately, not emitted in a public report.
    counts, schemas, grants = {}, {}, {}
    for position, (source, target) in enumerate(pairs, 1):
        print(f'Promotion preflight [{position}/30]: {target}', flush=True)
        counts[source] = spark.table(source).count()
        schemas[source] = _schema(spark, source)
        grants[target] = _grants(spark, target)
    state = {'format': FORMAT, 'metastore': rebuild.BELGIUM_METASTORE,
             'pairs': pairs, 'tables': target_names, 'months': months, 'sources': sources,
             'baseline': baseline, 'dev_baseline': dev_baseline,
             'dev_checkpoint': str(dev_path), 'source_versions': source_versions,
             'recovery_versions': target_versions, 'expected_prod_versions': target_versions.copy(),
             'source_counts': counts, 'source_schemas': schemas, 'prod_grants': grants,
             'month_states': _month_states(spark, prod, sources),
             'copied': [], 'clone_metrics': {}, 'completed': [], 'status': 'PLAN_READY'}
    _assert_versions(spark, state)
    rebuild._save(path, state)
    return _summary(state)


def _publish_views(spark, prod):
    refresh_cost_allocation_view(spark, prod)
    # The existing serving scripts explicitly reference PROD, not DEV.
    for file in ('security/04_create_dashboard_serving_view.sql',
                 'security/05_validate_dashboard_serving_view.sql'):
        statements = split_statements(sql_text(file))
        for position, statement in enumerate(statements, 1):
            rows = spark.sql(statement).collect()  # Force SELECT assertions to run.
            print(f'{file} [{position}/{len(statements)}]: {len(rows)} row(s)', flush=True)


def run_stage(spark, dev, prod, state_file, dev_checkpoint, *, stage='plan',
              confirmation='', jobs_paused=False, dashboard_paused=False):
    """PLAN is read-only in Databricks; COPY and VALIDATE require manual confirmation."""
    pairs = _scope(dev, prod)
    if stage not in STAGES:
        raise ValueError('Unknown promotion stage')
    metastore = spark.sql('SELECT current_metastore() AS metastore').first()['metastore']
    if metastore != rebuild.BELGIUM_METASTORE:
        raise ValueError('Promotion is restricted to the Belgian metastore')
    path = _private_path(state_file, prod)
    if not path.exists():
        if stage != 'plan':
            raise ValueError('Run promotion plan first')
        return _plan(spark, dev, prod, path, dev_checkpoint, pairs)
    state = json.loads(path.read_text(encoding='utf-8'))
    if (state.get('format') != FORMAT or state.get('metastore') != metastore
            or state.get('pairs') != [list(p) for p in pairs]
            or state.get('tables') != [p[1] for p in pairs]
            or state.get('dev_checkpoint') != str(Path(dev_checkpoint).resolve())):
        raise ValueError('Promotion checkpoint scope differs')
    expected_source = {p[0] for p in pairs}
    expected_target = {p[1] for p in pairs} | {
        prod.table('month_status', 'ops'), f'{prod.operations_catalog}.security.business_scope',
        f'{prod.operations_catalog}.security.user_entitlement'}
    if (set(state['source_versions']) != expected_source
            or set(state['expected_prod_versions']) != expected_target
            or set(state['source_counts']) != expected_source
            or set(state['source_schemas']) != expected_source
            or set(state['prod_grants']) != {p[1] for p in pairs}
            or not set(state['copied']).issubset({p[1] for p in pairs})
            or len(state['copied']) != len(set(state['copied']))):
        raise ValueError('Promotion checkpoint table inventory differs')
    stored_rows = [dict(billing_month=s['month'], _source_type=kind, _source_file=s['uri'])
                   for key, kind in (('monthly', 'MONTHLY_BILLING'), ('daily', 'DAILY'))
                   for s in state['sources'][key]]
    if rebuild.source_manifest(stored_rows, prod, state['months']) != state['sources']:
        raise ValueError('Promotion checkpoint source manifest differs')
    if state['status'] in {'RUNNING', 'FAILED'}:
        raise ValueError('Previous promotion failed/interrupted; preserve checkpoint, no blind retry')
    _assert_versions(spark, state)
    if stage == 'plan' or stage in state['completed']:
        return _summary(state)
    if stage == 'validate' and 'copy' not in state['completed']:
        raise ValueError('Execute copy before validate')
    if (confirmation != CONFIRMATION or jobs_paused is not True or dashboard_paused is not True):
        raise ValueError('Exact promotion confirmation and paused jobs/dashboard required')
    rebuild._assert_managed(spark, [p[1] for p in pairs])
    state['status'] = 'RUNNING'
    rebuild._save(path, state)
    run_id = None
    try:
        run_id = start_run(spark, prod, f'dev_to_prod_deep_clone_{stage}')
        state[f'{stage}_run_id'] = run_id
        rebuild._save(path, state)
        if stage == 'copy':
            for position, (source, target) in enumerate(pairs, 1):
                version = state['source_versions'][source]
                if type(version) is not int or version < 0:
                    raise ValueError('Invalid DEV Delta version')
                if rebuild._versions(spark, [target])[target] != state['expected_prod_versions'][target]:
                    raise ValueError(f'Target changed before clone: {target}')
                print(f'Deep clone [{position}/30]: {source} -> {target} (version {version})', flush=True)
                metrics = spark.sql(
                    f'CREATE OR REPLACE TABLE {quoted_table(target)} DEEP CLONE '
                    f'{quoted_table(source)} VERSION AS OF {version}').collect()
                if (_schema(spark, target) != state['source_schemas'][source]
                        or spark.table(target).count() != state['source_counts'][source]):
                    raise ValueError(f'Cloned count/schema differs: {target}')
                if _grants(spark, target) != state['prod_grants'][target]:
                    raise ValueError(f'PROD table grants changed: {target}')
                state['expected_prod_versions'][target] = rebuild._versions(spark, [target])[target]
                state['copied'].append(target)
                state['clone_metrics'][target] = [row.asDict() for row in metrics]
                rebuild._save(path, state)
            _assert_versions(spark, state)
        else:
            if len(state['copied']) != 30:
                raise ValueError('All 30 tables must have been copied before validation')
            # Reuse financial, privacy, lineage, tag-bridge and application-label controls.
            # This updates only the PROD display label in business_scope, not entitlements.
            rebuild._validate(spark, prod, state)
            label_table = f'{prod.operations_catalog}.security.business_scope'
            state['expected_prod_versions'][label_table] = rebuild._versions(spark, [label_table])[label_table]
            _assert_versions(spark, state)
            _publish_views(spark, prod)
            for item in state['month_states']:
                set_month_status(spark, prod, item['month'], item['status'], item['source'], run_id)
            month_table = prod.table('month_status', 'ops')
            state['expected_prod_versions'][month_table] = rebuild._versions(spark, [month_table])[month_table]
            _assert_versions(spark, state)
        finish_run(spark, prod, run_id, 'SUCCESS',
                   'Pinned DEV snapshot promoted; ingestion IDs retain DEV provenance. '
                   'Dashboard profile validation remains manual.')
        state['completed'].append(stage)
        state['status'] = 'PASS' if stage == 'validate' else 'STAGE_PASS'
        rebuild._save(path, state)
        return _summary(state)
    except Exception as exc:
        state['status'] = 'FAILED'
        state['failed_stage'] = stage
        rebuild._save(path, state)
        if run_id:
            try:
                # No raw exception text or original business labels in OPS messages.
                finish_run(spark, prod, run_id, 'FAILED',
                           f'Manual deep-clone promotion {stage} failed; preserve private checkpoint.')
            except Exception as audit_error:
                if hasattr(exc, 'add_note'):
                    exc.add_note('Failure audit could not be finalized: ' + type(audit_error).__name__)
        raise
