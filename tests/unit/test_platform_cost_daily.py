"""Daily cost grain, migration compatibility, reconciliation and dashboard tests."""

from datetime import datetime, timezone
from decimal import Decimal
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / 'apps/finops_dashboard'
sys.path.insert(0, str(ROOT / 'src'))
sys.path.insert(0, str(APP))

from streamlit.testing.v1 import AppTest
from platform_costs.model import COLUMNS, monthly_from_daily, validate_records
from platform_costs.snapshot import build_payload, read_payload
from platform_costs.view import cost_trend, grouped_costs
from finops_cloud.monitoring.platform_costs import (
    DAILY, MONTHLY, AUDIT, VOLUME, latest_complete_export, prepare_payload, run,
)

NOW = datetime(2026, 10, 8, 20, tzinfo=timezone.utc)
NAME = '20261008T190000Z_' + 'c' * 32


def row(provider='GCP', day='2026-09-01', **changes):
    data = dict(usage_date=day, month=day[:7], provider=provider, service='Cloud Run',
                currency='EUR', cost_before_credits='12.345678901234567890', credits='-0.25',
                usage_quantity=None, usage_unit='', cost_basis='billing_export', period_status='partial')
    if provider == 'Databricks':
        data.update(service='PREMIUM_ALL_PURPOSE_COMPUTE', currency='USD', credits=None,
                    usage_quantity='1.123456789012345678', usage_unit='DBU', cost_basis='list_estimate')
    return {**data, **changes}


def manifest(**changes):
    return {**dict(schema_version='2', granularity='daily', run_id=NAME,
                   extracted_at=NOW.isoformat(), row_count='1', status='COMPLETE'), **changes}


def payload(records):
    monthly = monthly_from_daily(records)
    return build_payload([{key: r[key] for key in COLUMNS} for r in monthly.to_dict('records')],
                         generated_at=NOW.isoformat(), gcp_extracted_at=NOW.isoformat(),
                         daily_records=records)


