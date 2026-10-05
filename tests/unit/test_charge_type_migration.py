"""Execute the manual notebook against a small offline Spark/Delta stand-in.

These checks cover control flow and safeguards, not a real Databricks migration.
"""

from copy import deepcopy
from decimal import Decimal
import hashlib
import io
import json
from pathlib import Path
import re
import sys
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src'))

from finops_cloud.config import load_config  # noqa: E402

NOTEBOOK = ROOT / 'platform/common/notebooks/operations/remove_charge_subcategory.ipynb'


class Row(dict):
    def asDict(self):
        return dict(self)

    def __getitem__(self, key):
        if isinstance(key, int):
            return list(self.values())[key]
        return super().__getitem__(key)


class Frame:
    def __init__(self, spark, rows, columns):
        self.spark = spark
        self.rows = [Row(row) for row in deepcopy(rows)]
        self.columns = list(columns)
        self.schema = self.columns  # Offline stand-in for a Spark StructType.

    def collect(self):
        return self.rows

    def first(self):
        return self.rows[0]

    def limit(self, n):
        return Frame(self.spark, self.rows[:n], self.columns)

    def select(self, *names):
        return Frame(self.spark, [{name: row[name] for name in names} for row in self.rows], names)

    def createOrReplaceTempView(self, name):
        self.spark.views[name] = self


class OfflineSpark:
    def __init__(self):
        self.config = load_config('dev', ROOT)
        self.dimension = self.config.table('dim_charge_type', 'gold')
        self.datamart = self.config.table('dm_cost_by_charge_type', 'datamart')
        rows = []
        for category in ('Usage', 'Adjustment'):
            key = hashlib.sha256(f'charge_type||{category}||Unknown||Usage-Based'.encode()).hexdigest()
            rows.append({'charge_type_sk': key, 'charge_category': category,
                         'charge_subcategory': 'Unknown', 'charge_frequency': 'Usage-Based'})
        self.rows = rows
        self.columns = list(rows[0])
        self.fact_keys = [rows[0]['charge_type_sk'], rows[1]['charge_type_sk']]
        self.costs = {'fact_rows': 2, 'billed_cost': Decimal('95.00'),
                      'effective_cost': Decimal('85.00')}
        self.mart_columns = ['billing_month', 'charge_category', 'charge_subcategory',
                             'charge_frequency', 'total_billed_cost']
        self.views, self.writes = {}, []
        self.catalog = self
        self.refresh_fails = False

    def table(self, name):
        if name == self.dimension:
            return Frame(self, self.rows, self.columns)
        if name == self.datamart:
            return Frame(self, [], self.mart_columns)
        raise AssertionError(f'Unexpected table access: {name}')

    def createDataFrame(self, rows, schema):
        return Frame(self, rows, schema)

    def dropTempView(self, name):
        del self.views[name]

    def sql(self, statement):
        if statement.startswith('SELECT count(*) AS fact_rows'):
            keys = {row['charge_type_sk'] for row in self.rows}
            controls = {**self.costs, 'orphan_rows': sum(key not in keys for key in self.fact_keys)}
            return Frame(self, [controls], controls)
        if statement.startswith('DESCRIBE HISTORY '):
            return Frame(self, [{'version': 7}], ['version'])
        if statement.startswith('CREATE OR REPLACE TABLE '):
            match = re.fullmatch(r'CREATE OR REPLACE TABLE (.+) USING DELTA AS SELECT \* FROM (\w+)', statement)
            assert match and match[1] == self.dimension
            snapshot = self.views[match[2]]
            self.rows = deepcopy(snapshot.rows)
            self.columns = list(snapshot.columns)
            self.writes.append(self.dimension)
            return Frame(self, [], [])
        if statement.startswith('ALTER TABLE '):
            assert statement == f'ALTER TABLE {self.dimension} ALTER COLUMN charge_type_sk SET NOT NULL'
            return Frame(self, [], [])
        if statement.startswith('SELECT coalesce(sum(total_billed_cost), 0)'):
            return Frame(self, [{'billed_cost': self.costs['billed_cost']}], ['billed_cost'])
        raise AssertionError(f'Unexpected SQL: {statement}')

    def refresh(self, spark, relative_path, values):
        assert spark is self
        assert relative_path == 'datamarts/table_refresh/06_dm_cost_by_charge_type.sql'
        if self.refresh_fails:
            raise RuntimeError('Offline simulated refresh failure')
        if 'charge_subcategory' in self.mart_columns:
            self.mart_columns.remove('charge_subcategory')
        self.writes.append(self.datamart)


