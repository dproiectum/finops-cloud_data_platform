"""Consumption presentation and live authorization on offline synthetic fixtures."""

from dataclasses import replace
from decimal import Decimal
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

from config import DashboardConfig  # noqa: E402
from consumption import (  # noqa: E402
    azure_consumption_chart, consumption_series, databricks_consumption_enabled,
    measurement_summary,
)
from data_access import DatabricksDataSource  # noqa: E402
from formatting import consumption_table, measurement_number  # noqa: E402
import queries  # noqa: E402
from security import Identity, SecurityError, demo_identity, resolve_access  # noqa: E402
from security.queries import ScopedQueries  # noqa: E402
from test_dashboard_authorization import FixtureSource  # noqa: E402
from test_dashboard_presentation import CallablePage  # noqa: E402


class ConsumptionFixture(FixtureSource):
    def __init__(self):
        super().__init__()
        self.connection.executescript('''
            CREATE TABLE consumption (
              environment TEXT, billing_month TEXT, application_code TEXT,
              service_name TEXT, sku_id TEXT, consumed_unit TEXT, consumed_quantity REAL,
              usage_rows INT, measured_usage_rows INT, missing_measurement_rows INT,
              negative_quantity_rows INT, first_loaded_charge_date TEXT, last_loaded_charge_date TEXT
            );
            INSERT INTO consumption VALUES
              ('prod','2026-01','APP00013057','Compute','SKU1','Hours',80,3,2,1,1,'2026-01-01','2026-01-02'),
              ('prod','2026-02','APP00013057','Compute','SKU1','Hours',-2,1,1,0,1,'2026-02-01','2026-02-01'),
              ('prod','2026-01','APP00013057','Compute','SKU1','GB',4,1,1,0,0,'2026-01-01','2026-01-01'),
              ('prod','2026-01','APP00013057','Storage','SKU2','GB',NULL,1,0,1,0,'2026-01-01','2026-01-01'),
              ('prod','2026-01','BSN0003965','Compute','SKU1','Hours',999,1,1,0,0,'2026-01-01','2026-01-01'),
              ('prod','2026-01',NULL,'Unmapped','SKU3','Hours',7,1,1,0,0,'2026-01-01','2026-01-01'),
              ('dev','2026-01','APP00013057','Compute','SKU1','Hours',10000,1,1,0,0,'2026-01-01','2026-01-01');
            CREATE TABLE dbu_consumption (
              usage_month TEXT, workspace_label TEXT, sku_name TEXT, billing_origin_product TEXT,
              usage_unit TEXT, is_genie_free_usage BOOLEAN, net_dbu REAL, billing_records INT,
              first_available_usage_date TEXT, last_available_usage_date TEXT
            );
            INSERT INTO dbu_consumption VALUES
              ('2026-09','Belgium','CLASSIC','ALL_PURPOSE','DBU',FALSE,6,3,'2026-09-26','2026-09-26'),
              ('2026-09','Belgium','GENIE_FREE_USAGE','GENIE','DBU',TRUE,2,1,'2026-09-26','2026-09-26');
        ''')

    @staticmethod
    def translate(text):
        return FixtureSource.translate(text).replace(
            'finops_prod.datamart.v_consumption_monthly', 'consumption'
        ).replace('finops_ops.monitoring.v_databricks_consumption_monthly', 'dbu_consumption')


