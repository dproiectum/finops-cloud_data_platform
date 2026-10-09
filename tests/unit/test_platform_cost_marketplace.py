"""Marketplace billing reconciliation, versioned rollout and no double counting."""

from copy import deepcopy
from datetime import timedelta
from decimal import Decimal
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / 'apps/finops_dashboard'
sys.path.insert(0, str(ROOT / 'tests/unit'))
from test_platform_cost_daily import row, manifest, payload, NOW
from test_platform_cost_collection import export_fs, NAME as EXPORT_NAME
from platform_costs.model import amount, billing_total, provider_total, validate_records
from platform_costs.snapshot import read_payload
from platform_costs.view import cost_trend
from finops_cloud.monitoring.platform_costs import latest_complete_export, prepare_payload, run
from streamlit.testing.v1 import AppTest


def marketplace_row(**changes):
    return {**row('Databricks', service='Databricks', currency='EUR',
                  cost_before_credits='8', credits='-1', usage_quantity=None,
                  usage_unit='', cost_basis='billing_export'), **changes}


def records():
    # Test-only values: 2 EUR native + 7 EUR Marketplace, not + 999 USD estimate.
    return [row(cost_before_credits='2', credits='0'), marketplace_row(),
            row('Databricks', cost_before_credits='999')]


def marketplace_manifest(**changes):
    return manifest(schema_version=3, billing_scope='finops_and_databricks_marketplace',
                    row_count=2, run_id=EXPORT_NAME, **changes)


