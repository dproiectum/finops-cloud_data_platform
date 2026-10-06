"""Offline promotion safety tests; never execute real Databricks or GCS writes."""
from contextlib import ExitStack
from dataclasses import replace
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src'))
from finops_cloud.config import load_config
from finops_cloud.medallion import promotion


class Row(dict):
    def asDict(self):
        return dict(self)


class ScopeTests(unittest.TestCase):
    def setUp(self):
        self.dev = load_config('dev')
        self.prod = load_config('prod')

    def test_scope_is_exactly_30_dev_to_prod_pairs_no_raw_or_ops(self):
        pairs = promotion._scope(self.dev, self.prod)
        self.assertEqual(len(pairs), 30)
        self.assertTrue(all(s.startswith('finops_dev.') and t.startswith('finops_prod.') for s, t in pairs))
        self.assertFalse(any('.landing.' in t or '.security.' in t or '.audit.' in t for s, t in pairs))
        for dev, prod in ((self.prod, self.dev), (self.dev, replace(self.prod, catalog='finops_dev')),
                          (self.dev, replace(self.prod, corporate_regions=('east us',)))):
            with self.assertRaises(ValueError):
                promotion._scope(dev, prod)

    def test_private_checkpoint_reuses_outside_git_guard(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            with patch.object(promotion.rebuild, 'WORKSPACE_USERS', root):
                self.assertEqual(promotion._private_path(root / 'promote_dev_to_prod.json', self.prod),
                                 root / 'promote_dev_to_prod.json')
                with self.assertRaises(ValueError):
                    promotion._private_path(root / 'rebuild_prod.json', self.prod)
                (root / '.git').mkdir()
                with self.assertRaises(ValueError):
                    promotion._private_path(root / 'promote_dev_to_prod.json', self.prod)

    def test_month_states_preserve_scope_and_refuse_pending_archive_or_closed_daily(self):
        spark = MagicMock()
        sources = {'monthly': [{'month': '2026-01', 'uri': 'monthly'}],
                   'daily': [{'month': '2026-07', 'uri': 'daily'}]}
        spark.sql.return_value.collect.return_value = [
            Row(billing_month='2026-01', status='CLOSED', authoritative_source='MONTHLY_BILLING'),
            Row(billing_month='2026-07', status='OPEN', authoritative_source='DAILY')]
        result = promotion._month_states(spark, self.prod, sources)
        self.assertEqual(result[0]['status'], 'CLOSED_DATA_LOADED')
        self.assertEqual(result[1]['status'], 'OPEN')
        self.assertIn("environment = 'prod'", spark.sql.call_args.args[0])
        for rows in ([Row(billing_month='2026-01', status='CLOSED_ARCHIVE_PENDING',
                          authoritative_source='MONTHLY_BILLING')],
                     [Row(billing_month='2026-07', status='CLOSED', authoritative_source='MONTHLY_BILLING')],
                     [Row(billing_month='2026-01', status='CLOSED', authoritative_source='MONTHLY_BILLING')] * 2):
            spark.sql.return_value.collect.return_value = rows
            with self.assertRaises(ValueError):
                promotion._month_states(spark, self.prod, sources)

    def test_notebook_has_empty_confirmation_no_outputs_and_no_clone_loop(self):
        path = ROOT / 'platform/common/notebooks/operations/promote_clean_dev_to_prod.ipynb'
        notebook = json.loads(path.read_text())
        code = '\n'.join(''.join(c['source']) for c in notebook['cells'] if c['cell_type'] == 'code')
        compile(code, str(path), 'exec')
        self.assertIn("STAGE = 'plan'", code)
        self.assertIn("CONFIRMATION = ''", code)
        self.assertIn('finops_cloud.medallion.promotion import run_stage', code)
        self.assertNotIn('DEEP CLONE', code)
        self.assertTrue(all(not c.get('outputs') for c in notebook['cells']))

    def test_serving_sql_is_forced_and_never_points_at_dev(self):
        spark = MagicMock()
        with patch.object(promotion, 'refresh_cost_allocation_view') as allocation, \
                redirect_stdout(io.StringIO()):
            promotion._publish_views(spark, self.prod)
            allocation.assert_called_once_with(spark, self.prod)
        statements = [c.args[0] for c in spark.sql.call_args_list]
        self.assertTrue(any('CREATE OR REPLACE VIEW finops_prod.datamart' in s for s in statements))
        self.assertTrue(any('assert_true' in s for s in statements))
        self.assertFalse(any('finops_dev.' in s for s in statements))
        self.assertEqual(spark.sql.return_value.collect.call_count, len(statements))
        spark.sql.return_value.collect.side_effect = ValueError('offline assertion failure')
        with patch.object(promotion, 'refresh_cost_allocation_view'), redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(ValueError, 'assertion failure'):
                promotion._publish_views(spark, self.prod)


class StageTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.path = Path(self.folder.name).resolve() / 'promote_dev_to_prod.json'
        self.dev_path = Path(self.folder.name).resolve() / 'rebuild_dev.json'
        self.dev = load_config('dev')
        self.prod = load_config('prod')
        self.pairs = promotion._scope(self.dev, self.prod)
        self.sources = {'monthly': [{'month': '2026-01', 'uri': self.dev.billing_volume_uri('2026-01')}],
                        'daily': [{'month': '2026-07', 'uri': self.dev.daily_volume_uri('2026-07-01')}]}
        self.money = [{'period': '2026-01', 'rows': 3, 'BilledCost': '12.345678901234'},
                      {'period': '2026-07', 'rows': 1, 'BilledCost': '2.0'}]
        self.proof = dict(status='PASS', environment='dev',
                          completed=['reset', 'monthly', 'daily', 'validate'],
                          months=['2026-01'], sources=self.sources, monthly_done=['2026-01'],
                          daily_done=[self.sources['daily'][0]['uri']],
                          expected_versions={s: 5 for s, t in self.pairs},
                          baseline={t: self.money for t in promotion._measured(self.dev)})
        self.dev_path.write_text(json.dumps(self.proof))
        self.ops = [self.prod.table('month_status', 'ops'), 'finops_ops.security.business_scope',
                    'finops_ops.security.user_entitlement']
        self.versions = {name: 5 for pair in self.pairs for name in pair}
        self.versions.update({t: 3 for t in self.ops})
        self.counts = {t: 3 for pair in self.pairs for t in pair}
        self.spark = MagicMock()
        self.spark.table.side_effect = lambda table: MagicMock(count=lambda: self.counts[table])
        self.spark.sql.side_effect = self.query
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(redirect_stdout(io.StringIO()))
        self.stack.enter_context(patch.object(promotion, '_private_path', return_value=self.path))
        self.stack.enter_context(patch.object(promotion.rebuild, '_control_path', return_value=self.dev_path))
        self.dev_control = self.stack.enter_context(patch.object(promotion.rebuild, 'run_stage'))
        self.stack.enter_context(patch.object(promotion.rebuild, '_assert_managed'))
        self.stack.enter_context(patch.object(promotion.rebuild, '_charge_schema_plan', return_value=[]))
        self.stack.enter_context(patch.object(promotion.rebuild, 'delta_version',
                                             side_effect=lambda s, t: self.versions[t]))
        rows = [dict(billing_month=s['month'], _source_type=kind, _source_file=s['uri'])
                for key, kind in (('monthly', 'MONTHLY_BILLING'), ('daily', 'DAILY'))
                for s in self.sources[key]]
        self.lineage = self.stack.enter_context(patch.object(promotion.rebuild, '_lineage', return_value=rows))
        self.measure = self.stack.enter_context(patch.object(promotion, 'money_snapshot', return_value=self.money))
        self.schema = self.stack.enter_context(patch.object(promotion, '_schema', return_value=[['id', 'string', True]]))
        self.grants = self.stack.enter_context(patch.object(promotion, '_grants', return_value=[{'Principal': 'test', 'ActionType': 'SELECT'}]))
        self.stack.enter_context(patch.object(promotion, '_month_states', return_value=[
            {'month': '2026-01', 'status': 'CLOSED_DATA_LOADED', 'source': 'MONTHLY_BILLING'},
            {'month': '2026-07', 'status': 'OPEN', 'source': 'DAILY'}]))
        self.start = self.stack.enter_context(patch.object(promotion, 'start_run', return_value='offline-promotion-run'))
        self.finish = self.stack.enter_context(patch.object(promotion, 'finish_run'))
        self.validate = self.stack.enter_context(patch.object(promotion.rebuild, '_validate'))
        self.publish = self.stack.enter_context(patch.object(promotion, '_publish_views'))
        self.statuses = self.stack.enter_context(patch.object(promotion, 'set_month_status', side_effect=self.set_status))

    def query(self, statement):
        if statement.startswith('SELECT current_metastore'):
            return MagicMock(first=lambda: {'metastore': promotion.rebuild.BELGIUM_METASTORE})
        if statement.startswith('CREATE OR REPLACE TABLE '):
            parts = statement.split()
            self.assertEqual(parts[5:7], ['DEEP', 'CLONE'])
            self.assertEqual(parts[8:11], ['VERSION', 'AS', 'OF'])
            target, source = parts[4].replace('`', ''), parts[7].replace('`', '')
            self.versions[target] += 1
            self.counts[target] = self.counts[source]
            return MagicMock(collect=lambda: [Row(num_copied_files=2, copied_files_size=1024)])
        raise AssertionError('Unexpected SQL: ' + statement)

    def set_status(self, *args):
        self.versions[self.ops[0]] += 1

    def stage(self, name='plan', **kwargs):
        return promotion.run_stage(self.spark, self.dev, self.prod, self.path, self.dev_path,
                                   stage=name, **kwargs)

    def approved(self, name):
        return self.stage(name, confirmation=promotion.CONFIRMATION,
                          jobs_paused=True, dashboard_paused=True)

    def state(self):
        return json.loads(self.path.read_text())

    def test_plan_records_prod_recovery_and_dev_snapshot_without_mutating_tables(self):
        self.assertEqual(self.stage()['status'], 'PLAN_READY')
        state = self.state()
        self.assertEqual(len(state['source_versions']), 30)
        self.assertEqual(len(state['recovery_versions']), 33)
        self.assertEqual(state['baseline'], {t: self.money for t in promotion._measured(self.prod)})
        self.assertTrue(all(c.args[0].startswith('SELECT current_metastore') for c in self.spark.sql.call_args_list))
        self.start.assert_not_called()
        self.assertEqual(self.stage()['status'], 'PLAN_READY')
        self.assertEqual(self.measure.call_count, 8)  # Existing plan never recaptures baseline.

    def test_dev_must_be_fully_validated_and_have_complete_replay(self):
        for changes in ({'status': 'STAGE_PASS'}, {'monthly_done': []}, {'daily_done': []}):
            self.dev_path.write_text(json.dumps({**self.proof, **changes}))
            with self.assertRaises(ValueError):
                self.stage()
            self.assertFalse(self.path.exists())

    def test_prod_finances_or_active_sources_must_match_dev(self):
        self.measure.side_effect = lambda s, t: self.money if t.startswith('finops_dev') else [
            {**r, 'BilledCost': '999'} for r in self.money]
        with self.assertRaisesRegex(ValueError, 'Financial amount changed'):
            self.stage()
        self.measure.side_effect = None
        self.lineage.return_value = [dict(billing_month='2026-01', _source_type='MONTHLY_BILLING',
                                         _source_file=self.dev.billing_volume_uri('2026-01'))]
        with self.assertRaisesRegex(ValueError, 'different active sources'):
            self.stage()
        self.assertFalse(self.path.exists())

    def test_wrong_metastore_empty_prod_or_copy_without_plan_blocks(self):
        with self.assertRaisesRegex(ValueError, 'plan first'):
            self.approved('copy')
        self.measure.side_effect = lambda s, t: [] if t.startswith('finops_prod') else self.money
        with self.assertRaisesRegex(ValueError, 'non-empty'):
            self.stage()
        self.spark.sql.side_effect = lambda sql: MagicMock(first=lambda: {'metastore': 'gcp:europe-west3:other'})
        with self.assertRaisesRegex(ValueError, 'Belgian'):
            self.stage()

    def test_confirmation_and_order_block_before_writes(self):
        self.stage()
        with self.assertRaisesRegex(ValueError, 'copy before validate'):
            self.approved('validate')
        for kwargs in ({}, {'confirmation': promotion.CONFIRMATION, 'jobs_paused': True}):
            with self.assertRaisesRegex(ValueError, 'Exact promotion confirmation'):
                self.stage('copy', **kwargs)
        self.start.assert_not_called()

    def test_copy_uses_30_pinned_deep_clones_no_truncate_or_ops_copy(self):
        self.stage()
        original = self.state()
        self.assertEqual(self.approved('copy')['copied_tables'], 30)
        statements = [c.args[0] for c in self.spark.sql.call_args_list if 'CLONE' in c.args[0]]
        self.assertEqual(len(statements), 30)
        self.assertTrue(all('DEEP CLONE' in s and 'VERSION AS OF 5' in s for s in statements))
        self.assertTrue(all('`finops_prod`' in s and '`finops_dev`' in s and 'finops_ops' not in s for s in statements))
        self.assertFalse(any('TRUNCATE' in c.args[0] or 'DROP' in c.args[0] for c in self.spark.sql.call_args_list))
        self.assertEqual(self.state()['recovery_versions'], original['recovery_versions'])
        self.assertEqual(self.state()['baseline'], original['baseline'])
        self.approved('copy')
        self.assertEqual(len([c for c in self.spark.sql.call_args_list if 'CLONE' in c.args[0]]), 30)

    def test_validate_reuses_controls_views_and_real_prod_month_statuses(self):
        self.stage()
        self.approved('copy')
        def update_label(*args):
            self.versions['finops_ops.security.business_scope'] += 1
        self.validate.side_effect = update_label
        result = self.approved('validate')
        self.assertEqual(result['status'], 'PASS')
        self.validate.assert_called_once()
        self.publish.assert_called_once_with(self.spark, self.prod)
        self.assertEqual(self.statuses.call_count, 2)
        self.assertTrue(all(c.args[1].environment == 'prod' for c in self.statuses.call_args_list))
        self.assertEqual(self.versions['finops_ops.security.user_entitlement'], 3)
        self.assertEqual(self.state()['completed'], ['copy', 'validate'])
        self.assertTrue(all(c.args[2].startswith('dev_to_prod_deep_clone_') for c in self.start.call_args_list))
        self.assertNotIn('monthly_close', str(self.start.call_args_list))

    def test_external_dev_prod_and_security_changes_block_before_copy(self):
        self.stage()
        for table in (self.pairs[0][0], self.pairs[0][1], self.ops[2]):
            self.versions[table] += 1
            with self.assertRaisesRegex(ValueError, 'changed'):
                self.approved('copy')
            self.versions[table] -= 1
        self.start.assert_not_called()

    def test_clone_error_is_retained_no_blind_retry_or_automatic_restore(self):
        self.stage()
        original = self.state()
        query = self.query
        def failure(statement):
            if 'DEEP CLONE' in statement:
                raise RuntimeError('offline simulated clone failure')
            return query(statement)
        self.spark.sql.side_effect = failure
        with self.assertRaisesRegex(RuntimeError, 'clone failure'):
            self.approved('copy')
        self.assertEqual(self.state()['status'], 'FAILED')
        self.assertEqual(self.state()['recovery_versions'], original['recovery_versions'])
        self.assertEqual(self.finish.call_args.args[3], 'FAILED')
        with self.assertRaisesRegex(ValueError, 'no blind retry'):
            self.approved('copy')
        self.assertFalse(any('RESTORE' in c.args[0] for c in self.spark.sql.call_args_list))

    def test_partial_copy_count_or_grant_mismatch_blocks_publication(self):
        self.stage()
        self.grants.return_value = [{'Principal': 'unexpected', 'ActionType': 'SELECT'}]
        with self.assertRaisesRegex(ValueError, 'grants changed'):
            self.approved('copy')
        self.assertEqual(self.state()['status'], 'FAILED')
        self.publish.assert_not_called()

    def test_cloned_row_count_mismatch_blocks_before_marking_table_copied(self):
        self.stage()
        def table(name):
            count = self.counts[name] + (1 if name.startswith('finops_prod') else 0)
            return MagicMock(count=lambda: count)
        self.spark.table.side_effect = table
        with self.assertRaisesRegex(ValueError, 'Cloned count/schema differs'):
            self.approved('copy')
        self.assertEqual(self.state()['copied'], [])
        self.assertEqual(self.state()['status'], 'FAILED')

    def test_dev_changes_between_pass_check_and_snapshot_are_not_approved(self):
        def race(*args, **kwargs):
            self.versions[self.pairs[0][0]] += 1
        self.dev_control.side_effect = race
        with self.assertRaisesRegex(ValueError, 'DEV changed since its PASS'):
            self.stage()
        self.assertFalse(self.path.exists())

    def test_validation_failure_or_entitlement_change_cannot_report_pass(self):
        self.stage()
        self.approved('copy')
        def changed(*args):
            self.versions['finops_ops.security.user_entitlement'] += 1
        self.validate.side_effect = changed
        with self.assertRaisesRegex(ValueError, 'PROD/OPS changed'):
            self.approved('validate')
        self.assertEqual(self.state()['status'], 'FAILED')
        self.publish.assert_not_called()
        self.statuses.assert_not_called()

    def test_checkpoint_scope_and_inventory_tamper_block(self):
        self.stage()
        original = self.state()
        state = self.state()
        state['pairs'][0][1] = 'finops_ops.audit.pipeline_run'
        self.path.write_text(json.dumps(state))
        with self.assertRaisesRegex(ValueError, 'scope differs'):
            self.approved('copy')
        original['source_versions']['finops_ops.security.user_entitlement'] = 3
        self.path.write_text(json.dumps(original))
        with self.assertRaisesRegex(ValueError, 'inventory differs'):
            self.approved('copy')


if __name__ == '__main__':
    unittest.main()