class ChargeTypeMigrationTests(unittest.TestCase):
    def setUp(self):
        self.notebook = json.loads(NOTEBOOK.read_text(encoding='utf-8'))
        self.spark = OfflineSpark()

    def run_migration(self):
        namespace = {'spark': self.spark, 'ENVIRONMENT': 'dev'}
        with patch('finops_cloud.config.load_config', return_value=self.spark.config), \
             patch('finops_cloud.sql.runner.execute_sql_file', side_effect=self.spark.refresh), \
             redirect_stdout(io.StringIO()) as output:
            for cell in self.notebook['cells'][3:]:
                exec(''.join(cell['source']), namespace)
        return output.getvalue()

    def test_default_confirmation_blocks_execution(self):
        with self.assertRaisesRegex(ValueError, 'CONFIRMATION'):
            exec(''.join(self.notebook['cells'][2]['source']), {})

    def test_key_preserving_migration_is_repeatable_and_writes_only_two_targets(self):
        before_keys, before_costs = deepcopy(self.spark.fact_keys), deepcopy(self.spark.costs)
        self.assertIn('PASS: dev', self.run_migration())
        self.assertNotIn('charge_subcategory', self.spark.columns)
        self.assertNotIn('charge_subcategory', self.spark.mart_columns)
        self.assertEqual(self.spark.fact_keys, before_keys)
        self.assertEqual(self.spark.costs, before_costs)
        self.assertEqual(self.spark.writes, [self.spark.dimension, self.spark.datamart])
        self.assertFalse(self.spark.views)
        self.assertIn('PASS: dev', self.run_migration())
        self.assertEqual(self.spark.writes, [self.spark.dimension, self.spark.datamart, self.spark.datamart])

    def test_real_values_bad_keys_duplicates_and_extra_attributes_block_before_any_write(self):
        for failure in ('real_value', 'key', 'duplicate', 'extra'):
            with self.subTest(failure=failure):
                self.spark = OfflineSpark()
                if failure == 'real_value':
                    self.spark.rows[0]['charge_subcategory'] = 'A real classification'
                elif failure == 'key':
                    self.spark.rows[0]['charge_type_sk'] = 'unexpected'
                elif failure == 'duplicate':
                    self.spark.rows.append(deepcopy(self.spark.rows[0]))
                else:
                    self.spark.columns.append('additional_attribute')
                with self.assertRaisesRegex(ValueError, 'STOP'):
                    self.run_migration()
                self.assertEqual(self.spark.writes, [])

    def test_orphan_facts_block_before_any_write(self):
        self.spark.fact_keys.append('orphan')
        with self.assertRaisesRegex(ValueError, 'orphan'):
            self.run_migration()
        self.assertEqual(self.spark.writes, [])

    def test_stale_datamart_sql_blocks_before_any_write(self):
        with patch('finops_cloud.sql.runner.sql_text', return_value='SELECT charge_subcategory FROM old_model'):
            with self.assertRaisesRegex(ValueError, 'old version'):
                self.run_migration()
        self.assertEqual(self.spark.writes, [])

    def test_datamart_refresh_can_be_retried_after_dimension_migration(self):
        self.spark.refresh_fails = True
        with self.assertRaisesRegex(RuntimeError, 'refresh failure'):
            self.run_migration()
        self.assertEqual(self.spark.writes, [self.spark.dimension])
        self.assertFalse(self.spark.views)
        self.spark.refresh_fails = False
        self.assertIn('PASS: dev', self.run_migration())
        self.assertEqual(self.spark.writes, [self.spark.dimension, self.spark.datamart])


if __name__ == '__main__':
    unittest.main()