class DashboardConsumptionTests(unittest.TestCase):
    def setUp(self):
        st.cache_data.clear()
        st.cache_resource.clear()
        with patch.dict(os.environ, {}, clear=True):
            self.config = DashboardConfig.from_environment()
        self.source = ConsumptionFixture()
        self.addCleanup(self.source.connection.close)

    def tearDown(self):
        st.cache_data.clear()
        st.cache_resource.clear()

    def scoped(self, identity, portfolio=False):
        return ScopedQueries(resolve_access(self.source, self.config, identity, portfolio_demo=portfolio))

    def owner_history(self):
        return self.source.run(self.scoped(demo_identity('demo-app-owner-a'))
                               .consumption_history(self.config, '2026'))

    def test_public_history_preserves_sku_unit_and_environment(self):
        frame = self.source.query(queries.consumption_history(self.config, '2026'))
        hours = frame.loc[frame.sku_id.eq('SKU1') & frame.consumed_unit.eq('Hours')]
        self.assertEqual(hours.consumed_quantity.tolist(), [1079, -2])
        self.assertIn('SUM(consumed_quantity)', queries.consumption_history(self.config, '2026'))
        self.assertNotIn('system.billing', queries.consumption_history(self.config, '2026'))
        for year in ['2026 OR 1=1', "2026'", '26', None]:
            with self.assertRaises(ValueError):
                queries.consumption_history(self.config, year)

    def test_authorization_precedes_quantity_aggregation_and_keeps_units_separate(self):
        scoped = self.scoped(demo_identity('demo-app-owner-a'))
        request = scoped.consumption_history(self.config, '2026')
        self.assertIn('WHERE', request.text)
        self.assertIn('c.application_code IN (', request.text)
        self.assertNotIn('demo-app-owner-a', request.text)
        self.assertEqual(request.parameters['consumption_year'], '2026-%')
        frame = self.source.run(request)
        self.assertEqual(frame.consumed_quantity.dropna().tolist(), [4, 80, -2])
        self.assertNotIn('Unmapped', frame.service_name.tolist())
        self.assertEqual(self.source.run(scoped.consumption_months(self.config))
                         .billing_month.tolist(), ['2026-02', '2026-01'])
        for year in ['2026 OR 1=1', '26', None]:
            with self.assertRaises(SecurityError):
                scoped.consumption_history(self.config, year)

    def test_consumption_rechecks_revocation_and_ambiguous_application_mapping(self):
        scoped = self.scoped(demo_identity('demo-app-owner-a'))
        request = scoped.consumption_history(self.config, '2026')
        self.source.connection.execute("UPDATE entitlement SET is_active=FALSE WHERE principal_id='demo-app-owner-a'")
        self.assertTrue(self.source.run(request).empty)
        self.source.connection.execute("UPDATE entitlement SET is_active=TRUE WHERE principal_id='demo-app-owner-a'")
        self.source.connection.execute("INSERT INTO business_scope VALUES ('prod','APP00013057','CONFLICT','SUB_A',TRUE)")
        self.assertTrue(self.source.run(request).empty)

    def test_portfolio_owner_sandbox_cannot_expand_to_other_app(self):
        scoped = self.scoped(demo_identity('demo-app-owner-a'), portfolio=True)
        request = scoped.consumption_history(self.config, '2026')
        # Even a subsequent live grant cannot extend the fixed public persona.
        self.source.grant('demo-app-owner-a', 'APPLICATION_OWNER', 'APPLICATION', 'BSN0003965')
        frame = self.source.run(request)
        self.assertEqual(frame.consumed_quantity.dropna().tolist(), [4, 80, -2])
        self.assertIn(':portfolio_application', request.text)

    def test_summary_counts_rows_without_summing_incompatible_quantities(self):
        frame = self.owner_history()
        summary = measurement_summary(frame.loc[frame.billing_month.eq('2026-01')])
        self.assertEqual(summary['usage_rows'], 5)
        self.assertEqual(summary['missing_measurement_rows'], 2)
        self.assertEqual(summary['coverage_pct'], 60)
        self.assertNotIn('consumed_quantity', summary)
        self.assertEqual(summary['last_date'], pd.Timestamp('2026-01-02'))

    def test_quantity_formatting_uses_two_decimals_without_changing_source_values(self):
        for value, display in [(None, '—'), (float('nan'), '—'), (0, '0,00'),
                               (Decimal('-1234.5'), '-1\u202f234,50'),
                               (Decimal('0.000000001'), '0,00'),
                               (Decimal('-0.000000001'), '-0,00'),
                               (Decimal('1234.56789'), '1\u202f234,57')]:
            self.assertEqual(measurement_number(value), display)
        frame = self.owner_history()
        original = frame.copy(deep=True)
        table = consumption_table(frame)
        self.assertIn('01/01/2026', table.to_html())
        self.assertIn('—', table.to_html())
        self.assertIn('Consumed Unit', table.data.columns)
        self.assertIn('SKU ID', table.data.columns)
        self.assertNotIn('€', table.to_html())
        pd.testing.assert_frame_equal(frame, original)

    def test_chart_retains_sign_missing_data_and_loaded_months_without_mixing(self):
        frame = self.owner_history()
        series = consumption_series(frame, 'Compute', 'SKU1', 'Hours')
        figure = azure_consumption_chart(series)
        self.assertEqual(list(figure.data[0].x), ['2026-01', '2026-02'])
        self.assertEqual(list(figure.data[0].y), [80, -2])
        self.assertEqual(figure.layout.separators, ',\u202f')
        self.assertEqual(figure.layout.xaxis.type, 'category')
        self.assertEqual(figure.data[0].customdata[1][0], '-2,00')
        self.assertEqual(figure.layout.yaxis.tickformat, ',.2f')
        missing = azure_consumption_chart(consumption_series(frame, 'Storage', 'SKU2', 'GB'))
        self.assertTrue(pd.isna(missing.data[0].y[0]))
        self.assertEqual(missing.data[0].customdata[0][0], '—')
        with self.assertRaises(ValueError):
            azure_consumption_chart(frame)
        with self.assertRaises(ValueError):
            azure_consumption_chart(pd.concat([series, series], ignore_index=True))

    def test_real_dbu_flag_does_not_unlock_public_or_demo_administrators(self):
        demo_admin = self.scoped(demo_identity('demo-finops-admin')).context
        private_admin = replace(demo_admin, identity=Identity('iap', 'verified-admin'))
        for mode in ['public', 'demo', 'portfolio_demo']:
            self.assertFalse(databricks_consumption_enabled(mode, demo_admin, 'true'))
            self.assertFalse(databricks_consumption_enabled(mode, private_admin, 'true'))
        self.assertFalse(databricks_consumption_enabled('iap', private_admin, None))
        self.assertFalse(databricks_consumption_enabled('iap', replace(private_admin, is_admin=False), 'true'))
        self.assertTrue(databricks_consumption_enabled('iap', private_admin, 'true'))
        for identity in [demo_identity('demo-finops-admin'), demo_identity('demo-app-owner-a')]:
            with self.assertRaises(SecurityError):
                self.scoped(identity).databricks_consumption(self.config)

    def test_private_dbu_query_rechecks_live_admin_and_keeps_genie_separate(self):
        self.source.grant('verified-admin', 'FINOPS_ADMIN', 'ALL', '*', provider='iap')
        scoped = self.scoped(Identity('iap', 'verified-admin'))
        request = scoped.databricks_consumption(self.config)
        self.assertIn('EXISTS', request.text)
        frame = self.source.run(request)
        self.assertEqual(frame.net_dbu.tolist(), [6, 2])
        self.assertEqual(frame.is_genie_free_usage.tolist(), [0, 1])
        self.source.connection.execute("UPDATE entitlement SET is_active=FALSE WHERE principal_id='verified-admin'")
        self.assertTrue(self.source.run(request).empty)
        self.source.grant('verified-owner', 'APPLICATION_OWNER', 'APPLICATION', 'APP00013057', provider='iap')
        with self.assertRaises(SecurityError):
            self.scoped(Identity('iap', 'verified-owner')).databricks_consumption(self.config)

    def test_public_consumption_page_renders_without_any_operational_query(self):
        def choose_page(pages, *, position):
            return next(page for page in pages if page.title == 'Consumption & Emission')

        with (
            patch.dict(os.environ, {'FINOPS_AUTH_MODE': 'public',
                                   'FINOPS_ENABLE_DATABRICKS_CONSUMPTION': 'true'}, clear=True),
            patch.object(DatabricksDataSource, 'healthcheck'),
            patch.object(DatabricksDataSource, 'query', side_effect=self.source.query),
            patch.object(st, 'Page', CallablePage),
            patch.object(st, 'navigation', side_effect=choose_page),
        ):
            app = AppTest.from_file(str(APP / 'app.py'), default_timeout=30).run()
            self.assertFalse(app.exception)
            self.assertEqual(app.title[0].value, 'Consumption & Emission')
            self.assertEqual([tab.label for tab in app.tabs],
                             ['Azure', 'Illustrative Carbon'])
            self.assertEqual(next(item.value for item in app.metric if item.label == 'Consumed Quantity'), '-2,00')
            self.assertEqual(len(app.get('plotly_chart')), 1)
            chart = json.loads(app.get('plotly_chart')[0].proto.spec)
            self.assertEqual(chart['layout']['yaxis']['title']['text'], 'Consumed Quantity (Hours)')
            self.assertTrue(any('Not Estimated' in item.value for item in app.info))
            self.assertTrue(any('not measured' in item.value for item in app.warning))
            self.assertFalse(any('monitoring' in sql or 'system.billing' in sql
                                 for sql, _ in self.source.calls))
            app.selectbox(key='consumption_unit').set_value('GB').run()
            self.assertFalse(app.exception)
            self.assertEqual(next(item.value for item in app.metric if item.label == 'Consumed Quantity'), '—')
            self.assertTrue(any('no loaded row' in item.value for item in app.info))

    def test_portfolio_owner_page_renders_only_authorized_consumption(self):
        def choose_page(pages, *, position):
            return next(page for page in pages if page.title == 'Consumption & Emission')

        with (
            patch.dict(os.environ, {'FINOPS_AUTH_MODE': 'portfolio_demo',
                                   'FINOPS_PORTFOLIO_DATA_APPROVED': 'true'}, clear=True),
            patch.object(DatabricksDataSource, 'healthcheck'),
            patch.object(DatabricksDataSource, 'query', side_effect=self.source.query),
            patch.object(st, 'Page', CallablePage),
            patch.object(st, 'navigation', side_effect=choose_page),
        ):
            app = AppTest.from_file(str(APP / 'app.py'), default_timeout=30).run()
            app.selectbox(key='portfolio_profile').set_value('demo-app-owner-a').run()
            self.assertFalse(app.exception)
            detail = app.dataframe[0].value
            self.assertNotIn('Unmapped', detail['Service Name'].tolist())
            self.assertNotIn(999, detail['Consumed Quantity'].tolist())
            self.assertFalse(any('monitoring' in sql for sql, _ in self.source.calls))

    def test_azure_emissions_use_authorized_rows_and_update_both_tabs(self):
        self.source.connection.executescript('''
            INSERT INTO consumption VALUES
              ('prod','2026-02','APP00013057','Virtual Machines','VM1','Hours',1000,10,10,0,0,'2026-02-01','2026-02-02'),
              ('prod','2026-02','BSN0003965','Virtual Machines','VM1','Hours',9000,10,10,0,0,'2026-02-01','2026-02-02');
        ''')

        def choose_page(pages, *, position):
            return next(page for page in pages if page.title == 'Consumption & Emission')

        with (
            patch.dict(os.environ, {'FINOPS_AUTH_MODE': 'portfolio_demo',
                                   'FINOPS_PORTFOLIO_DATA_APPROVED': 'true'}, clear=True),
            patch.object(DatabricksDataSource, 'healthcheck'),
            patch.object(DatabricksDataSource, 'query', side_effect=self.source.query),
            patch.object(st, 'Page', CallablePage),
            patch.object(st, 'navigation', side_effect=choose_page),
        ):
            app = AppTest.from_file(str(APP / 'app.py'), default_timeout=30).run()
            app.selectbox(key='portfolio_profile').set_value('demo-app-owner-a').run()
            self.assertFalse(app.exception)
            self.assertEqual(len(app.number_input), 2)
            self.assertEqual(len(app.tabs[1].number_input), 2)
            self.assertFalse(app.tabs[0].number_input)
            self.assertNotIn('Carbon Scenario Assumptions', [item.label for item in app.expander])
            detail = app.dataframe[0].value
            vm = detail.loc[detail['Service Name'].eq('Virtual Machines')].iloc[0]
            self.assertEqual(vm['Consumed Quantity'], 1000)
            self.assertAlmostEqual(vm['Illustrative Emissions (kgCO₂e)'], 7.56)
            self.assertTrue(detail.loc[detail['Service Name'].eq('Compute'),
                                       'Illustrative Emissions (kgCO₂e)'].isna().all())
            app.number_input(key='carbon_power_watts').set_value(100).run()
            self.assertFalse(app.exception)
            detail = app.dataframe[0].value
            vm = detail.loc[detail['Service Name'].eq('Virtual Machines')].iloc[0]
            self.assertAlmostEqual(vm['Illustrative Emissions (kgCO₂e)'], 15.12)
            metric = next(item.value for item in app.metric
                          if item.label == 'Illustrative Emissions (kgCO₂e)')
            self.assertEqual(metric, '15,12')
            service_chart = next(json.loads(chart.proto.spec) for chart in app.get('plotly_chart')
                                 if json.loads(chart.proto.spec)['layout']['title']['text']
                                 == 'Illustrative Emissions by Service')
            self.assertEqual(service_chart['data'][0]['customdata'][0][0], '15,12')
            self.assertFalse(any('monitoring' in sql or 'system.billing' in sql
                                 for sql, _ in self.source.calls))

    def test_consumption_has_no_dbu_tab_or_query_even_for_private_administrator(self):
        self.source.grant('verified-admin', 'FINOPS_ADMIN', 'ALL', '*', provider='iap')

        def choose_page(pages, *, position):
            return next(page for page in pages if page.title == 'Consumption & Emission')

        with (
            patch.dict(os.environ, {'FINOPS_AUTH_MODE': 'iap', 'FINOPS_IAP_AUDIENCE': 'test-audience',
                                   'FINOPS_ENABLE_DATABRICKS_CONSUMPTION': 'true'}, clear=True),
            patch('security.iap_identity', return_value=Identity('iap', 'verified-admin')),
            patch.object(DatabricksDataSource, 'healthcheck'),
            patch.object(DatabricksDataSource, 'query', side_effect=self.source.query),
            patch.object(st, 'Page', CallablePage),
            patch.object(st, 'navigation', side_effect=choose_page),
        ):
            app = AppTest.from_file(str(APP / 'app.py'), default_timeout=30).run()
            self.assertFalse(app.exception)
            self.assertEqual([tab.label for tab in app.tabs], ['Azure', 'Illustrative Carbon'])
            self.assertFalse([metric for metric in app.metric if 'DBU' in metric.label])
            self.assertNotIn('dbu_usage_month', [widget.key for widget in app.selectbox])
            self.assertEqual(app.selectbox(key='billing_month').value, '2026-02')
            self.assertEqual(len(app.get('plotly_chart')), 1)
            calls = [(sql, bindings) for sql, bindings in self.source.calls if 'monitoring' in sql]
            self.assertFalse(calls)

    def test_unavailable_consumption_view_stops_without_global_fallback(self):
        def unavailable(sql, parameters=None):
            if 'v_consumption_monthly' in sql:
                raise PermissionError('Offline denied-view fixture')
            return self.source.query(sql, parameters)

        with (
            patch.dict(os.environ, {'FINOPS_AUTH_MODE': 'public'}, clear=True),
            patch.object(DatabricksDataSource, 'healthcheck'),
            patch.object(DatabricksDataSource, 'query', side_effect=unavailable),
            patch.object(st, 'Page', CallablePage),
            patch.object(st, 'navigation', side_effect=lambda pages, position: next(
                page for page in pages if page.title == 'Consumption & Emission')),
        ):
            app = AppTest.from_file(str(APP / 'app.py'), default_timeout=30).run()
            self.assertFalse(app.exception)
            self.assertTrue(app.error)
            self.assertEqual(len(app.metric), 0)
            self.assertFalse(self.source.calls)


if __name__ == '__main__':
    unittest.main()