class DailyCostsTests(unittest.TestCase):
    def test_daily_manifest_is_supported_and_inconsistent_grain_refused(self):
        directory = VOLUME + '/extracts/gcp/' + NAME
        fs = Mock()
        fs.ls.side_effect = [
            [SimpleNamespace(name=NAME + '/')],
            [SimpleNamespace(name='complete-000000000000.json', size=200),
             SimpleNamespace(name='data-000000000000.parquet', size=200)],
        ]
        fs.head.return_value = json.dumps(manifest())
        path, meta = latest_complete_export(fs, NOW)
        self.assertEqual(path, directory)
        self.assertEqual(meta['schema_version'], 2)
        self.assertEqual(meta['row_count'], 1)
        for bad in (manifest(granularity='monthly'), manifest(schema_version=True), manifest(schema_version='3')):
            fs.ls.side_effect = [[SimpleNamespace(name=NAME + '/')],
                                [SimpleNamespace(name='complete-000000000000.json', size=200)]]
            fs.head.return_value = json.dumps(bad)
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                latest_complete_export(fs, NOW)

    def test_daily_keys_allow_two_days_but_not_duplicates_or_mismatched_month(self):
        self.assertEqual(len(validate_records([row(), row(day='2026-09-02')], daily=True)), 2)
        for records in ([row(), row()], [row(month='2026-10')], [row(day='2026-09-31')],
                        [row(workspace_id='private')], [row(usage_date=None)]):
            with self.subTest(records=records), self.assertRaises(ValueError):
                validate_records(records, daily=True)

    def test_monthly_sums_are_exact_preserve_corrections_and_unknown_credits(self):
        records = [row(), row(day='2026-09-03', cost_before_credits='-2.1', credits='0.01'),
                   row('Databricks'), row('Databricks', day='2026-09-02', usage_quantity='-0.1')]
        frame = monthly_from_daily(records)
        gcp = frame[frame.provider == 'GCP'].iloc[0]
        db = frame[frame.provider == 'Databricks'].iloc[0]
        self.assertEqual(gcp.cost_before_credits, Decimal('10.245678901234567890'))
        self.assertEqual(gcp.reported_cost, Decimal('10.005678901234567890'))
        self.assertEqual(db.usage_quantity, Decimal('1.023456789012345678'))
        self.assertIsNone(db.credits)
        self.assertEqual(len(frame), 2)

    def test_v3_roundtrip_monthly_and_daily_reconcile_without_private_fields(self):
        output = payload([row(), row('Databricks'), row(day='2026-09-02')])
        self.assertEqual(output['schema_version'], 3)
        self.assertEqual(len(output['records']), 2)
        as_of, monthly = read_payload(output, remote=True, now=NOW)
        self.assertEqual(as_of, '2026-10-08')
        self.assertEqual(len(monthly.attrs['daily_records']), 3)
        for identifier in ('workspace_id', 'job_id', 'run_id', 'resource_id', 'email'):
            self.assertNotIn(identifier, json.dumps(output))
        output['records'][0]['cost_before_credits'] = '999'
        with self.assertRaisesRegex(ValueError, 'reconcile'):
            read_payload(output, remote=True, now=NOW)

    def test_future_daily_usage_and_missing_daily_provider_refused(self):
        for records in ([row(day='2026-10-09'), row('Databricks')], [row()]):
            with self.subTest(records=records), self.assertRaises(ValueError):
                payload(records)

    def test_prepare_daily_and_transitional_monthly_payloads(self):
        result = prepare_payload([row()], [row('Databricks')], manifest(row_count=1), NOW)
        self.assertEqual(result['schema_version'], 3)
        old_gcp = {key: r for key, r in row().items() if key != 'usage_date'}
        old_manifest = {key: value for key, value in manifest(schema_version=1, row_count=1).items() if key != 'granularity'}
        result = prepare_payload([old_gcp], [row('Databricks'), row('Databricks', day='2026-09-02')], old_manifest, NOW)
        self.assertEqual(result['schema_version'], 2)
        self.assertNotIn('daily_records', result)
        self.assertEqual(len(result['records']), 2)
        self.assertEqual(read_payload(result, remote=True, now=NOW)[1].attrs, {})

    def test_missing_days_are_gaps_and_measured_zero_stays_zero(self):
        frame = validate_records([row(cost_before_credits='0', credits='0'),
                                  row(day='2026-09-03')], daily=True)
        figure = cost_trend(frame, daily=True, month='2026-09')
        self.assertEqual(figure.data[0].type, 'bar')
        self.assertEqual(figure.layout.barmode, 'group')
        self.assertEqual(list(figure.data[0].x)[:3], ['2026-09-01', '2026-09-02', '2026-09-03'])
        self.assertEqual(figure.data[0].y[0], 0)
        self.assertIsNone(figure.data[0].y[1])
        self.assertIn('0,00 EUR', figure.data[0].customdata[0])
        self.assertIn('Usage Date', figure.layout.xaxis.title.text)

    def test_chart_aggregation_does_not_round_high_precision_decimals(self):
        frame = validate_records([row(cost_before_credits='99999999999999.123456789012345678', credits='0'),
                                  row(day='2026-09-02', cost_before_credits='0.000000000000000001', credits='0')], daily=True)
        total = grouped_costs(frame, 'service').iloc[0].reported_cost
        self.assertEqual(total, Decimal('99999999999999.123456789012345679'))

    def test_daily_dashboard_filters_month_keeps_both_currencies_and_european_numbers(self):
        output = payload([row(), row('Databricks'), row(day='2026-10-01', cost_before_credits='2', credits='0')])
        as_of, frame = read_payload(output, now=NOW)
        prefix = f'import sys\nsys.path.insert(0, {str(APP)!r})\n'
        with patch('platform_costs.view.load_snapshot', return_value=(as_of, frame)):
            app = AppTest.from_string(prefix + 'from platform_costs.view import render_platform_costs\nrender_platform_costs()').run()
            self.assertFalse(app.exception)
            self.assertEqual(app.selectbox(key='platform_cost_view').options, ['Daily', 'Monthly', 'Yearly'])
            self.assertEqual(app.selectbox(key='platform_cost_view').label, 'View by')
            self.assertEqual(app.selectbox(key='platform_cost_year').label, 'Year')
            self.assertEqual(app.selectbox(key='platform_cost_month').label, 'Month')
            app.selectbox(key='platform_cost_view').select('Daily').run()
            self.assertFalse(app.exception)
            app.selectbox(key='platform_cost_month').select('10 · October').run()
            self.assertFalse(app.exception)
            self.assertEqual(app.metric[1].value, '2,00 EUR')
            self.assertTrue(any(s.value == 'Detailed Daily Cost Table' for s in app.subheader))
            app.selectbox(key='platform_cost_month').select('09 · September').run()
            self.assertFalse(app.exception)
            self.assertEqual(app.metric[1].value, '12,10 EUR')
            self.assertEqual(app.metric[3].value, '12,35 USD')
            self.assertEqual(app.metric[2].value, '1,12')

    def test_daily_dual_axes_preserve_provider_gaps_signed_values_and_dbu_hover(self):
        frame = validate_records([row(cost_before_credits='0', credits='0'),
                                  row('Databricks', day='2026-09-02', cost_before_credits='-2',
                                      usage_quantity='-0.5')], daily=True)
        figure = cost_trend(frame, daily=True, month='2026-09')
        gcp, db = figure.data
        self.assertEqual(db.type, 'bar')
        self.assertNotEqual(gcp.offsetgroup, db.offsetgroup)
        self.assertEqual(list(gcp.x), list(db.x))
        self.assertEqual(gcp.y[0], 0)
        self.assertIsNone(db.y[0])
        self.assertIsNone(gcp.y[1])
        self.assertEqual(db.y[1], -2)
        self.assertEqual(db.yaxis, 'y2')
        self.assertEqual(db.customdata[1], ['-2,00 USD', '-0,50'])
        self.assertIn('Net DBUs', db.hovertemplate)
        self.assertEqual(figure.layout.yaxis2.rangemode, 'tozero')
        self.assertIsNone(figure.layout.yaxis2.range)

    def test_chart_never_aggregates_two_currencies_for_one_provider(self):
        frame = validate_records([row(), row(service='Cloud Storage', currency='USD')], daily=True)
        with self.assertRaisesRegex(ValueError, 'one currency per provider'):
            cost_trend(frame, daily=True, month='2026-09')

    def test_dashboard_multiple_currencies_select_per_provider_not_globally(self):
        output = payload([row(), row(service='Cloud Storage', currency='USD'), row('Databricks')])
        as_of, frame = read_payload(output, now=NOW)
        prefix = f'import sys\nsys.path.insert(0, {str(APP)!r})\n'
        with patch('platform_costs.view.load_snapshot', return_value=(as_of, frame)):
            app = AppTest.from_string(prefix + 'from platform_costs.view import render_platform_costs\nrender_platform_costs()').run()
            self.assertFalse(app.exception)
            self.assertEqual(app.selectbox(key='platform_cost_currency_GCP').value, 'EUR')
            self.assertEqual(app.metric[1].value, '12,10 EUR')
            self.assertEqual(app.metric[3].value, '12,35 USD')
            app.selectbox(key='platform_cost_currency_GCP').select('USD').run()
            self.assertFalse(app.exception)
            self.assertEqual(app.metric[1].value, '12,10 USD')
            self.assertEqual(app.metric[3].value, '12,35 USD')

    def test_monthly_missing_month_is_a_gap_and_absent_provider_is_not_a_zero(self):
        frame = validate_records([{key: value for key, value in r.items() if key != 'usage_date'}
                                  for r in [row(day='2026-07-01'), row(day='2026-09-01')]])
        figure = cost_trend(frame)
        self.assertEqual(len(figure.data), 1)
        self.assertEqual(list(figure.data[0].x), ['2026-07', '2026-08', '2026-09'])
        self.assertIsNone(figure.data[0].y[1])

    def test_yearly_costs_aggregate_months_without_mutating_source(self):
        frame = monthly_from_daily([row(day='2025-09-01', cost_before_credits='10', credits='-1'),
                                    row(day='2026-09-01', cost_before_credits='20', credits='-2'),
                                    row(day='2026-10-01', cost_before_credits='30', credits='-3'),
                                    row('Databricks', day='2026-09-01')])
        figure = cost_trend(frame, yearly=True)
        self.assertEqual(list(figure.data[0].x), ['2025', '2026'])
        self.assertEqual(list(figure.data[0].y), [9, 45])
        self.assertEqual(figure.layout.xaxis.title.text, 'Usage Year')
        self.assertIsNone(figure.data[1].y[0])
        self.assertNotIn('year', frame.columns)

    def test_daily_all_months_keeps_dates_and_month_filter_excludes_other_months(self):
        frame = validate_records([row(day='2025-09-01'), row(day='2026-09-01'),
                                  row('Databricks', day='2026-09-02')], daily=True)
        figure = cost_trend(frame, daily=True, month_number='09')
        self.assertTrue(all(day[5:7] == '09' for day in figure.data[0].x))
        self.assertIn('2025-09-01', figure.data[0].x)
        self.assertIn('2026-09-01', figure.data[0].x)
        self.assertTrue(all(len(label) == 10 for label in figure.layout.xaxis.ticktext))
        self.assertLessEqual(len(figure.layout.xaxis.ticktext), 12)

    def test_shared_year_month_filters_and_empty_2025_never_invent_zero(self):
        output = payload([row(), row('Databricks'), row(day='2026-10-01', cost_before_credits='2', credits='0')])
        as_of, frame = read_payload(output, now=NOW)
        prefix = f'import sys\nsys.path.insert(0, {str(APP)!r})\n'
        with patch('platform_costs.view.load_snapshot', return_value=(as_of, frame)):
            app = AppTest.from_string(prefix + 'from platform_costs.view import render_platform_costs\nrender_platform_costs()').run()
            self.assertFalse(app.exception)
            self.assertEqual(app.selectbox(key='platform_cost_year').options[1], '2025')
            self.assertEqual(len(app.selectbox(key='platform_cost_month').options), 13)
            app.selectbox(key='platform_cost_year').select('2025').run()
            self.assertFalse(app.exception)
            self.assertEqual(len(app.get('bidi_component')), 1)
            self.assertTrue(all(metric.value == '—' for metric in app.metric))
            app.selectbox(key='platform_cost_year').select('2026').run()
            app.selectbox(key='platform_cost_month').select('09 · September').run()
            for mode in ['Yearly', 'Daily', 'Monthly']:
                app.selectbox(key='platform_cost_view').select(mode).run()
                self.assertFalse(app.exception)
                self.assertEqual(app.selectbox(key='platform_cost_month').value, '09 · September')
                self.assertEqual(app.metric[1].value, '12,10 EUR')
                self.assertEqual(app.metric[3].value, '12,35 USD')
            app.selectbox(key='platform_cost_month').select('All Months').run()
            self.assertEqual(app.metric[1].value, '14,10 EUR')

    def test_empty_period_keeps_calendar_axes_but_no_cost_values(self):
        empty = validate_records([row()], daily=True).iloc[:0]
        for mode in ('Daily', 'Monthly', 'Yearly'):
            figure = cost_trend(empty, daily=mode == 'Daily', yearly=mode == 'Yearly',
                                year='2025', month_number='02', provider_currencies={'GCP': 'EUR', 'Databricks': 'USD'})
            expected = ['2025-02'] if mode == 'Monthly' else ['2025'] if mode == 'Yearly' else [f'2025-02-{day:02}' for day in range(1, 29)]
            self.assertEqual(list(figure.layout.xaxis.categoryarray), expected)
            self.assertEqual(len(figure.data), 2)
            self.assertTrue(all(value is None for trace in figure.data for value in trace.y))
            self.assertTrue(figure.layout.yaxis.visible)
            self.assertTrue(figure.layout.yaxis2.visible)
            self.assertFalse(figure.layout.yaxis.showticklabels)
            self.assertTrue(any(note.text == '<i>No published record</i>' for note in figure.layout.annotations))
            self.assertEqual(figure.data[1].marker.color, '#FF543D')

    def test_empty_period_preserves_selected_provider_currency(self):
        empty = validate_records([row()], daily=True).iloc[:0]
        figure = cost_trend(empty, year='2025', month_number='02',
                            provider_currencies={'GCP': 'GBP', 'Databricks': 'EUR'})
        self.assertEqual(figure.layout.yaxis.title.text, 'Cost in GBP')
        self.assertEqual(figure.layout.annotations[0].text, 'Cost in Euro')
        self.assertIn('(GBP)', figure.data[0].name)

    def test_publication_checks_both_schemas_then_overwrites_daily_and_monthly(self):
        for wrong_schema in (False, True):
            spark, utils, monthly, daily = Mock(), Mock(), Mock(), Mock()
            monthly.columns = ['month', 'provider', 'service', 'currency', 'cost_before_credits',
                               'credits', 'usage_quantity', 'usage_unit', 'cost_basis',
                               'period_status', 'collection_run_id', 'collected_at']
            daily.columns = ['usage_date', *monthly.columns]
            def table(name):
                result = Mock()
                result.columns = (['wrong'] if wrong_schema else daily.columns) if name == DAILY else monthly.columns
                return result
            spark.table.side_effect = table
            with patch('finops_cloud.monitoring.platform_costs.datetime') as clock, \
                 patch('finops_cloud.monitoring.platform_costs.latest_complete_export', return_value=('/valid', manifest(row_count=1))), \
                 patch('finops_cloud.monitoring.platform_costs._collect', side_effect=[[row()], [row('Databricks')]]), \
                 patch('finops_cloud.monitoring.platform_costs._monthly_frame', return_value=monthly), \
                 patch('finops_cloud.monitoring.platform_costs._daily_frame', return_value=daily), \
                 patch('finops_cloud.monitoring.platform_costs._audit') as audit:
                clock.now.return_value = NOW
                if wrong_schema:
                    with self.assertRaisesRegex(ValueError, 'daily cost schema'):
                        run(spark, utils, dry_run=False, confirmation='PUBLISH_PLATFORM_COSTS')
                    monthly.write.mode.assert_not_called()
                    daily.write.mode.assert_not_called()
                    utils.fs.put.assert_not_called()
                else:
                    result = run(spark, utils, dry_run=False, confirmation='PUBLISH_PLATFORM_COSTS')
                    self.assertEqual(result['granularity'], 'daily')
                    self.assertEqual(result['daily_rows'], 2)
                    monthly.write.mode.return_value.insertInto.assert_called_once_with(MONTHLY)
                    daily.write.mode.return_value.insertInto.assert_called_once_with(DAILY)
                    utils.fs.put.assert_called_once()
                    self.assertEqual(json.loads(utils.fs.put.call_args.args[1])['schema_version'], 3)
                    self.assertEqual(audit.call_args.args[3], 'PUBLISHED')

    def test_daily_preview_never_writes(self):
        spark, utils = Mock(), Mock()
        with patch('finops_cloud.monitoring.platform_costs.datetime') as clock, \
             patch('finops_cloud.monitoring.platform_costs.latest_complete_export', return_value=('/valid', manifest(row_count=1))), \
             patch('finops_cloud.monitoring.platform_costs._collect', side_effect=[[row()], [row('Databricks')]]):
            clock.now.return_value = NOW
            result = run(spark, utils)
            self.assertEqual(result['status'], 'PREVIEW')
            self.assertEqual(result['daily_rows'], 2)
            spark.table.assert_not_called()
            utils.fs.put.assert_not_called()

    def test_sql_artifacts_keep_one_source_query_and_additive_setup(self):
        sql = ROOT / 'platform/common/sql/monitoring/platform_costs'
        self.assertFalse((sql / '02_collect_databricks_monthly.sql').exists())
        db = (sql / '02_collect_databricks_daily.sql').read_text()
        self.assertIn("prices.currency_code = 'USD'", db)
        self.assertIn('GROUP BY usage_date, month, service', db)
        bq = (sql / '01_export_gcp_to_gcs.sql').read_text()
        self.assertIn("2 AS schema_version, 'daily' AS granularity", bq)
        self.assertIn('GROUP BY usage_date, month, service, currency', bq)
        setup = (sql / '03_create_monitoring_objects.sql').read_text()
        self.assertIn('CREATE TABLE IF NOT EXISTS finops_ops.monitoring.platform_cost_daily', setup)
        self.assertNotIn('DROP ', setup)
        validation = (sql / '04_validate_platform_costs.sql').read_text()
        self.assertIn('FULL OUTER JOIN daily_totals', validation)
        self.assertIn('monthly.collection_run_id <=> daily.run_id', validation)


if __name__ == '__main__':
    unittest.main()
