"""Offline guards for the manual checks; not evidence of live warehouse access."""

from pathlib import Path
import re
import sqlite3
import sys
import unittest


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src'))
from finops_cloud.sql.runner import split_statements  # noqa: E402

SQL = ROOT / 'platform/common/sql/consumption'


class ConsumptionPreflightTests(unittest.TestCase):
    def test_checks_are_read_only_and_split_without_templates(self):
        for name, count in [('00_check_azure_consumption.sql', 3),
                            ('01_check_databricks_consumption.sql', 2)]:
            with self.subTest(file=name):
                text = (SQL / name).read_text()
                statements = split_statements(text)
                self.assertEqual(len(statements), count)
                for statement in statements:
                    bare = re.sub(r'--[^\n]*', '', statement).strip()
                    self.assertRegex(bare, r'^(SELECT|WITH)\b')
                    self.assertNotRegex(bare, r'(?i)\b(CREATE|DROP|DELETE|UPDATE|INSERT|'
                                        r'MERGE|GRANT|REVOKE|ALTER|TRUNCATE|COPY|SET)\b')
                    self.assertNotIn('{', bare)

    def test_azure_uses_loaded_data_and_keeps_sku_units_separate(self):
        text = (SQL / '00_check_azure_consumption.sql').read_text()
        self.assertIn('finops_prod.gold.v_cost_allocation', text)
        self.assertIn('ConsumedQuantity', text)
        self.assertIn('ConsumedUnit', text)
        self.assertNotIn('read_files', text)
        sample = split_statements(text)[2]
        self.assertIn("source.ChargeCategory = 'Usage'", sample)
        self.assertIn('source.ConsumedQuantity IS NOT NULL', sample)
        self.assertIn('source.ServiceName, source.SkuId,', sample)
        self.assertIn('trim(source.ConsumedUnit)', sample)
        self.assertIn('sum(source.ConsumedQuantity)', sample)
        self.assertNotIn('abs(', sample.lower())

    def test_dbu_check_limits_workspaces_and_keeps_signed_corrections(self):
        statements = split_statements((SQL / '01_check_databricks_consumption.sql').read_text())
        for statement in statements:
            bare = re.sub(r'--[^\n]*', '', statement)
            self.assertIn("('8259550392658865', '8259550830613689')", bare)
            self.assertIn("usage_unit = 'DBU'", bare)
            self.assertIn("cloud = 'GCP'", bare)
            self.assertIn("usage_date >= DATE '2026-09-01'", bare)
            self.assertNotRegex(bare, r"record_type\s*=\s*'ORIGINAL'")
        monthly = statements[1]
        self.assertIn('sum(usage_quantity) AS net_dbu', monthly)
        self.assertNotIn('sum(abs(', monthly.lower())

    def test_sample_preserves_negative_usage_and_does_not_mix_units(self):
        # Execute the actual last SQL statement on a tiny offline SQLite fixture.
        # Only schema qualification and the standard trim/nullif functions are used.
        statement = split_statements((SQL / '00_check_azure_consumption.sql').read_text())[2]
        statement = statement.replace('finops_prod.gold.v_cost_allocation', 'source_rows')
        with sqlite3.connect(':memory:') as db:
            db.execute('CREATE TABLE source_rows (billing_month TEXT, ServiceName TEXT, '
                       'SkuId TEXT, ConsumedUnit TEXT, ConsumedQuantity REAL, ChargeCategory TEXT)')
            db.executemany('INSERT INTO source_rows VALUES (?,?,?,?,?,?)', [
                ('2026-09', 'Compute', 'SKU1', 'Hours', 10, 'Usage'),
                ('2026-09', 'Compute', 'SKU1', 'Hours', -2, 'Usage'),
                ('2026-09', 'Compute', 'SKU1', 'GB', 3, 'Usage'),
                ('2026-09', 'Compute', 'SKU2', 'Hours', 4, 'Usage'),
                ('2026-09', 'Compute', 'SKU1', 'Hours', 999, 'Purchase'),
                ('2026-09', 'Compute', 'SKU1', 'Hours', None, 'Usage'),
                ('2026-09', 'Compute', 'SKU1', None, 999, 'Usage'),
                ('2026-09', 'Compute', 'SKU1', ' Unknown ', 999, 'Usage'),
                ('2026-08', 'Compute', 'SKU1', 'Hours', 999, 'Usage'),
            ])
            self.assertEqual(db.execute(statement).fetchall(), [
                ('2026-09', 'Compute', 'SKU1', 'GB', 3, 1),
                ('2026-09', 'Compute', 'SKU1', 'Hours', 8, 2),
                ('2026-09', 'Compute', 'SKU2', 'Hours', 4, 1),
            ])


if __name__ == '__main__':
    unittest.main()
