"""Offline collection, freshness, privacy and orchestration regression tests."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch, Mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src'))
sys.path.insert(0, str(ROOT / 'apps/finops_dashboard'))

from finops_cloud.monitoring.platform_costs import (VOLUME, latest_complete_export,
                                                  prepare_payload, exact_decimal, run)
from platform_costs.reader import storage_url, load_snapshot
from platform_costs.snapshot import build_payload, read_payload


NOW = datetime(2026, 10, 8, 18, tzinfo=timezone.utc)
NAME = '20261008T170000Z_' + 'a' * 32


def record(provider='GCP', **changes):
    result = dict(month='2026-09', provider=provider, service='Cloud Run', currency='EUR',
                  cost_before_credits='5.789510', credits='-0.254762', usage_quantity=None,
                  usage_unit='', cost_basis='billing_export', period_status='partial')
    if provider == 'Databricks':
        result.update(service='PREMIUM_ALL_PURPOSE_COMPUTE', currency='USD', credits=None,
                      usage_quantity='10.123456789012345678', usage_unit='DBU', cost_basis='list_estimate')
    return {**result, **changes}


def manifest(**changes):
    return {**dict(schema_version=1, run_id=NAME, extracted_at=NOW.isoformat(),
                   row_count='1', status='COMPLETE'), **changes}


class MemoryFS:
    def __init__(self, entries):
        self.entries = entries
    def ls(self, path):
        if path not in self.entries:
            raise FileNotFoundError(path)
        return self.entries[path]
    def head(self, path, size):
        return self.entries[path][:size]


def export_fs(meta=None):
    base = VOLUME + '/extracts/gcp'
    return MemoryFS({base: [SimpleNamespace(name=NAME + '/', size=0)],
                     base + '/' + NAME: [SimpleNamespace(name='complete-000000000000.json', size=100),
                                         SimpleNamespace(name='data-000000000000.parquet', size=200)],
                     base + '/' + NAME + '/complete-000000000000.json': json.dumps(meta or manifest())})


class CollectionTests(unittest.TestCase):
    def test_complete_export_selected_and_unfinished_newer_export_ignored(self):
        fs = export_fs()
        base = VOLUME + '/extracts/gcp'
        unfinished = '20261008T175000Z_' + 'b' * 32
        fs.entries[base].append(SimpleNamespace(name=unfinished + '/', size=0))
        fs.entries[base + '/' + unfinished] = []
        directory, meta = latest_complete_export(fs, NOW)
        self.assertEqual(directory, base + '/' + NAME)
        self.assertEqual(meta['row_count'], 1)
        _, string_meta = latest_complete_export(export_fs(manifest(schema_version='1')), NOW)
        self.assertEqual(string_meta['row_count'], 1)

    def test_stale_corrupt_or_incomplete_manifest_refused(self):
        for change in ({'extracted_at': (NOW - timedelta(hours=49)).isoformat()},
                       {'run_id': 'wrong'}, {'status': 'FAILED'}, {'row_count': '0'},
                       {'row_count': '1.5'}, {'row_count': True}, {'schema_version': 2}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                latest_complete_export(export_fs(manifest(**change)), NOW)

    def test_mismatched_count_wrong_provider_missing_prices_and_duplicates_refused(self):
        cases = [([record()], [], manifest(row_count=1)),
                 ([record()], [record('Databricks')], manifest(row_count=2)),
                 ([record('Databricks')], [record('Databricks')], manifest(row_count=1)),
                 ([record()], [record('Databricks', cost_before_credits=None)], manifest(row_count=1)),
                 ([record(), record()], [record('Databricks')], manifest(row_count=2)),
                 ([record(period_status='closed')], [record('Databricks')], manifest(row_count=1))]
        for gcp, db, meta in cases:
            with self.subTest(gcp=gcp, db=db), self.assertRaises(ValueError):
                prepare_payload(gcp, db, meta, NOW)

    def test_precision_and_signed_values_unchanged_in_public_contract(self):
        payload = prepare_payload([record()], [record('Databricks')], manifest(row_count=1), NOW)
        as_of, frame = read_payload(payload, remote=True, now=NOW)
        self.assertEqual(as_of, '2026-10-08')
        self.assertEqual(frame[frame.provider == 'GCP'].iloc[0].reported_cost, Decimal('5.534748'))
        self.assertEqual(frame[frame.provider == 'Databricks'].iloc[0].usage_quantity,
                         Decimal('10.123456789012345678'))
        self.assertNotIn('run_id', json.dumps(payload))
        self.assertNotIn('workspace_id', json.dumps(payload))

    def test_exact_delta_decimals_reject_overflow_and_rounding(self):
        self.assertEqual(exact_decimal('1.123456789012345678'), Decimal('1.123456789012345678'))
        self.assertEqual(exact_decimal('1.0000000000000000000'), Decimal('1'))
        self.assertIsNone(exact_decimal(None))
        for value in ('1.1234567890123456789', '1e20', 'NaN', 'Infinity'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                exact_decimal(value)

    def test_remote_rejects_stale_future_extra_fields_and_wrong_approval(self):
        payload = build_payload([record(), record('Databricks')], generated_at=NOW.isoformat(), gcp_extracted_at=NOW.isoformat())
        for change in ({'generated_at': (NOW - timedelta(hours=49)).isoformat()},
                       {'generated_at': (NOW + timedelta(hours=1)).isoformat()},
                       {'workspace_id': 'private'}, {'approved_for_publication': 'true'},
                       {'source_as_of': {'GCP': NOW.isoformat()}}, {'records': []}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                read_payload({**payload, **change}, remote=True, now=NOW)
        with self.assertRaises(ValueError):
            read_payload({'schema_version': 1, 'approved_for_publication': True,
                          'as_of': '2026-10-08', 'records': [record()]}, remote=True, now=NOW)

    def test_remote_only_dedicated_object_and_no_fallback_on_failure(self):
        uri = 'gs://dtl_finops/platform_costs/published/latest.json'
        self.assertIn('platform_costs%2Fpublished%2Flatest.json', storage_url(uri))
        for wrong in ('https://example.com/latest.json', 'gs://dtl_finops/focus/private.json',
                      'gs://dtl_finops/platform_costs/extracts/data.json'):
            with self.assertRaises(ValueError):
                storage_url(wrong)
        with patch.dict('os.environ', {'FINOPS_PLATFORM_COSTS_MODE': 'gcs',
                                      'FINOPS_PLATFORM_COSTS_GCS_URI': uri}), \
             patch('platform_costs.reader.download_payload', side_effect=ValueError('denied')), \
             patch('platform_costs.reader.load_bundled') as offline:
            with self.assertRaises(ValueError):
                load_snapshot()
            offline.assert_not_called()

    def test_confirmation_and_validation_fail_before_any_data_write(self):
        spark, utils = Mock(), Mock()
        with self.assertRaises(ValueError):
            run(spark, utils, dry_run=False, confirmation='')
        spark.conf.set.assert_not_called()
        with patch('finops_cloud.monitoring.platform_costs.latest_complete_export',
                   side_effect=ValueError('no completed data')):
            with self.assertRaises(ValueError):
                run(spark, utils, dry_run=True)
        utils.fs.put.assert_not_called()
        spark.createDataFrame.assert_not_called()

    def test_preview_never_writes_and_publication_replaces_one_dedicated_snapshot(self):
        spark, utils, monthly = Mock(), Mock(), Mock()
        monthly.columns = ['month', 'provider', 'service', 'currency', 'cost_before_credits',
                           'credits', 'usage_quantity', 'usage_unit', 'cost_basis',
                           'period_status', 'collection_run_id', 'collected_at']
        spark.table.return_value.columns = monthly.columns
        for dry_run in (True, False):
            utils.reset_mock()
            monthly.reset_mock()
            with patch('finops_cloud.monitoring.platform_costs.datetime') as clock, \
                 patch('finops_cloud.monitoring.platform_costs.latest_complete_export', return_value=('/valid', manifest(row_count=1))), \
                 patch('finops_cloud.monitoring.platform_costs._collect', side_effect=[[record()], [record('Databricks')]]), \
                 patch('finops_cloud.monitoring.platform_costs._monthly_frame', return_value=monthly), \
                 patch('finops_cloud.monitoring.platform_costs._audit') as audit:
                clock.now.return_value = NOW
                result = run(spark, utils, confirmation='PUBLISH_PLATFORM_COSTS', dry_run=dry_run)
                if dry_run:
                    self.assertEqual(result['status'], 'PREVIEW')
                    utils.fs.put.assert_not_called()
                    monthly.write.mode.assert_not_called()
                    audit.assert_not_called()
                else:
                    self.assertEqual(result['status'], 'PUBLISHED')
                    monthly.write.mode.assert_called_once_with('overwrite')
                    monthly.write.mode.return_value.insertInto.assert_called_once_with('finops_ops.monitoring.platform_cost_monthly')
                    args, kwargs = utils.fs.put.call_args
                    self.assertEqual(args[0], VOLUME + '/published/latest.json')
                    self.assertTrue(kwargs['overwrite'])
                    payload = json.loads(args[1])
                    read_payload(payload, remote=True, now=NOW)
                    self.assertEqual(audit.call_args.args[3], 'PUBLISHED')

    def test_invalid_provider_data_does_not_replace_existing_public_object(self):
        spark, utils = Mock(), Mock()
        with patch('finops_cloud.monitoring.platform_costs.datetime') as clock, \
             patch('finops_cloud.monitoring.platform_costs.latest_complete_export', return_value=('/valid', manifest(row_count=1))), \
             patch('finops_cloud.monitoring.platform_costs._collect', side_effect=[[record()], [record('Databricks', cost_before_credits=None)]]), \
             patch('finops_cloud.monitoring.platform_costs._audit') as audit:
            clock.now.return_value = NOW
            with self.assertRaises(ValueError):
                run(spark, utils, confirmation='PUBLISH_PLATFORM_COSTS', dry_run=False)
            utils.fs.put.assert_not_called()
            spark.createDataFrame.assert_not_called()
            self.assertEqual(audit.call_args.args[3], 'FAILED')

    def test_reader_checks_freshness_again_after_cached_download(self):
        payload = build_payload([record(), record('Databricks')], generated_at=NOW.isoformat(), gcp_extracted_at=NOW.isoformat())
        with patch.dict('os.environ', {'FINOPS_PLATFORM_COSTS_MODE': 'gcs',
                                      'FINOPS_PLATFORM_COSTS_GCS_URI': 'gs://dtl_finops/platform_costs/published/latest.json'}), \
             patch('platform_costs.reader.download_payload', return_value=payload), \
             patch('platform_costs.snapshot.datetime') as clock:
            clock.now.return_value = NOW
            clock.fromisoformat.side_effect = datetime.fromisoformat
            self.assertEqual(len(load_snapshot()[1]), 2)
            clock.now.return_value = NOW + timedelta(hours=49)
            with self.assertRaises(ValueError):
                load_snapshot()

    def test_artifacts_single_source_and_business_pipelines_untouched(self):
        self.assertFalse((ROOT / 'apps/finops_dashboard/project_costs').exists())
        sql = ROOT / 'platform/common/sql/monitoring/platform_costs'
        self.assertEqual(len(list(sql.glob('*.sql'))), 5)
        self.assertNotIn('SET TIME ZONE', (sql / '02_collect_databricks_monthly.sql').read_text())
        export = (sql / '01_export_gcp_to_gcs.sql').read_text()
        self.assertLess(export.index('data-*.parquet'), export.index('complete-*.json'))
        self.assertIn('GENERATE_UUID()', export)
        self.assertIn("EXPORT DATA OPTIONS(uri='%sdata-*.parquet', format='PARQUET', overwrite=true)", export)
        self.assertIn("EXPORT DATA OPTIONS(uri='%scomplete-*.json', format='JSON', overwrite=true)", export)
        self.assertNotIn('overwrite=false', export)
        self.assertIn("CONCAT('gs://dtl_finops/platform_costs/extracts/gcp/', run_id, '/')", export)
        for path in [ROOT / 'platform/classic_compute/jobs/platform_costs_daily.yml',
                     ROOT / 'platform/serverless/jobs/platform_costs_daily.yml']:
            content = path.read_text()
            self.assertIn('pause_status: PAUSED', content)
            self.assertIn('max_concurrent_runs: 1', content)
            self.assertIn('collect_platform_costs', content)
            self.assertNotIn('finops_prod', content)
            self.assertNotIn('sql_task:', content)


if __name__ == '__main__':
    unittest.main()