class MarketplaceCostsTests(unittest.TestCase):
    def test_billing_total_excludes_usd_estimates_and_rounds_only_for_display(self):
        frame = validate_records(records(), daily=True)
        self.assertEqual(billing_total(frame), Decimal('9'))
        billed = frame[frame.cost_basis == 'billing_export']
        self.assertEqual(provider_total(billed, 'Databricks', 'reported_cost'), Decimal('7'))
        with self.assertRaisesRegex(ValueError, 'Separate'):
            provider_total(frame, 'Databricks', 'reported_cost')
        with self.assertRaisesRegex(ValueError, 'Separate'):
            cost_trend(frame)

    def test_missing_billing_component_or_different_currency_has_no_total(self):
        for rows in ([records()[0], records()[2]],
                     [records()[1], records()[2]],
                     [records()[0], {**records()[1], 'currency': 'USD'}, records()[2]]):
            with self.subTest(rows=rows):
                self.assertIsNone(billing_total(validate_records(rows, daily=True)))
        self.assertEqual(billing_total(validate_records([
            row(cost_before_credits='0', credits='0'),
            {**marketplace_row(), 'cost_before_credits': '0', 'credits': '0'},
        ], daily=True)), Decimal('0'))

    def test_total_preserves_signed_corrections_and_rounds_after_summing(self):
        frame = validate_records([
            row(cost_before_credits='0.005', credits='0'),
            row(day='2026-09-02', cost_before_credits='0.005', credits='0'),
            marketplace_row(cost_before_credits='0.005', credits='0'),
            records()[2],
        ], daily=True)
        self.assertEqual(billing_total(frame), Decimal('0.015'))
        self.assertEqual(amount(billing_total(frame), 'EUR'), '0,02 EUR')
        corrected = validate_records([
            records()[0], marketplace_row(cost_before_credits='8', credits='-20'), records()[2],
        ], daily=True)
        self.assertEqual(billing_total(corrected), Decimal('-10'))

    def test_marketplace_rows_require_known_credits_blank_usage_and_correct_labels(self):
        for changed in ({'credits': None}, {'usage_quantity': '2'}, {'usage_unit': 'DBU'},
                        {'service': 'Compute Engine'}, {'provider': 'GCP'}):
            with self.subTest(changed=changed), self.assertRaises(ValueError):
                validate_records([{**marketplace_row(), **changed}], daily=True)

    def test_v4_reconciles_three_components_and_exposes_no_project_identity(self):
        output = payload(records())
        self.assertEqual(output['schema_version'], 4)
        as_of, frame = read_payload(output, remote=True, now=NOW)
        self.assertTrue(frame.attrs['marketplace_billing'])
        self.assertEqual(len(frame), 3)
        self.assertEqual(billing_total(frame), Decimal('9'))
        self.assertEqual(len(frame.attrs['daily_records']), 3)
        serialized = json.dumps(output)
        for private in ('project_id', 'pr-5193', 'workspace_id', 'billing_account_id', 'run_id'):
            self.assertNotIn(private, serialized)
        for version in (2, 3):
            wrong = deepcopy(output)
            wrong['schema_version'] = version
            if version == 2:
                del wrong['daily_records']
            with self.assertRaises(ValueError):
                read_payload(wrong, remote=True, now=NOW)

    def test_v4_requires_both_billed_providers_and_usd_reference(self):
        old = payload([records()[0], records()[2]])
        with self.assertRaisesRegex(ValueError, 'Marketplace publication'):
            read_payload({**old, 'schema_version': 4}, remote=True, now=NOW)
        for rows in ([records()[0], records()[1]],
                     [records()[0], records()[1], {**records()[2], 'currency': 'EUR'}]):
            with self.subTest(rows=rows), self.assertRaises(ValueError):
                payload(rows)

    def test_marketplace_dates_use_gcp_extraction_not_databricks_extraction(self):
        output = payload(records())
        output['generated_at'] = (NOW + timedelta(days=1)).isoformat()
        output['as_of'] = (NOW + timedelta(days=1)).date().isoformat()
        output['source_as_of']['Databricks'] = output['generated_at']
        # Keep the same month and sums, but move Marketplace usage after the GCP extraction.
        for row_data in output['daily_records']:
            if row_data['provider'] == 'Databricks' and row_data['cost_basis'] == 'billing_export':
                row_data['usage_date'] = '2026-10-09'
                row_data['month'] = '2026-10'
        with self.assertRaisesRegex(ValueError, 'Usage date follows'):
            read_payload(output, now=NOW + timedelta(days=1))

    def test_manifest_scope_and_source_roles_are_enforced(self):
        _, meta = latest_complete_export(export_fs(marketplace_manifest()), NOW)
        self.assertEqual(meta['schema_version'], 3)
        output = prepare_payload(records()[:2], records()[2:], meta, NOW)
        self.assertEqual(output['schema_version'], 4)
        for wrong in ({**meta, 'billing_scope': 'all_projects'},
                      {**meta, 'schema_version': 2}):
            with self.subTest(wrong=wrong), self.assertRaises(ValueError):
                prepare_payload(records()[:2], records()[2:], wrong, NOW)
        with self.assertRaises(ValueError):
            latest_complete_export(export_fs({**marketplace_manifest(), 'billing_scope': 'all_projects'}), NOW)
        with self.assertRaises(ValueError):
            prepare_payload(records()[:2], [marketplace_row()], meta, NOW)
        with self.assertRaises(ValueError):
            prepare_payload(records()[:1], records()[2:], {**meta, 'row_count': 1}, NOW)

    def test_charts_separate_billing_eur_from_usage_usd_and_keep_neutral_hover(self):
        frame = validate_records(records(), daily=True)
        billed = cost_trend(frame, daily=True, cost_basis='billing_export')
        self.assertEqual([trace.yaxis for trace in billed.data], ['y', 'y'])
        self.assertEqual(billed.layout.yaxis.title.text, 'Cost in Euro')
        self.assertFalse(billed.layout.yaxis2.visible)
        self.assertEqual([trace.y[0] for trace in billed.data], [2, 7])
        self.assertIn('Marketplace Net Cost', billed.data[1].name)
        self.assertNotIn('Net DBUs', billed.data[1].hovertemplate)
        self.assertEqual(billed.layout.hoverlabel.bgcolor, '#F8FAFC')
        reference = cost_trend(frame, daily=True, cost_basis='list_estimate')
        self.assertEqual(len(reference.data), 1)
        self.assertEqual(reference.data[0].y[0], 999)
        self.assertEqual(reference.layout.yaxis.title.text, 'Cost in USD')
        self.assertIn('Net DBUs', reference.data[0].hovertemplate)
        self.assertFalse(reference.layout.yaxis2.visible)

    def test_new_dashboard_total_shared_filters_and_empty_period(self):
        as_of, frame = read_payload(payload(records()), now=NOW)
        prefix = f'import sys\nsys.path.insert(0, {str(APP)!r})\n'
        with patch('platform_costs.view.load_snapshot', return_value=(as_of, frame)):
            app = AppTest.from_string(prefix + 'from platform_costs.view import render_platform_costs\nrender_platform_costs()').run()
            self.assertFalse(app.exception)
            self.assertEqual([metric.value for metric in app.metric], ['2,00 EUR', '7,00 EUR', '9,00 EUR', '1,12', '999,00 USD'])
            self.assertEqual(app.metric[2].label, 'Total Platform Cost')
            self.assertEqual(len(app.get('bidi_component')), 2)
            self.assertFalse(app.warning)
            # Billing detail has no DBU estimate or misleading DBU quantity.
            self.assertNotIn('Net DBUs', app.dataframe[0].value.columns)
            self.assertEqual(set(app.dataframe[0].value['Currency']), {'EUR'})
            for mode in ('Daily', 'Monthly', 'Yearly'):
                app.selectbox(key='platform_cost_view').select(mode).run()
                self.assertFalse(app.exception)
                self.assertEqual(app.metric[2].value, '9,00 EUR')
            app.selectbox(key='platform_cost_month').select('10 · October').run()
            self.assertFalse(app.exception)
            self.assertTrue(all(metric.value == '—' for metric in app.metric))
            app.selectbox(key='platform_cost_year').select('2025').run()
            self.assertFalse(app.exception)
            self.assertTrue(all(metric.value == '—' for metric in app.metric))

    def test_legacy_dashboard_warns_without_inventing_marketplace_total(self):
        as_of, frame = read_payload(payload([records()[0], records()[2]]), now=NOW)
        prefix = f'import sys\nsys.path.insert(0, {str(APP)!r})\n'
        with patch('platform_costs.view.load_snapshot', return_value=(as_of, frame)):
            app = AppTest.from_string(prefix + 'from platform_costs.view import render_platform_costs\nrender_platform_costs()').run()
            self.assertFalse(app.exception)
            self.assertIn('Marketplace billing is not included', app.warning[0].value)
            self.assertNotIn('Total Platform Cost', [metric.label for metric in app.metric])

    def test_dashboard_keeps_currency_mismatch_unavailable_without_silent_fx(self):
        output = payload([records()[0], marketplace_row(currency='USD'), records()[2]])
        as_of, frame = read_payload(output, now=NOW)
        prefix = f'import sys\nsys.path.insert(0, {str(APP)!r})\n'
        with patch('platform_costs.view.load_snapshot', return_value=(as_of, frame)):
            app = AppTest.from_string(prefix + 'from platform_costs.view import render_platform_costs\nrender_platform_costs()').run()
            self.assertFalse(app.exception)
            self.assertEqual([metric.value for metric in app.metric[:3]], ['2,00 EUR', '7,00 USD', '—'])
            self.assertTrue(any('different currencies' in message.value for message in app.info))

    def test_sql_allowlist_has_no_all_account_export_and_scope_is_versioned(self):
        sql = (ROOT / 'platform/common/sql/monitoring/platform_costs/01_export_gcp_to_gcs.sql').read_text()
        self.assertIn("project.id = 'global-repeater-355412'", sql)
        self.assertIn("project.id = 'pr-5193ad409e7b591' AND service.description = 'Databricks'", sql)
        self.assertIn("CASE WHEN service.description = 'Databricks' THEN 'Databricks' ELSE 'GCP' END", sql)
        self.assertIn("3 AS schema_version", sql)
        self.assertIn("'finops_and_databricks_marketplace' AS billing_scope", sql)
        self.assertIn('COUNT(DISTINCT provider) = 2', sql)

    def test_legacy_export_cannot_replace_publication_after_marketplace_upgrade(self):
        spark, utils = Mock(), Mock()
        with patch('finops_cloud.monitoring.platform_costs.datetime') as clock, \
             patch('finops_cloud.monitoring.platform_costs.latest_complete_export', return_value=('/valid', manifest(row_count=1))), \
             patch('finops_cloud.monitoring.platform_costs._collect', side_effect=[[records()[0]], [records()[2]]]), \
             patch('finops_cloud.monitoring.platform_costs._audit'):
            clock.now.return_value = NOW
            with self.assertRaisesRegex(ValueError, 'update the BigQuery scheduled SQL'):
                run(spark, utils, dry_run=False, confirmation='PUBLISH_PLATFORM_COSTS')
            utils.fs.put.assert_not_called()
            spark.table.assert_not_called()


if __name__ == '__main__':
    unittest.main()
