"""Offline scenario maths, interpretation and existing live authorization boundaries."""

import json
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

import pandas as pd
import streamlit as st
from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / 'apps/finops_dashboard'
sys.path.insert(0, str(ROOT / 'tests/unit'))
sys.path.insert(0, str(APP))

from carbon import Scenario, estimate_scenario, load_grid_references, monthly_scenarios
from carbon.scenario import MODELLED
from carbon.view import monthly_chart, comparison_chart
from config import DashboardConfig
from formatting import consumption_table
from security import demo_identity, resolve_access
from security.queries import ScopedQueries
from test_dashboard_consumption import ConsumptionFixture


def usage(**changes):
    row = dict(billing_month='2026-06', service_name='Virtual Machines', sku_id='VM1',
               consumed_unit='Hours', consumed_quantity=1000.0, usage_rows=10,
               measured_usage_rows=10, missing_measurement_rows=0, negative_quantity_rows=0,
               first_loaded_charge_date='2026-06-01', last_loaded_charge_date='2026-06-30')
    return {**row, **changes}


class CarbonScenarioTests(unittest.TestCase):
    def test_formula_units_and_same_energy_comparison(self):
        result = estimate_scenario(pd.DataFrame([usage()]), Scenario())
        row = result.iloc[0]
        self.assertEqual(row.scenario_status, MODELLED)
        self.assertAlmostEqual(row.scenario_energy_kwh, 60)
        self.assertAlmostEqual(row.scenario_kgco2e, 7.56)
        self.assertAlmostEqual(row.comparison_kgco2e, 16.56)
        self.assertEqual(row.modelled_usage_rows, 10)
        changed = estimate_scenario(pd.DataFrame([usage()]), Scenario(100, 1.2, 'europe-west9'))
        self.assertAlmostEqual(changed.iloc[0].scenario_energy_kwh, 120)
        self.assertAlmostEqual(changed.iloc[0].scenario_kgco2e, 1.92)

    def test_references_have_verified_year_units_and_source(self):
        references = load_grid_references()
        self.assertEqual(references['reference_year'], 2025)
        self.assertEqual(references['unit'], 'gCO2e/kWh')
        self.assertEqual(references['source_url'], 'https://cloud.google.com/sustainability/region-carbon')
        self.assertEqual({r['region']: r['grid_gco2e_per_kwh'] for r in references['references']},
                         {'europe-west1': 126, 'europe-west3': 276, 'europe-west9': 16})
        self.assertNotIn('power_watts', references)
        self.assertNotIn('pue', references)

    def test_parameter_validation_rejects_invalid_assumptions(self):
        for power in [0, -1, True, '50', float('inf'), float('nan')]:
            with self.subTest(power=power), self.assertRaises(ValueError):
                Scenario(power_watts=power)
        for pue in [0.9, -1, True, '1.2', float('inf'), float('nan')]:
            with self.subTest(pue=pue), self.assertRaises(ValueError):
                Scenario(pue=pue)
        with self.assertRaises(ValueError):
            Scenario(primary_region='unknown')
        with self.assertRaises(ValueError):
            Scenario(comparison_region='unknown')

    def test_only_exact_vm_services_and_hours_are_supported(self):
        rows = [usage(), usage(sku_id='VM2', service_name='Virtual Machine Scale Sets'),
                usage(sku_id='VM3', consumed_unit='GB'),
                usage(sku_id='VM4', consumed_unit='GB Hours'),
                usage(sku_id='VM5', consumed_unit='hours'),
                usage(sku_id='VM6', service_name='Azure App Service')]
        result = estimate_scenario(pd.DataFrame(rows), Scenario())
        self.assertEqual(result.scenario_status.eq(MODELLED).tolist(), [True, True, False, False, False, False])
        self.assertTrue(result.scenario_kgco2e.iloc[2:].isna().all())

    def test_negative_or_incomplete_group_is_excluded_not_clipped(self):
        cases = [
            (dict(consumed_quantity=-1), 'signed correction group'),
            (dict(negative_quantity_rows=1), 'signed correction group'),
            (dict(measured_usage_rows=9, missing_measurement_rows=1), 'incomplete measurements'),
            (dict(consumed_quantity=None), 'incomplete measurements'),
            (dict(consumed_quantity=float('inf')), 'incomplete measurements'),
        ]
        for changes, reason in cases:
            with self.subTest(changes=changes):
                original = pd.DataFrame([usage(**changes)])
                result = estimate_scenario(original, Scenario())
                self.assertIn(reason, result.iloc[0].scenario_status)
                self.assertTrue(pd.isna(result.iloc[0].scenario_kgco2e))
                self.assertEqual(result.iloc[0].modelled_usage_rows, 0)
                pd.testing.assert_frame_equal(result[original.columns], original)

    def test_invalid_counters_and_missing_sku_exclude_whole_group(self):
        for sku in [None, '', '  ', 'Unknown', 'unknown']:
            with self.subTest(sku=sku):
                result = estimate_scenario(pd.DataFrame([usage(sku_id=sku)]), Scenario())
                self.assertIn('missing SKU', result.iloc[0].scenario_status)
        for changes in [dict(usage_rows=0), dict(usage_rows=None), dict(usage_rows=-1),
                        dict(measured_usage_rows=8), dict(negative_quantity_rows=11),
                        dict(usage_rows=10.5, measured_usage_rows=10.5),
                        dict(negative_quantity_rows=float('inf'))]:
            with self.subTest(changes=changes):
                result = estimate_scenario(pd.DataFrame([usage(**changes)]), Scenario())
                self.assertIn('invalid measurement counters', result.iloc[0].scenario_status)

    def test_input_is_unchanged_and_duplicate_groups_rejected(self):
        source = pd.DataFrame([usage()])
        expected = source.copy(deep=True)
        estimate_scenario(source, Scenario())
        pd.testing.assert_frame_equal(source, expected)
        with self.assertRaises(ValueError):
            estimate_scenario(pd.DataFrame([usage(), usage()]), Scenario())

    def test_zero_is_zero_unmodelled_is_missing_months_not_filled(self):
        source = pd.DataFrame([usage(consumed_quantity=0), usage(
            billing_month='2026-08', consumed_unit='GB', first_loaded_charge_date='2026-08-01',
            last_loaded_charge_date='2026-08-02')])
        result = monthly_scenarios(estimate_scenario(source, Scenario()))
        self.assertEqual(result.billing_month.tolist(), ['2026-06', '2026-08'])
        self.assertEqual(result.iloc[0].scenario_kgco2e, 0)
        self.assertTrue(pd.isna(result.iloc[1].scenario_kgco2e))
        self.assertEqual(result.iloc[1].modelled_usage_rows, 0)

    def test_partial_dates_and_calendar_window_not_completeness(self):
        result = monthly_scenarios(estimate_scenario(pd.DataFrame([
            usage(), usage(billing_month='2026-07', first_loaded_charge_date='2026-07-01',
                           last_loaded_charge_date='2026-07-02'),
        ]), Scenario()))
        self.assertIn('completeness not certified', result.iloc[0].period_status)
        self.assertIn('Partial', result.iloc[1].period_status)
        figure = monthly_chart(result, 'Belgium')
        self.assertEqual(list(figure.data[0].marker.pattern.shape), ['', '/'])
        self.assertEqual(figure.layout.xaxis.type, 'category')
        comparison = comparison_chart(result.iloc[0], load_grid_references()['references'][0],
                                      load_grid_references()['references'][1])
        self.assertAlmostEqual(comparison.data[0].y[0], 7.56)
        self.assertAlmostEqual(comparison.data[0].y[1], 16.56)
        self.assertEqual(comparison.data[0].customdata[0][1], comparison.data[0].customdata[1][1])

    def test_carbon_table_is_european_and_retains_missing_values(self):
        frame = pd.DataFrame({'scenario_vm_hours': [1000, None], 'scenario_energy_kwh': [60, None],
                              'scenario_kgco2e': [7.56, None]})
        html = consumption_table(frame).to_html()
        for expected in ['Modelled VM Billing Hours', 'Scenario Energy (kWh)', 'kgCO₂e', '7,56', '1\u202f000', '—']:
            self.assertIn(expected, html)
        self.assertNotIn('€', html)

    def test_live_scope_precedes_scenario_and_revocation_has_no_fallback(self):
        source = ConsumptionFixture()
        self.addCleanup(source.connection.close)
        source.connection.executescript('''
            INSERT INTO consumption VALUES
              ('prod','2026-06','APP00013057','Virtual Machines','VM1','Hours',1000,10,10,0,0,'2026-06-01','2026-06-30'),
              ('prod','2026-06','BSN0003965','Virtual Machines','VM1','Hours',9000,10,10,0,0,'2026-06-01','2026-06-30');
        ''')
        with patch.dict(os.environ, {}, clear=True):
            config = DashboardConfig.from_environment()
        access = resolve_access(source, config, demo_identity('demo-app-owner-a'))
        request = ScopedQueries(access).consumption_history(config, '2026')
        scoped = source.run(request)
        result = monthly_scenarios(estimate_scenario(scoped, Scenario()))
        self.assertAlmostEqual(result.loc[result.billing_month.eq('2026-06')].iloc[0].scenario_kgco2e, 7.56)
        source.connection.execute("UPDATE entitlement SET is_active=FALSE WHERE principal_id='demo-app-owner-a'")
        revoked = source.run(request)
        self.assertTrue(estimate_scenario(revoked, Scenario()).empty)
        self.assertFalse(any('monitoring' in sql or 'system.billing' in sql for sql, _ in source.calls))

    def test_read_only_ui_shows_assumptions_comparison_and_reacts_to_power(self):
        script = '''
import sys
sys.path.insert(0, APP_PATH)
import pandas as pd
from carbon.view import render_carbon_scenario
render_carbon_scenario(pd.DataFrame(ROWS), '2026-06')
'''.replace('APP_PATH', repr(str(APP))).replace('ROWS', repr([usage()]))
        app = AppTest.from_string(script, default_timeout=30).run()
        self.assertFalse(app.exception)
        metrics = {item.label: item.value for item in app.metric}
        self.assertEqual(metrics['Scenario Energy (kWh)'], '60,00')
        self.assertEqual(metrics['Illustrative Emissions (kgCO₂e)'], '7,56')
        self.assertEqual(metrics['Modelled Usage Row Coverage'], '100,00 %')
        self.assertEqual(len(app.get('plotly_chart')), 2)
        self.assertTrue(any('not measured' in item.value for item in app.warning))
        self.assertTrue(any('2025' in item.value and '2026' in item.value for item in app.caption))
        app.number_input(key='carbon_power_watts').set_value(100).run()
        self.assertFalse(app.exception)
        self.assertEqual(next(item.value for item in app.metric
                              if item.label == 'Illustrative Emissions (kgCO₂e)'), '15,12')
        app.selectbox(key='carbon_primary_region').set_value('europe-west9').run()
        self.assertFalse(app.exception)
        self.assertEqual(next(item.value for item in app.metric
                              if item.label == 'Illustrative Emissions (kgCO₂e)'), '1,92')

    def test_empty_authorized_history_does_not_fabricate_metrics(self):
        script = '''
import sys
sys.path.insert(0, APP_PATH)
import pandas as pd
from carbon.view import render_carbon_scenario
render_carbon_scenario(pd.DataFrame(), '2026-06')
'''.replace('APP_PATH', repr(str(APP)))
        app = AppTest.from_string(script, default_timeout=30).run()
        self.assertFalse(app.exception)
        self.assertFalse(app.metric)
        self.assertFalse(app.get('plotly_chart'))
        self.assertTrue(any('Not Estimated' in item.value for item in app.info))


if __name__ == '__main__':
    unittest.main()
