"""Execute the manual view queries on offline fixtures, not a live warehouse.

SQLite shims cover Databricks functions used here, not Spark Decimal semantics,
Unity Catalog permissions or live system-table availability.
"""

import json
from pathlib import Path
import re
import sqlite3
import sys
import unittest


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src'))
from finops_cloud.sql.runner import split_statements  # noqa: E402

SQL = ROOT / 'platform/common/sql/consumption'


class CountIf:
    def __init__(self):
        self.count = 0

    def step(self, value):
        self.count += int(bool(value))

    def finalize(self):
        return self.count


def assert_true(value, message):
    if not value:
        raise ValueError(message)
    return None


def offline_sql(statement):
    """Adapt identifiers, null-safe equality and DATE literal syntax only."""
    for source, target in [
        ('finops_prod.gold.v_cost_allocation', 'azure_source'),
        ('finops_prod.datamart.v_consumption_monthly', 'azure_view'),
        ('system.billing.usage', 'dbu_source'),
        ('finops_ops.monitoring.v_databricks_consumption_monthly', 'dbu_view'),
    ]:
        statement = statement.replace(source, target)
    return statement.replace('<=>', 'IS').replace("DATE '2026-09-01'", "'2026-09-01'")


def view_query(filename):
    statement = split_statements((SQL / filename).read_text())[-1]
    return offline_sql(statement.split('\nAS\n', 1)[1])


class ConsumptionViewTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(':memory:')
        self.addCleanup(self.db.close)
        self.db.create_aggregate('count_if', 1, CountIf)
        self.db.create_function('from_json', 2, lambda value, schema: value)
        self.db.create_function('element_at', 2,
                                lambda value, key: json.loads(value or '{}').get(key))
        self.db.create_function('to_date', 1, lambda value: value[:10] if value else None)
        self.db.create_function('date_format', 2,
                                lambda value, fmt: value[:7] if value else None)
        self.db.create_function('assert_true', 2, assert_true)

    def azure_fixture(self):
        self.db.execute('CREATE TABLE azure_source (billing_month TEXT, Tags TEXT, '
                        'ServiceName TEXT, SkuId TEXT, ConsumedUnit TEXT, '
                        'ConsumedQuantity REAL, ChargeCategory TEXT, ChargePeriodStart TEXT)')
        rows = [
            ('APP1', 'SKU1', 'Hours', 10, 'Usage'),
            ('APP1', 'SKU1', 'Hours', -2, 'Usage'),
            ('APP1', 'SKU1', 'Hours', None, 'Usage'),
            ('APP1', 'SKU1', 'GB', 3, 'Usage'),
            ('APP2', 'SKU1', 'Hours', 4, 'Usage'),
            (None, 'SKU1', 'Hours', 7, 'Usage'),
            ('APP1', 'SKU2', 'Hours', 0, 'Usage'),
            ('APP1', 'SKU3', 'Hours', None, 'Usage'),
            ('APP1', 'SKU4', None, 999, 'Usage'),
            ('APP1', 'SKU4', ' Unknown ', 999, 'Usage'),
            ('APP1', 'SKU4', '  ', 999, 'Usage'),
            ('APP1', 'SKU1', 'Hours', 999, 'Purchase'),
        ]
        self.db.executemany('INSERT INTO azure_source VALUES (?,?,?,?,?,?,?,?)', [
            ('2026-07', json.dumps({'ApplicationCode-Symphony': app}) if app else None,
             'Compute', sku, unit, quantity, category, '2026-07-01T00:00:00Z')
            for app, sku, unit, quantity, category in rows
        ])
        self.db.execute('CREATE VIEW azure_view AS ' +
                        view_query('02_create_azure_consumption_view.sql'))

    def dbu_fixture(self):
        self.db.execute('CREATE TABLE dbu_source (usage_date TEXT, workspace_id TEXT, '
                        'sku_name TEXT, billing_origin_product TEXT, usage_unit TEXT, '
                        'usage_quantity REAL, cloud TEXT, record_type TEXT)')
        belgium = '8259550830613689'
        frankfurt = '8259550392658865'
        self.db.executemany('INSERT INTO dbu_source VALUES (?,?,?,?,?,?,?,?)', [
            ('2026-09-26', belgium, 'CLASSIC', 'ALL_PURPOSE', 'DBU', 10, 'GCP', 'ORIGINAL'),
            ('2026-09-26', belgium, 'CLASSIC', 'ALL_PURPOSE', 'DBU', -10, 'GCP', 'RETRACTION'),
            ('2026-09-26', belgium, 'CLASSIC', 'ALL_PURPOSE', 'DBU', 6, 'GCP', 'RESTATEMENT'),
            ('2026-09-26', belgium, 'CLASSIC_(PHOTON)', 'ALL_PURPOSE', 'DBU', 2, 'GCP', 'ORIGINAL'),
            ('2026-09-26', belgium, 'GENIE_FREE_USAGE', 'GENIE', 'DBU', 3, 'GCP', 'ORIGINAL'),
            ('2026-09-26', belgium, 'JOBS_SERVERLESS', 'JOBS', 'DBU', 4, 'GCP', 'ORIGINAL'),
            ('2026-09-26', belgium, 'JOBS_SERVERLESS', 'PREDICTIVE_OPTIMIZATION', 'DBU', 5, 'GCP', 'ORIGINAL'),
            ('2026-10-01', frankfurt, 'SQL', None, 'DBU', 7, 'GCP', 'ORIGINAL'),
            ('2026-09-26', 'OTHER', 'SQL', 'SQL', 'DBU', 999, 'GCP', 'ORIGINAL'),
            ('2026-09-26', belgium, 'SQL', 'SQL', 'DBU', 999, 'AZURE', 'ORIGINAL'),
            ('2026-09-26', belgium, 'SQL', 'SQL', 'OTHER_UNIT', 999, 'GCP', 'ORIGINAL'),
            ('2026-08-31', belgium, 'SQL', 'SQL', 'DBU', 999, 'GCP', 'ORIGINAL'),
        ])
        self.db.execute('CREATE VIEW dbu_view AS ' +
                        view_query('03_create_databricks_consumption_view.sql'))

    def test_setup_is_additive_ddl_only(self):
        names = [('02_create_azure_consumption_view.sql', 1),
                 ('03_create_databricks_consumption_view.sql', 2)]
        for name, expected_count in names:
            with self.subTest(file=name):
                statements = split_statements((SQL / name).read_text())
                self.assertEqual(len(statements), expected_count)
                for statement in statements:
                    bare = re.sub(r'--[^\n]*', '', statement).strip()
                    self.assertRegex(bare, r'^CREATE (OR REPLACE VIEW|SCHEMA IF NOT EXISTS)\b')
                    self.assertNotRegex(bare, r'(?i)\b(DROP|INSERT|MERGE|UPDATE|DELETE|'
                                        r'GRANT|REVOKE|TRUNCATE|COPY|LOCATION)\b')
                    self.assertNotIn('v_dashboard_charge_scoped', bare)
                    self.assertNotIn('{', bare)
        azure = (SQL / names[0][0]).read_text()
        self.assertIn('VIEW finops_prod.datamart.v_consumption_monthly', azure)
        dbu = (SQL / names[1][0]).read_text()
        self.assertIn('VIEW finops_ops.monitoring.v_databricks_consumption_monthly', dbu)

    def test_validators_are_read_only(self):
        for name, expected_count in [('04_validate_azure_consumption_view.sql', 3),
                                     ('05_validate_databricks_consumption_view.sql', 2)]:
            statements = split_statements((SQL / name).read_text())
            self.assertEqual(len(statements), expected_count)
            for statement in statements:
                bare = re.sub(r'--[^\n]*', '', statement).strip()
                self.assertRegex(bare, r'^(WITH|SELECT)\b')
                self.assertNotRegex(bare, r'(?i)\b(CREATE|DROP|GRANT|UPDATE|INSERT|MERGE)\b')

    def test_azure_keeps_scope_units_nulls_zero_and_signed_corrections(self):
        self.azure_fixture()
        result = self.db.execute('SELECT application_code, sku_id, consumed_unit, '
                                 'consumed_quantity, usage_rows, measured_usage_rows, '
                                 'missing_measurement_rows, negative_quantity_rows '
                                 'FROM azure_view ORDER BY application_code, sku_id, consumed_unit').fetchall()
        self.assertEqual(result, [
            (None, 'SKU1', 'Hours', 7, 1, 1, 0, 0),
            ('APP1', 'SKU1', 'GB', 3, 1, 1, 0, 0),
            ('APP1', 'SKU1', 'Hours', 8, 3, 2, 1, 1),
            ('APP1', 'SKU2', 'Hours', 0, 1, 1, 0, 0),
            ('APP1', 'SKU3', 'Hours', None, 1, 0, 1, 0),
            ('APP1', 'SKU4', None, None, 3, 0, 3, 0),
            ('APP2', 'SKU1', 'Hours', 4, 1, 1, 0, 0),
        ])

    def test_azure_controls_pass_and_report_measurement_coverage(self):
        self.azure_fixture()
        statements = split_statements((SQL / '04_validate_azure_consumption_view.sql').read_text())
        for statement in statements[:2]:
            self.assertEqual(self.db.execute(offline_sql(statement)).fetchall(), [(None,)])
        summary = self.db.execute(offline_sql(statements[2])).fetchone()
        self.assertEqual(summary[:5], ('2026-07', 11, 6, 5, 1))
        self.assertEqual(summary[-1], 'READY_WITH_MISSING_VALUES')

    def test_azure_controls_reject_empty_source_and_wrong_quantities(self):
        self.azure_fixture()
        statements = split_statements((SQL / '04_validate_azure_consumption_view.sql').read_text())
        self.db.execute('CREATE TABLE saved_azure AS SELECT * FROM azure_view')
        self.db.execute('DROP VIEW azure_view')
        self.db.execute('UPDATE saved_azure SET consumed_quantity = 42 WHERE sku_id = ?'
                        ' AND consumed_unit = ?', ('SKU1', 'Hours'))
        self.db.execute('CREATE VIEW azure_view AS SELECT * FROM saved_azure')
        with self.assertRaises(sqlite3.OperationalError):
            self.db.execute(offline_sql(statements[1])).fetchall()
        self.db.execute('DELETE FROM azure_source')
        with self.assertRaises(sqlite3.OperationalError):
            self.db.execute(offline_sql(statements[0])).fetchall()

    def test_dbu_preserves_corrections_products_free_usage_and_workspace_bounds(self):
        self.dbu_fixture()
        result = self.db.execute('SELECT workspace_label, sku_name, billing_origin_product, '
                                'is_genie_free_usage, net_dbu, billing_records FROM dbu_view '
                                'ORDER BY workspace_label, sku_name, billing_origin_product').fetchall()
        self.assertEqual(result, [
            ('Belgium', 'CLASSIC', 'ALL_PURPOSE', 0, 6, 3),
            ('Belgium', 'CLASSIC_(PHOTON)', 'ALL_PURPOSE', 0, 2, 1),
            ('Belgium', 'GENIE_FREE_USAGE', 'GENIE', 1, 3, 1),
            ('Belgium', 'JOBS_SERVERLESS', 'JOBS', 0, 4, 1),
            ('Belgium', 'JOBS_SERVERLESS', 'PREDICTIVE_OPTIMIZATION', 0, 5, 1),
            ('Frankfurt', 'SQL', None, 0, 7, 1),
        ])

    def test_dbu_controls_pass_and_reject_wrong_or_empty_telemetry(self):
        self.dbu_fixture()
        statement = split_statements((SQL / '05_validate_databricks_consumption_view.sql').read_text())[0]
        self.assertEqual(self.db.execute(offline_sql(statement)).fetchall(), [(None,)])
        self.db.execute('CREATE TABLE saved_dbu AS SELECT * FROM dbu_view')
        self.db.execute('DROP VIEW dbu_view')
        self.db.execute('UPDATE saved_dbu SET net_dbu = 999 WHERE sku_name = ?', ('CLASSIC',))
        self.db.execute('CREATE VIEW dbu_view AS SELECT * FROM saved_dbu')
        with self.assertRaises(sqlite3.OperationalError):
            self.db.execute(offline_sql(statement)).fetchall()
        self.db.execute('DELETE FROM dbu_source')
        with self.assertRaises(sqlite3.OperationalError):
            self.db.execute(offline_sql(statement)).fetchall()


if __name__ == '__main__':
    unittest.main()
