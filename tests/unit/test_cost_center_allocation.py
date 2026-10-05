"""Execute allocation SQL offline; these tests are not live Spark evidence."""

from dataclasses import replace
from decimal import Decimal
from pathlib import Path
import sqlite3
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src'))

from finops_cloud.config import load_config
from finops_cloud.medallion.cost_allocation import apply_cost_allocation, _compare, _totals
from finops_cloud.medallion.gold import (
    COST_ALLOCATION_DDL, cost_allocation_context, refresh_datamarts, DATAMART_SCRIPTS,
)
from finops_cloud.sql.runner import render_sql, split_statements, sql_text


class CostCenterAllocationTests(unittest.TestCase):
    def setUp(self):
        self.config = load_config('dev', ROOT)
        self.connection = sqlite3.connect(':memory:')
        self.addCleanup(self.connection.close)
        self.connection.execute('''CREATE TABLE source (
          source_id INT, billing_month TEXT, Region TEXT, x_CostCenter TEXT,
          BilledCost REAL, EffectiveCost REAL, ListCost REAL, x_CustomerName TEXT,
          ServiceCategory TEXT, ServiceName TEXT, SubAccountId TEXT
        )''')
        inputs = [
            ('West Europe', None, 100), (' North Europe ', 'UNKNOWN', 20),
            ('France Central', '', 30), ('sweden central', ' Unallocated ', 40),
            ('UK South', 'No Cost Center Assigned', 50), ('Global', None, 60),
            ('UAE North', None, 70), ('South India', None, 80),
            ('West Europe', ' CostCenter_APAC ', 90), ('Global', 'CostCenter_NAM', 100),
            (None, None, -5), ('Unknown', None, 0),
            ('South Central US', 'CostCenter_IOC', 110),
            ('West Europe', 'CostCenter_Europe', -10),
            ('UK South', 'Unallocated Costs', 3),
        ]
        # Every row belongs to the SAME subscription: regional allocation must
        # not select a single cost center at subscription grain.
        self.connection.executemany('INSERT INTO source VALUES (?,?,?,?,?,?,?,?,?,?,?)', [
            (index, '2026-06', region, center, cost, cost + 1, cost + 2,
             'Customer', 'Compute', 'Virtual Machines', 'same-subscription')
            for index, (region, center, cost) in enumerate(inputs, 1)
        ])

    def create_view(self, config=None):
        config = config or self.config
        statement = render_sql(COST_ALLOCATION_DDL, {
            **cost_allocation_context(config), 'silver_central': 'source',
            'cost_allocation_view': 'allocated',
        }).replace('CREATE OR REPLACE VIEW', 'CREATE VIEW')
        self.connection.execute(statement)

    def test_policy_preserves_source_and_allocates_at_charge_grain(self):
        self.create_view()
        actual = self.connection.execute('SELECT source_id,cost_center_allocated,allocation_method '
                                         'FROM allocated ORDER BY source_id').fetchall()
        self.assertEqual(actual, [
            (1, 'CostCenter_Europe', 'REGION_EUROPE'),
            (2, 'CostCenter_Europe', 'REGION_EUROPE'),
            (3, 'CostCenter_Europe', 'REGION_EUROPE'),
            (4, 'CostCenter_Europe', 'REGION_EUROPE'),
            (5, 'CostCenter_Europe', 'REGION_EUROPE'),
            (6, 'CostCenter_Corporate', 'GLOBAL_CORPORATE'),
            (7, 'Unallocated Costs', 'UNALLOCATED'),
            (8, 'Unallocated Costs', 'UNALLOCATED'),
            (9, 'CostCenter_APAC', 'SOURCE'), (10, 'CostCenter_NAM', 'SOURCE'),
            (11, 'Unallocated Costs', 'UNALLOCATED'),
            (12, 'Unallocated Costs', 'UNALLOCATED'),
            (13, 'CostCenter_IOC', 'SOURCE'), (14, 'CostCenter_Europe', 'SOURCE'),
            (15, 'CostCenter_Europe', 'REGION_EUROPE'),
        ])
        self.assertEqual(self.connection.execute('SELECT x_CostCenter FROM source WHERE source_id=9').fetchone(),
                         (' CostCenter_APAC ',))
        self.assertEqual(self.connection.execute('SELECT cost_center_source FROM allocated WHERE source_id=9').fetchone(),
                         (' CostCenter_APAC ',))
        totals = 'count(*),sum(BilledCost),sum(EffectiveCost),sum(ListCost)'
        self.assertEqual(self.connection.execute(f'SELECT {totals} FROM source').fetchone(),
                         self.connection.execute(f'SELECT {totals} FROM allocated').fetchone())

    def test_corporate_regions_are_explicit_and_do_not_override_source(self):
        self.create_view(replace(self.config, corporate_regions=(' UAE North ', 'south india')))
        self.assertEqual(self.connection.execute('SELECT cost_center_allocated,allocation_method '
                                                'FROM allocated WHERE source_id IN (7,8)').fetchall(),
                         [('CostCenter_Corporate', 'REGION_CORPORATE')] * 2)
        self.assertEqual(self.connection.execute('SELECT cost_center_allocated FROM allocated '
                                                'WHERE source_id=9').fetchone(), ('CostCenter_APAC',))

    def test_bad_allowlists_are_rejected_before_execution(self):
        for regions in [('West Europe',), ('Global',), ('south india', 'South India'),
                        ('',), (None,), ("UAE North'); DROP TABLE source; --",)]:
            with self.subTest(regions=regions), self.assertRaises(ValueError):
                cost_allocation_context(replace(self.config, corporate_regions=regions))
        self.assertEqual(self.config.corporate_regions, ())
        self.assertEqual(cost_allocation_context(self.config)['corporate_regions_sql'], 'NULL')

    def test_datamart_uses_same_policy_and_preserves_signed_totals(self):
        self.create_view()
        query = render_sql('datamarts/table_refresh/03_dm_cost_by_scope_service_month.sql', {
            'dm_cost_by_scope_service_month': 'mart', 'cost_allocation_view': 'allocated',
        }).split('USING DELTA AS', 1)[1]
        self.connection.execute('CREATE TABLE mart AS ' + query)
        centers = dict(self.connection.execute('SELECT cost_center,total_billed_cost FROM mart'))
        self.assertEqual(centers, {'CostCenter_Europe': 233, 'CostCenter_Corporate': 60,
                                  'Unallocated Costs': 145, 'CostCenter_APAC': 90,
                                  'CostCenter_NAM': 100, 'CostCenter_IOC': 110})
        self.assertEqual(sum(centers.values()), self.connection.execute('SELECT sum(BilledCost) FROM source').fetchone()[0])

    def test_refresh_creates_view_before_all_fourteen_datamarts(self):
        with patch('finops_cloud.medallion.gold.execute_sql_file') as execute:
            refresh_datamarts(object(), self.config)
        paths = [call.args[1] for call in execute.call_args_list]
        self.assertEqual(paths, [COST_ALLOCATION_DDL, *DATAMART_SCRIPTS])
        self.assertEqual(len(split_statements(sql_text(COST_ALLOCATION_DDL))), 1)

    def test_manual_maintenance_requires_confirmation_and_matching_catalog(self):
        with self.assertRaisesRegex(ValueError, 'confirmation'):
            apply_cost_allocation(object(), self.config, '')
        with self.assertRaisesRegex(ValueError, 'matching'):
            apply_cost_allocation(object(), replace(self.config, catalog='finops_prod'),
                                  'APPLY_COST_CENTER_ALLOCATION')

    def test_manual_maintenance_only_publishes_view_and_one_mart(self):
        totals = {'2026-06': {'row_count': 15, 'billed': Decimal(738),
                             'effective': Decimal(753), 'list_cost': Decimal(768)}}
        mart = {'2026-06': {'row_count': 6, 'billed': Decimal(738)}}
        with patch('finops_cloud.medallion.cost_allocation._totals', side_effect=[
            totals, totals, totals, mart, totals, totals,
        ]), patch('finops_cloud.medallion.cost_allocation.refresh_cost_allocation_view') as view, \
                patch('finops_cloud.medallion.cost_allocation.execute_sql_file') as execute:
            result = apply_cost_allocation(object(), self.config, 'APPLY_COST_CENTER_ALLOCATION')
        self.assertEqual(result['status'], 'PASS')
        self.assertEqual(result['source_rows'], 15)
        view.assert_called_once()
        self.assertEqual([call.args[1] for call in execute.call_args_list],
                         ['datamarts/table_refresh/03_dm_cost_by_scope_service_month.sql'])

    def test_mismatched_gold_blocks_manual_publication(self):
        baseline = {'2026-06': {'row_count': 1, 'billed': 10, 'effective': 10, 'list_cost': 10}}
        wrong = {'2026-06': {'row_count': 1, 'billed': 11, 'effective': 10, 'list_cost': 10}}
        with patch('finops_cloud.medallion.cost_allocation._totals', side_effect=[baseline, wrong]), \
             patch('finops_cloud.medallion.cost_allocation.refresh_cost_allocation_view') as view, \
             patch('finops_cloud.medallion.cost_allocation.execute_sql_file') as execute:
            with self.assertRaisesRegex(ValueError, 'billed differs'):
                apply_cost_allocation(object(), self.config, 'APPLY_COST_CENTER_ALLOCATION')
        view.assert_not_called()
        execute.assert_not_called()

    def test_reconciliation_checks_months_rows_and_amounts(self):
        baseline = {'2026-06': {'row_count': 2, 'billed': Decimal('10.00')}}
        for actual in [{}, {'2026-06': {'row_count': 3, 'billed': 10}},
                       {'2026-06': {'row_count': 2, 'billed': Decimal('10.01')}}]:
            with self.subTest(actual=actual), self.assertRaises(ValueError):
                _compare(baseline, actual, Decimal('0.005'))

    def test_manual_empty_data_blocks_before_publication(self):
        with patch('finops_cloud.medallion.cost_allocation._totals', return_value={}), \
             patch('finops_cloud.medallion.cost_allocation.refresh_cost_allocation_view') as view:
            with self.assertRaisesRegex(ValueError, 'requires loaded'):
                apply_cost_allocation(object(), self.config, 'APPLY_COST_CENTER_ALLOCATION')
        view.assert_not_called()

    def test_totals_require_a_month_and_execute_the_aggregate(self):
        from unittest.mock import MagicMock
        spark = MagicMock()
        row = MagicMock()
        row.asDict.return_value = {'billing_month': '2026-06', 'row_count': 2, 'billed': Decimal('10')}
        spark.sql.return_value.collect.return_value = [row]
        self.assertEqual(_totals(spark, 'source', {'billed': 'BilledCost'}),
                         {'2026-06': {'row_count': 2, 'billed': Decimal('10')}})
        self.assertIn('coalesce(SUM(BilledCost), 0)', spark.sql.call_args.args[0])
        row.asDict.return_value = {'billing_month': None, 'row_count': 2, 'billed': Decimal('10')}
        with self.assertRaisesRegex(ValueError, 'no billing_month'):
            _totals(spark, 'source', {'billed': 'BilledCost'})

    def test_datamart_failure_is_retryable_without_fact_writes(self):
        totals = {'2026-06': {'row_count': 1, 'billed': 10, 'effective': 10, 'list_cost': 10}}
        with patch('finops_cloud.medallion.cost_allocation._totals', side_effect=[totals] * 3), \
             patch('finops_cloud.medallion.cost_allocation.refresh_cost_allocation_view') as view, \
             patch('finops_cloud.medallion.cost_allocation.execute_sql_file', side_effect=RuntimeError('refresh failed')):
            with self.assertRaisesRegex(RuntimeError, 'refresh failed'):
                apply_cost_allocation(object(), self.config, 'APPLY_COST_CENTER_ALLOCATION')
        view.assert_called_once()


if __name__ == '__main__':
    unittest.main()
