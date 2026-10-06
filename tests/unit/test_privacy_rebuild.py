"""Offline safety tests; do not execute Databricks or truncate real tables."""
from contextlib import ExitStack
from dataclasses import replace
from decimal import Decimal
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src'))
from finops_cloud.config import load_config
from finops_cloud.medallion import privacy_rebuild as rebuild


class ScopeTests(unittest.TestCase):
    def setUp(self):
        self.config = load_config('dev')

    def test_only_30_selected_business_tables(self):
        for env in ('dev', 'prod'):
            names = rebuild.validate_scope(load_config(env))
            self.assertEqual(len(names), 30)
            self.assertTrue(all(n.startswith(f'finops_{env}.') for n in names))
            self.assertFalse(any('finops_ops' in n or 'finops_raw' in n for n in names))
        for config in (replace(self.config, catalog='finops_prod'),
                       replace(self.config, environment='test'),
                       replace(self.config, source_volume='/Volumes/other/source')):
            with self.assertRaises(ValueError):
                rebuild.validate_scope(config)

    def rows(self):
        return [dict(billing_month='2026-01', _source_type='MONTHLY_BILLING',
                     _source_file='gs://dtl_finops/focus/monthly/billing-2026-01.parquet'),
                dict(billing_month='2026-07', _source_type='DAILY',
                     _source_file=self.config.daily_volume_uri('2026-07-01'))]

    def test_manifest_uses_only_active_lineage_and_normalizes(self):
        rows = self.rows()
        result = rebuild.source_manifest(rows + rows, self.config, ['2026-01'])
        self.assertEqual(len(result['monthly']), 1)
        self.assertEqual(len(result['daily']), 1)
        self.assertEqual(result['monthly'][0]['uri'], self.config.billing_volume_uri('2026-01'))

    def test_wrong_unknown_or_mixed_lineage_refused(self):
        for changes in ({'_source_type': 'OTHER'}, {'billing_month': '2026-02'},
                        {'_source_file': 'gs://other/secret.parquet'}):
            rows = self.rows()
            rows[0].update(changes)
            with self.assertRaises(ValueError):
                rebuild.source_manifest(rows, self.config, ['2026-01'])
        rows = self.rows()
        rows[1]['billing_month'] = '2026-01'
        with self.assertRaises(ValueError):
            rebuild.source_manifest(rows, self.config, ['2026-01'])

    def test_daily_bad_name_and_path_refused(self):
        for path in (self.config.source_volume + '/daily/2026/07/focus-2026-07-01.parquet',
                     self.config.source_volume + '/daily/2026/08/2026-07-01.parquet'):
            rows = self.rows()
            rows[1]['_source_file'] = path
            with self.assertRaises(ValueError):
                rebuild.source_manifest(rows, self.config, ['2026-01'])

    def test_financial_counts_periods_nulls_and_decimal_precision(self):
        before = [{'period': '2026-01', 'rows': 3, 'BilledCost': '1.234567890123'}]
        rebuild.compare_money(before, [{**before[0], 'BilledCost': Decimal('1.234567890123')}])
        for after in ([], [{**before[0], 'rows': 4}],
                      [{**before[0], 'BilledCost': '1.234567890124'}],
                      [{**before[0], 'BilledCost': None}], before + before):
            with self.assertRaises(ValueError):
                rebuild.compare_money(before, after)
        rebuild.compare_money(before, [{**before[0], 'BilledCost': '1.234567890124'}], tolerance='0.005')

    def test_checkpoint_must_be_private_and_outside_git(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            private = root / 'private'
            private.mkdir()
            with patch.object(rebuild, 'WORKSPACE_USERS', root):
                self.assertEqual(rebuild._control_path(private / 'rebuild_dev.json', self.config),
                                 (private / 'rebuild_dev.json').resolve())
                for path in (private / 'rebuild_prod.json', root / 'missing/rebuild_dev.json'):
                    with self.assertRaises(ValueError):
                        rebuild._control_path(path, self.config)
                (private / '.git').mkdir()
                with self.assertRaises(ValueError):
                    rebuild._control_path(private / 'rebuild_dev.json', self.config)

    def test_managed_delta_check_rejects_external_or_non_delta(self):
        spark = MagicMock()
        for kind, format in (('EXTERNAL', 'delta'), ('MANAGED', 'parquet')):
            spark.sql.return_value.first.return_value.asDict.return_value = {'format': format}
            spark.sql.return_value.collect.return_value = [{'col_name': 'Type', 'data_type': kind}]
            with self.assertRaises(ValueError):
                rebuild._assert_managed(spark, ('finops_dev.bronze.focus_daily_raw',))

    def test_notebook_is_manual_empty_confirmation_without_outputs(self):
        path = ROOT / 'platform/common/notebooks/operations/rebuild_clean_environment.ipynb'
        nb = json.loads(path.read_text())
        code = '\n'.join(''.join(c['source']) for c in nb['cells'] if c['cell_type'] == 'code')
        compile(code, str(path), 'exec')
        self.assertIn("STAGE = 'plan'", code)
        self.assertIn("CONFIRMATION = ''", code)
        self.assertIn('DASHBOARD_PAUSED = False', code)
        self.assertNotIn('dbutils.widgets.get', code)
        self.assertTrue(all(not c.get('outputs') for c in nb['cells']))


class StageTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / 'rebuild_dev.json'
        self.config = load_config('dev')
        self.names = rebuild.validate_scope(self.config)
        self.versions = {n: 5 for n in (*self.names, 'finops_ops.security.business_scope',
                                      'finops_ops.security.user_entitlement')}
        self.spark = MagicMock()
        self.spark.sql.return_value.first.return_value = {'metastore': rebuild.BELGIUM_METASTORE}
        self.spark.table.return_value.limit.return_value.count.return_value = 0
        self.spark.read.parquet.return_value.columns = ['BillingPeriodStart', 'BilledCost']
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.object(rebuild, '_control_path', return_value=self.path))
        self.stack.enter_context(patch.object(rebuild, '_assert_managed'))
        self.stack.enter_context(patch.object(rebuild, '_guard_daily_status'))
        self.stack.enter_context(patch.object(rebuild, 'delta_version',
                                             side_effect=lambda s, t: self.versions[t]))
        self.stack.enter_context(patch.object(rebuild, '_lineage', return_value=[{
            'billing_month': '2026-01', '_source_type': 'MONTHLY_BILLING',
            '_source_file': self.config.billing_volume_uri('2026-01')}]))
        self.money = self.stack.enter_context(patch.object(rebuild, 'money_snapshot',
                                              return_value=[{'period': '2026-01', 'rows': 3,
                                                             'BilledCost': Decimal('5.25')}]))

    def stage(self, stage='plan', **kwargs):
        return rebuild.run_stage(self.spark, self.config, self.path, stage=stage,
                                 start_month='2026-01', end_month='2026-01', **kwargs)

    def approved(self, stage):
        return self.stage(stage, confirmation='REBUILD_DEV_BUSINESS_DATA', jobs_paused=True,
                          dashboard_paused=True, sources_verified=True)

    def state(self):
        return json.loads(self.path.read_text())

    def test_plan_saves_recovery_baseline_without_writes_and_does_not_overwrite(self):
        self.assertEqual(self.stage()['status'], 'PLAN_READY')
        before = self.state()['baseline']
        self.money.return_value = [{'period': '2026-01', 'rows': 100, 'BilledCost': Decimal('9')}]
        self.stage()
        self.assertEqual(self.state()['baseline'], before)
        self.assertEqual(self.money.call_count, 4)
        self.assertTrue(all(call.args[0].startswith('SELECT current_metastore')
                            for call in self.spark.sql.call_args_list))

    def test_wrong_metastore_blocks_before_any_checkpoint(self):
        self.spark.sql.return_value.first.return_value = {'metastore': 'gcp:europe-west3:other'}
        with self.assertRaisesRegex(ValueError, 'Belgian'):
            self.stage()
        self.assertFalse(self.path.exists())

    def test_reset_requires_checkpoint_and_all_explicit_acknowledgements(self):
        with self.assertRaisesRegex(ValueError, 'plan first'):
            self.approved('reset')
        self.stage()
        for kwargs in ({}, {'confirmation': 'REBUILD_PROD_BUSINESS_DATA', 'jobs_paused': True,
                           'dashboard_paused': True, 'sources_verified': True},
                       {'confirmation': 'REBUILD_DEV_BUSINESS_DATA', 'jobs_paused': True,
                        'sources_verified': True}):
            with self.assertRaisesRegex(ValueError, 'Exact confirmation'):
                self.stage('reset', **kwargs)
        self.assertFalse(any('TRUNCATE' in c.args[0] for c in self.spark.sql.call_args_list))

    def test_reset_only_30_tables_and_repeat_is_noop(self):
        self.stage()
        self.approved('reset')
        targets = [c.args[0] for c in self.spark.sql.call_args_list if 'TRUNCATE' in c.args[0]]
        self.assertEqual(len(targets), 30)
        self.assertTrue(all('finops_dev' in t for t in targets))
        self.assertTrue(all('finops_ops' not in t and 'finops_raw' not in t for t in targets))
        self.approved('reset')
        self.assertEqual(len([c for c in self.spark.sql.call_args_list if 'TRUNCATE' in c.args[0]]), 30)

    def test_changed_versions_and_out_of_order_stages_block(self):
        self.stage()
        with self.assertRaisesRegex(ValueError, 'in order'):
            self.approved('monthly')
        self.versions[self.names[0]] += 1
        with self.assertRaisesRegex(ValueError, 'changed outside'):
            self.approved('reset')

    def test_failed_or_interrupted_reset_cannot_blindly_retry(self):
        self.stage()
        def query(text):
            if text.startswith('TRUNCATE'):
                raise RuntimeError('offline simulated failure')
            return MagicMock(first=MagicMock(return_value={'metastore': rebuild.BELGIUM_METASTORE}))
        self.spark.sql.side_effect = query
        with self.assertRaises(RuntimeError):
            self.approved('reset')
        self.assertEqual(self.state()['status'], 'FAILED')
        self.assertIn('recovery_versions', self.state())
        with self.assertRaisesRegex(ValueError, 'failed/interrupted'):
            self.approved('reset')

    def test_monthly_reuses_pipeline_no_archival_then_daily_and_validation(self):
        self.stage()
        self.approved('reset')
        with patch('finops_cloud.pipelines.monthly_close.run') as load:
            self.approved('monthly')
            load.assert_called_once_with('dev', '2026-01',
                                          source_uri=self.config.billing_volume_uri('2026-01'), archive=False)
            self.approved('monthly')
            self.assertEqual(load.call_count, 1)
        with patch('finops_cloud.pipelines.daily_incremental.run') as daily:
            self.approved('daily')  # Empty active daily inventory is a successful explicit stage.
            daily.assert_not_called()
        with patch.object(rebuild, '_validate') as check:
            self.assertEqual(self.approved('validate')['status'], 'PASS')
            check.assert_called_once()

    def test_security_versions_are_not_silently_accepted_after_pipeline(self):
        self.stage()
        self.approved('reset')
        def changed(*args, **kwargs):
            self.versions['finops_ops.security.user_entitlement'] += 1
        with patch('finops_cloud.pipelines.monthly_close.run', side_effect=changed):
            with self.assertRaisesRegex(ValueError, 'Security metadata'):
                self.approved('monthly')
        self.assertEqual(self.state()['status'], 'FAILED')

    def test_environment_checkpoint_mismatch_and_manifest_tamper_block(self):
        self.stage()
        state = self.state()
        state['environment'] = 'prod'
        self.path.write_text(json.dumps(state))
        with self.assertRaisesRegex(ValueError, 'different rebuild scope'):
            self.approved('reset')
        state['environment'] = 'dev'
        state['sources']['monthly'][0]['uri'] = 'gs://another/secret.parquet'
        self.path.write_text(json.dumps(state))
        with self.assertRaises(ValueError):
            self.approved('reset')

    def test_daily_replays_only_saved_active_sources_through_existing_controls(self):
        rows = [{'billing_month': '2026-01', '_source_type': 'MONTHLY_BILLING',
                 '_source_file': self.config.billing_volume_uri('2026-01')},
                {'billing_month': '2026-07', '_source_type': 'DAILY',
                 '_source_file': self.config.daily_volume_uri('2026-07-01')}]
        with patch.object(rebuild, '_lineage', return_value=rows):
            self.stage()
        self.approved('reset')
        with patch('finops_cloud.pipelines.monthly_close.run'):
            self.approved('monthly')
        with (patch('finops_cloud.pipelines.daily_incremental.run') as daily,
              patch('finops_cloud.audit.daily_controls.validate_daily_load') as check):
            self.approved('daily')
            daily.assert_called_once_with('dev', self.config.daily_volume_uri('2026-07-01'))
            check.assert_called_once_with(self.spark, self.config,
                                           self.config.daily_volume_uri('2026-07-01'))
            self.approved('daily')
            self.assertEqual(daily.call_count, 1)

    def test_empty_baseline_is_rejected_before_checkpoint_and_reset(self):
        self.money.return_value = []
        with self.assertRaisesRegex(ValueError, 'before any reset'):
            self.stage()
        self.assertFalse(self.path.exists())

    def test_validation_failure_is_not_reported_as_pass(self):
        self.stage()
        self.approved('reset')
        with patch('finops_cloud.pipelines.monthly_close.run'):
            self.approved('monthly')
        self.approved('daily')
        with patch.object(rebuild, '_validate', side_effect=ValueError('financial mismatch')):
            with self.assertRaisesRegex(ValueError, 'financial mismatch'):
                self.approved('validate')
        self.assertEqual(self.state()['status'], 'FAILED')
        self.assertNotIn('validate', self.state()['completed'])

    def test_display_label_update_does_not_reseed_security(self):
        spark = MagicMock()
        spark.sql.return_value.collect.side_effect = [[{'application_name': 'TEN Data platform'}], []]
        rebuild._business_scope_label(spark, self.config)
        sql = spark.sql.call_args.args[0]
        self.assertIn("environment = 'dev'", sql)
        self.assertIn("application_code = 'APP00013057'", sql)
        self.assertNotIn('user_entitlement', sql)
        self.assertNotIn('INSERT', sql)
        self.assertNotIn('DELETE', sql)
        self.assertIn("application_name = 'Data Platform'", sql)


if __name__ == '__main__':
    unittest.main()
