from pathlib import Path
import hashlib
import json
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src'))
from finops_cloud.config import load_config
from finops_cloud.medallion.privacy_repair import protected_column, project_tags, quoted_table, source_volume_uri, run


class PrivacyRepairTests(unittest.TestCase):
    def test_protected_keys_and_costs(self):
        for name in ['ResourceId', 'resource_sk', 'application_code', 'BilledCost', 'EffectiveCost', 'ChargePeriodStart', 'environment']:
            self.assertTrue(protected_column(name))
        for name in ['Tags', 'application_name', 'sku_details']:
            self.assertFalse(protected_column(name))

    def test_tag_rekeying_uses_gold_hash_and_keeps_mapping(self):
        rows = [{'tag_sk': 'old-a', 'tag_key': 'ApplicationName', 'tag_value': 'TEN Data Platform'},
                {'tag_sk': 'old-b', 'tag_key': 'ApplicationName', 'tag_value': 'Data Platform'}]
        tags, mapping = project_tags(rows, lambda v: v.replace('TEN Data Platform', 'Data Platform'))
        key = hashlib.sha256(b'tag||ApplicationName||Data Platform').hexdigest()
        self.assertEqual(tags, [(key, 'ApplicationName', 'Data Platform')])
        self.assertEqual(mapping, [('old-a', key), ('old-b', key)])
        with self.assertRaises(ValueError):
            project_tags([rows[0], rows[0]], lambda v: v)

    def test_source_lineage_is_limited_to_raw_volume(self):
        config = load_config('dev')
        path = source_volume_uri('gs://dtl_finops/focus/monthly/billing-2026-01.parquet', config)
        self.assertEqual(path, '/Volumes/finops_raw/landing/focus/monthly/billing-2026-01.parquet')
        self.assertEqual(source_volume_uri('dbfs:' + path, config), path)
        with self.assertRaises(ValueError):
            source_volume_uri('gs://other-bucket/file.parquet', config)
        with self.assertRaises(ValueError):
            source_volume_uri('gs://dtl_finops/focus/../secret.parquet', config)
        with self.assertRaises(ValueError):
            quoted_table('finops_prod.gold.dim_tag; DROP CATALOG finops_prod')

    def test_notebook_is_manual_checksum_pinned_and_read_only_by_default(self):
        file = ROOT / 'platform/common/notebooks/operations/repair_dataset_privacy.ipynb'
        notebook = json.loads(file.read_text())
        code = '\n'.join(''.join(c['source']) for c in notebook['cells'] if c['cell_type'] == 'code')
        compile(code, str(file), 'exec')
        self.assertIn("CONFIRMATION = ''", code)
        self.assertIn('EXPECTED_POLICY_SHA256', code)
        self.assertNotIn('billing_backfill', code)
        for path in (ROOT / 'platform').rglob('*.yml'):
            self.assertNotIn('repair_dataset_privacy', path.read_text())

    def test_repair_is_not_a_catalog_or_fact_reset(self):
        text = (ROOT / 'src/finops_cloud/medallion/privacy_repair.py').read_text()
        self.assertNotIn('TRUNCATE', text)
        self.assertNotIn('DROP CATALOG', text)
        self.assertNotIn('user_entitlement', text)
        self.assertLess(text.index('assert_source_privacy(raw, path)'), text.index('start_run(spark, config'))
        self.assertLess(text.index('verify_source_copy(spark, uris[uri]'), text.index('start_run(spark, config'))

    def test_dry_run_never_updates_or_registers_an_executor_function(self):
        spark = MagicMock()
        policy = SimpleNamespace(POLICY_VERSION='organization-text-v1')
        with patch('finops_cloud.medallion.privacy_repair.table_exists', return_value=True), \
             patch('finops_cloud.medallion.privacy_repair.plan_table', return_value={'Tags': 1}):
            result = run(spark, load_config('dev'), policy)
        self.assertEqual(result['status'], 'DRY_RUN')
        spark.sql.assert_not_called()
        spark.udf.register.assert_not_called()
        spark.createDataFrame.assert_not_called()
        with self.assertRaises(ValueError):
            run(spark, load_config('dev'), policy, 'YES')


if __name__ == '__main__':
    unittest.main()
