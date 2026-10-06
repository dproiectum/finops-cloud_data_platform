"""Retired repair entry points must never modify business data."""
from pathlib import Path
import json
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src'))
from finops_cloud.config import load_config
from finops_cloud.medallion.privacy_repair import (
    quoted_table, source_volume_uri, run, run_targeted,
)


class PrivacyInventoryTests(unittest.TestCase):
    def test_old_apply_is_disabled_before_any_spark_action(self):
        spark = MagicMock()
        for call in (
            lambda: run(spark, load_config('dev'), None, 'YES'),
            lambda: run_targeted(spark, load_config('dev'), None, step='plan'),
            lambda: run_targeted(spark, load_config('dev'), None, step='tags'),
        ):
            with self.assertRaisesRegex(ValueError, 'retired'):
                call()
        self.assertFalse(spark.mock_calls)

    def test_inventory_is_read_only_and_returns_only_counts(self):
        spark = MagicMock()
        with patch('finops_cloud.medallion.privacy_repair.plan_table',
                   return_value={'Tags': 3}):
            result = run(spark, load_config('dev'),
                         SimpleNamespace(POLICY_VERSION='organization-text-v1'))
        self.assertEqual(result['status'], 'DRY_RUN')
        self.assertEqual(len(result['findings']), 30)
        spark.sql.assert_not_called()
        spark.udf.register.assert_not_called()

    def test_source_paths_stay_inside_raw(self):
        config = load_config('dev')
        expected = config.billing_volume_uri('2026-01')
        self.assertEqual(source_volume_uri('gs://dtl_finops/focus/monthly/billing-2026-01.parquet',
                                           config), expected)
        self.assertEqual(source_volume_uri('dbfs:' + expected, config), expected)
        for path in (None, 'gs://other-bucket/a.parquet',
                     'gs://dtl_finops/focus/../secret.parquet'):
            with self.assertRaises(ValueError):
                source_volume_uri(path, config)

    def test_identifiers_are_quoted_and_injection_rejected(self):
        self.assertEqual(quoted_table('finops_dev.gold.dim_tag'),
                         chr(96)+'finops_dev'+chr(96)+'.'+chr(96)+'gold'+chr(96)+'.'+chr(96)+'dim_tag'+chr(96))
        with self.assertRaises(ValueError):
            quoted_table('finops_dev.gold.dim_tag; DROP CATALOG finops_dev')

    def test_old_notebook_is_only_a_retired_redirect(self):
        path = ROOT / 'platform/common/notebooks/operations/repair_dataset_privacy.ipynb'
        nb = json.loads(path.read_text())
        code = '\n'.join(''.join(c['source']) for c in nb['cells'] if c['cell_type'] == 'code')
        compile(code, str(path), 'exec')
        self.assertIn('raise RuntimeError', code)
        self.assertNotIn('run_targeted(', code)
        self.assertNotIn('MAPPING_FILE', code)
        for job in (ROOT / 'platform').rglob('*.yml'):
            self.assertNotIn('repair_dataset_privacy', job.read_text())
            self.assertNotIn('rebuild_clean_environment', job.read_text())


if __name__ == '__main__':
    unittest.main()
