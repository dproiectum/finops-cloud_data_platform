"""Presentation regression tests; no Databricks connection or credentials needed."""

from decimal import Decimal
import ast
import json
from pathlib import Path
import sys
import tomllib
import unittest
from unittest.mock import patch

import pandas as pd
import plotly.express as px
import streamlit as st
from streamlit.testing.v1 import AppTest


APP = Path(__file__).resolve().parents[2] / "apps/finops_dashboard"
sys.path.insert(0, str(APP))

from formatting import (  # noqa: E402
    SAVINGS_DETAIL_COLUMNS, chart_layout, column_label, comparison_state,
    financial_table, integer, money, percent,
    savings_detail_table,
)
from data_access import DatabricksDataSource  # noqa: E402
from charts import (  # noqa: E402
    comparable_years, cost_bridge, lineage_chart, savings_cost_chart,
    service_cost_chart, charge_cost_chart,
)


class CallablePage:
    """AppTest cannot switch callable pages; route page-body tests explicitly."""

    def __init__(self, function, *, title, **kwargs):
        self.function = function
        self.title = title

    def run(self):
        self.function()


class DashboardPresentationTests(unittest.TestCase):
    def setUp(self):
        st.cache_data.clear()
        st.cache_resource.clear()

    def tearDown(self):
        st.cache_data.clear()
        st.cache_resource.clear()

    def test_native_navigation_and_app_surfaces_keep_streamlit_theme(self):
        # Native navigation moves into the sidebar on small screens. Its text
        # and background must come from the same theme, including live switches.
        tree = ast.parse((APP / "app.py").read_text())
        styles = [node.value for node in ast.walk(tree)
                  if isinstance(node, ast.Constant) and isinstance(node.value, str)
                  and "<style>" in node.value]
        self.assertEqual(len(styles), 1)
        css = styles[0]
        for selector in (".stApp", "stSidebar", "stHeader", "stTopNav",
                         "stSidebarNav"):
            self.assertNotIn(selector, css)
        self.assertNotIn("!important", css)
        self.assertNotIn("st.context.theme", (APP / "app.py").read_text())
        self.assertIn('[data-testid="stMetricLabel"] { color:inherit; }', css)
        self.assertIn(".architecture-card h4 { color:inherit;", css)
        self.assertIn(".finops-subtitle { color:inherit;", css)

    def test_european_metrics_include_negative_values_and_signed_change(self):
        self.assertEqual(money(Decimal("912000")), "912\u202f000,00 €")
        self.assertEqual(money(-1234.5), "-1\u202f234,50 €")
        self.assertEqual(integer(164145), "164\u202f145")
        self.assertEqual(percent(14.66), "14,66 %")
        self.assertEqual(percent(2.5, signed=True), "+2,50 %")
        self.assertEqual(percent(-2.5, signed=True), "-2,50 %")
        self.assertEqual(money(None), "0,00 €")
        self.assertEqual(integer(float("nan")), "0")

    def test_finops_inspired_theme_is_shipped_without_sandbox_navigation(self):
        theme = tomllib.loads((APP / '.streamlit/config.toml').read_text())['theme']
        self.assertEqual(theme['base'], 'light')
        self.assertEqual(theme['chartCategoricalColors'][:2], ['#005A9E', '#00B894'])
        self.assertEqual(theme['light']['backgroundColor'], '#FFFFFF')
        self.assertEqual(theme['dark']['backgroundColor'], '#13232D')
        for mode in ['light', 'dark']:
            self.assertEqual(theme[mode]['textColor'], theme[mode]['sidebar']['textColor'])
        source = (APP / 'app.py').read_text()
        self.assertNotIn('Dashboard Style', source)
        self.assertNotIn('127.0.0.1', source)
        self.assertNotIn('FINOPS_PREVIEW_STYLE', source)
        self.assertNotIn('recolor_chart', source)

    def test_lineage_keeps_original_public_palette_and_structure(self):
        figure = lineage_chart()
        graph = figure.data[0]
        self.assertEqual(graph.type, 'sankey')
        self.assertEqual(graph.arrangement, 'fixed')
        self.assertEqual(graph.textfont.shadow, 'none')
        self.assertEqual(graph.node.y[-1], .375)
        self.assertEqual(list(graph.node.label), [
            'GCS Parquet', 'RAW Volume', 'Bronze', 'FOCUS Contract', 'Silver',
            'Gold', 'Datamarts', 'Streamlit', 'OPS Audit',
        ])
        self.assertEqual(list(graph.node.color), [
            '#0078d4', '#2b88d8', '#2b88d8', '#71afe5', '#71afe5',
            '#00a4ef', '#50e6ff', '#deecf9', '#8764b8',
        ])
        self.assertEqual(list(zip(graph.link.source, graph.link.target)), [
            (0, 1), (1, 2), (2, 3), (3, 4), (4, 5), (5, 6), (6, 7),
            (2, 8), (4, 8), (5, 8),
        ])
        self.assertEqual(figure.layout.height, 590)
        self.assertEqual(figure.layout.paper_bgcolor, '#ffffff')
        self.assertEqual(figure.layout.font.color, '#424242')

    def test_table_formatting_preserves_data_and_identifiers(self):
        frame = pd.DataFrame({
            "total_billed_cost": [Decimal("1234.50"), None],
            "resource_count": [164145, 0],
            "subscription_id": ["000123", "000456"],
        })
        original = frame.copy(deep=True)
        styled = financial_table(frame)
        html = styled.to_html()
        self.assertIn("1\u202f234,50 €", html)
        self.assertIn("164\u202f145", html)
        self.assertIn("000123", html)
        self.assertIn("—", html)
        self.assertEqual(list(styled.data.columns),
                         ["Total Billed Cost", "Resource Count", "Subscription ID"])
        pd.testing.assert_frame_equal(styled.data.set_axis(original.columns, axis=1), original)
        pd.testing.assert_frame_equal(frame, original)

    def test_column_headers_are_readable_and_keep_acronyms(self):
        for key, label in {
            "service_name": "Service Name", "billing_month": "Billing Month",
            "sku_id": "SKU ID", "run_id": "Run ID",
            "application_owner_email": "Application Owner Email",
            "critical_completeness_rate": "Critical Completeness Rate",
            "average_cost_per_resource": "Average by Resource",
            "Certified Source": "Certified Source", "KPI": "KPI",
        }.items():
            with self.subTest(column=key):
                self.assertEqual(column_label(key), label)

    def test_comparison_color_requires_a_positive_benefit(self):
        for value, expected in [(Decimal("12.50"), "positive"), (-12.5, "negative"),
                                (0, "neutral"), (None, "neutral"),
                                (float("nan"), "neutral")]:
            with self.subTest(value=value):
                self.assertEqual(comparison_state(value), expected)

    def test_comparison_tile_selects_only_its_own_color_scope(self):
        # Exercise the actual UI helper without initializing a cloud connection.
        tree = ast.parse((APP / "app.py").read_text())
        helper = next(node for node in tree.body
                      if isinstance(node, ast.FunctionDef) and node.name == "catalog_price_metric")
        prefix = (
            f"import sys\nsys.path.insert(0, {str(APP)!r})\n"
            "import streamlit as st\nimport pandas as pd\n"
            "from formatting import comparison_state, money\n"
        )
        for value, state, rendered in [(12.5, "positive", "12,50 €"),
                                       (-12.5, "negative", "-12,50 €"),
                                       (0, "neutral", "0,00 €"),
                                       (None, "neutral", "—")]:
            with self.subTest(value=value):
                app = AppTest.from_string(
                    prefix + ast.unparse(helper) +
                    f"\ncatalog_price_metric(st.columns(1)[0], {value!r})\n"
                ).run()
                self.assertFalse(app.exception)
                self.assertEqual(app.metric[0].value, rendered)
                ids = [block.proto.id for block in app.get("flex_container")]
                self.assertTrue(any(f"catalog_price_comparison_{state}" in key for key in ids))

    def test_chart_separators_and_cost_axes(self):
        figure = px.bar(x=["2025-01"], y=[912000], labels={"y": "Cost (€)"})
        chart_layout(figure)
        self.assertEqual(figure.layout.separators, ",\u202f")
        self.assertEqual(figure.layout.yaxis.tickformat, ",.2f")
        self.assertEqual(figure.layout.yaxis.hoverformat, ",.2f")

    def test_savings_table_has_ordered_business_labels_and_european_values(self):
        frame = pd.DataFrame([{
            "billing_month": "2026-01", "list_cost": 1300, "contracted_cost": 1000,
            "negotiated_savings": 300, "reservation": 100, "savings_plan": 150,
            "usage_on_demand": 850, "usage_dynamic": 5, "adjustment": -5,
            "effective_cost": 1100, "savings_rate": 15.38,
            "commitment_savings": -100, "total_savings": 200, "other_effective_cost": 0,
        }])
        original = frame.copy(deep=True)
        styled = savings_detail_table(frame)
        self.assertEqual(list(styled.data.columns), list(SAVINGS_DETAIL_COLUMNS.values()))
        self.assertNotIn("commitment_savings", styled.data)
        self.assertNotIn("Other Charges", styled.data)
        self.assertEqual(list(styled.data.columns)[-3:],
                         ["Effective Cost", "Realized Savings", "Saving Rate"])
        self.assertEqual(styled.data["Realized Savings"].iloc[0], 200)
        self.assertIn("200,00 €", styled.to_html())
        self.assertIn("1\u202f100,00 €", styled.to_html())
        self.assertIn("-5,00 €", styled.to_html())
        self.assertIn("15,38 %", styled.to_html())
        pd.testing.assert_frame_equal(frame, original)

    def test_savings_table_missing_components_are_not_fabricated_zeroes(self):
        styled = savings_detail_table(pd.DataFrame([{
            "billing_month": "2026-01", "list_cost": 1300, "contracted_cost": 1000,
            "negotiated_savings": 300, "effective_cost": 1100, "savings_rate": 15.38,
        }]))
        self.assertTrue(styled.data["Reservation"].isna().all())
        self.assertTrue(styled.data["Savings Plan"].isna().all())
        self.assertIn("—", styled.to_html())

    def test_savings_table_keeps_other_charges_when_present(self):
        styled = savings_detail_table(pd.DataFrame([{
            "billing_month": "2026-01", "other_effective_cost": -2.5,
        }]))
        self.assertEqual(list(styled.data.columns)[-4:],
                         ["Other Charges", "Effective Cost", "Realized Savings", "Saving Rate"])
        self.assertIn("-2,50 €", styled.to_html())

    def test_services_have_one_bar_per_name_and_explicit_order(self):
        frame = pd.DataFrame({
            "service_name": ["Azure NetApp Files", "Azure NetApp Files", "Compute"],
            "service_category": ["Storage", "Other", "Compute"],
            "total_billed_cost": [100, 200, 400],
        })
        figure = service_cost_chart(frame, "Services")
        self.assertEqual(len(figure.data), 1)
        self.assertEqual(list(figure.data[0].y), ["Compute", "Azure NetApp Files"])
        self.assertEqual(list(figure.data[0].x), [400, 300])
        self.assertEqual(figure.layout.yaxis.autorange, "reversed")
        self.assertFalse(figure.layout.showlegend)
        ascending = service_cost_chart(frame, "Services", "Lowest cost first")
        self.assertEqual(list(ascending.data[0].y), ["Azure NetApp Files", "Compute"])
        alphabetical = service_cost_chart(frame, "Services", "Name A–Z")
        self.assertEqual(list(alphabetical.data[0].y), ["Azure NetApp Files", "Compute"])

    def test_charge_chart_retains_negative_credits(self):
        frame = pd.DataFrame({"charge_category": ["Usage", "Credit"],
                              "total_billed_cost": [1000, -50]})
        figure = charge_cost_chart(frame)
        self.assertEqual(list(figure.data[0].x), [1000, -50])
        self.assertIn("-50,00 €", figure.data[0].text)

    def test_cost_bridge_shows_negative_difference_as_cost_increase(self):
        figure = cost_bridge(pd.Series({"list_cost": 1300, "contracted_cost": 1000,
                                        "effective_cost": 1100}))
        trace = figure.data[0]
        self.assertEqual(list(trace.y), [1300, -300, 100, 0])
        self.assertEqual(list(trace.measure), ["absolute", "relative", "relative", "total"])
        self.assertEqual(trace.text[-1], "1\u202f100,00 €")

    def test_savings_stack_reaches_list_price_without_double_counting(self):
        frame = pd.DataFrame({"billing_month": ["2026-01"], "list_cost": [1300],
                              "contracted_cost": [1000], "effective_cost": [1100]})
        original = frame.copy(deep=True)
        figure, stacked = savings_cost_chart(frame)
        self.assertTrue(stacked)
        self.assertEqual(figure.layout.barmode, "stack")
        self.assertEqual(list(figure.data[0].y), [1100])
        self.assertEqual(list(figure.data[1].y), [200])
        self.assertEqual(len(figure.data), 2)
        self.assertEqual([trace.name for trace in figure.data],
                         ["Effective Cost", "Realized Savings"])
        self.assertEqual(figure.data[0].marker.color, "#005a9e")
        self.assertEqual(figure.data[1].marker.color, "#00b894")
        self.assertEqual(figure.layout.title.text, "Realized Savings")
        self.assertIn("1\u202f100,00 €", figure.data[0].customdata[0])
        self.assertEqual(list(figure.data[1].customdata[0]), ["200,00 €", "1\u202f300,00 €"])
        self.assertEqual(figure.data[1].hovertemplate,
                         "%{x}<br>List Cost: %{customdata[1]}"
                         "<br>Realized Savings: %{customdata[0]}<extra></extra>")
        pd.testing.assert_frame_equal(frame, original)

    def test_savings_tooltip_keeps_month_costs_aligned_after_sorting(self):
        figure, _ = savings_cost_chart(pd.DataFrame({
            "billing_month": ["2026-02", "2026-01"],
            "list_cost": [2000, 1300], "effective_cost": [1500, 1100],
        }))
        self.assertEqual(list(figure.data[1].x), ["2026-01", "2026-02"])
        self.assertEqual([list(row) for row in figure.data[1].customdata],
                         [["200,00 €", "1\u202f300,00 €"],
                          ["500,00 €", "2\u202f000,00 €"]])

    def test_savings_never_clips_negative_costs_or_missing_values(self):
        for values in [(100, 90, 110), (-100, -90, -80), (None, 90, 80), (100, 90, None)]:
            with self.subTest(values=values):
                frame = pd.DataFrame({"billing_month": ["2026-01"],
                                      "list_cost": [values[0]], "contracted_cost": [values[1]],
                                      "effective_cost": [values[2]]})
                figure, stacked = savings_cost_chart(frame)
                self.assertFalse(stacked)
                self.assertEqual(figure.layout.barmode, "group")
                self.assertEqual(len(figure.data), 2)
                if values[2] is None:
                    self.assertTrue(pd.isna(figure.data[0].y[0]))
                    self.assertEqual(figure.data[0].customdata[0][0], "Unavailable")
                else:
                    self.assertEqual(figure.data[0].y[0], values[2])
                if values[0] is None or values[2] is None:
                    self.assertTrue(pd.isna(figure.data[1].y[0]))
                else:
                    self.assertEqual(figure.data[1].y[0], values[0] - values[2])

    def test_savings_chart_does_not_require_contracted_cost(self):
        figure, stacked = savings_cost_chart(pd.DataFrame({
            "billing_month": ["2026-01"], "list_cost": [100], "effective_cost": [80],
        }))
        self.assertTrue(stacked)
        self.assertEqual(len(figure.data), 2)

    def test_year_comparison_uses_only_common_months(self):
        frame = pd.DataFrame({
            "billing_month": ["2025-01", "2025-02", "2025-03", "2026-01", "2026-03"],
            "billed_cost": [10, 9999, 20, 12, 24],
        })
        current, previous, common = comparable_years(frame, "2026", "2025")
        self.assertEqual(common, ["01", "03"])
        self.assertEqual(current["billed_cost"].sum(), 36)
        self.assertEqual(previous["billed_cost"].sum(), 30)
        self.assertEqual(len(frame), 5)
        current, previous, common = comparable_years(frame, "2027", "2025")
        self.assertEqual(common, [])
        self.assertTrue(current.empty)
        self.assertTrue(previous.empty)

    def test_all_pages_render_without_live_databricks(self):
        # One deterministic fixture row covers the columns consumed by all pages.
        # It is test data, not evidence for the deployed app or cloud reconciliation.
        text_columns = {
            "billing_month": "2025-01", "service_name": "Compute",
            "service_category": "Compute", "charge_category": "Usage",
            "cost_center": "Engineering", "resource_name": "vm-test",
            "resource_group_name": "rg-test", "region": "test-region",
            "status": "SUCCESS", "environment": "prod", "run_id": "test-run",
        }
        numeric_columns = {
            "billed_cost": 912000, "effective_cost": 1101755.75,
            "list_cost": 1290989.95, "contracted_cost": 1090989.95,
            "savings_vs_list": 189234.2, "savings_rate": 14.66,
            "month_change_rate": 2.5, "charge_lines": 164145,
            "resources": 22453, "services": 59, "average_cost_per_resource": 40.62,
            "daily_billed_cost": 30000, "monthly_billed_cost": 912000,
            "total_billed_cost": 912000, "resource_count": 22453,
            "negotiated_savings": 200000, "commitment_savings": -10765.8,
            "total_savings": 189234.2, "critical_completeness_rate": 100,
            "reservation": 100000, "savings_plan": 100000,
            "usage_on_demand": 901000, "usage_dynamic": 800, "adjustment": -44.25,
            "other_effective_cost": 0,
            "batches": 1, "total_rows": 164145, "billed_cost_nulls": 0,
            "currency_nulls": 0, "service_nulls": 0,
            "billing_rows": 164145, "after_rows": 164145,
            "after_billing_difference": 0, "total_runs": 1, "successful_runs": 1,
        }
        fixture = pd.DataFrame([{
            **text_columns, **numeric_columns,
            "date": pd.Timestamp("2025-01-01"),
            "latest_silver_load": pd.Timestamp("2025-02-01"),
        }])
        with (
            patch.object(DatabricksDataSource, "healthcheck"),
            patch.object(DatabricksDataSource, "query", side_effect=lambda _: fixture.copy()),
        ):
            # Smoke test the real native navigation and default Executive page.
            app = AppTest.from_file(str(APP / "app.py"), default_timeout=30).run()
            self.assertFalse(app.exception)
            self.assertEqual(len(app.radio), 0)
            self.assertEqual(app.metric[0].value, "912\u202f000,00 €")
            self.assertEqual(app.metric[0].delta, "+2,50 % MoM")
            self.assertEqual(app.metric[4].value, "164\u202f145")
            self.assertEqual([metric.label for metric in app.metric], [
                "Billed Cost", "Effective Cost", "Savings vs. Catalog Price",
                "Catalog Price Difference Rate", "Charge Lines", "Active Resources",
                "Consumed Services", "Average by Resource",
            ])
            self.assertEqual(app.metric[2].value, "189\u202f234,20 €")
            self.assertIn("List Cost − Effective Cost", app.metric[2].proto.help)
            self.assertIn('"type":"category"', app.get("plotly_chart")[1].proto.spec)
            titles = ["Executive Overview", "Cost Drivers", "Savings",
                      "Allocation & Accountability", "Resources", "Operations & Quality",
                      "Knowledge Base", "Architecture",
                      "About the Project", "About Me"]
            for title in titles:
                with self.subTest(page=title):
                    def choose_page(pages, *, position):
                        self.assertEqual(position, "top")
                        self.assertNotIn("Project Costs", [page.title for page in pages])
                        return next(page for page in pages if page.title == title)

                    with patch.object(st, "Page", CallablePage), patch.object(
                        st, "navigation", side_effect=choose_page
                    ):
                        app = AppTest.from_file(str(APP / "app.py"), default_timeout=30).run()
                        self.assertFalse(app.exception)
                        if title in {"About the Project", "About Me"}:
                            self.assertFalse(app.sidebar.selectbox)
                        for table in app.dataframe:
                            self.assertFalse(any("_" in column for column in table.value.columns))
                        if title == "Savings":
                            self.assertEqual(app.metric[3].label, "Realized Savings")
                            self.assertEqual(app.metric[3].value, "189\u202f234,20 €")
                            chart = json.loads(app.get("plotly_chart")[0].proto.spec)
                            self.assertEqual(chart["layout"]["barmode"], "stack")
                            self.assertEqual(chart["data"][0]["name"], "Effective Cost")
                            self.assertEqual(chart["data"][1]["name"], "Realized Savings")
                            self.assertEqual(chart["layout"]["title"]["text"], "Realized Savings")
                            self.assertIn("List Cost: %{customdata[1]}",
                                          chart["data"][1]["hovertemplate"])
                            self.assertEqual(len(chart["data"]), 2)
                            self.assertEqual(app.subheader[0].value, "Detailed Table")
                            self.assertEqual(list(app.dataframe[0].value.columns),
                                             list(SAVINGS_DETAIL_COLUMNS.values()))
                            self.assertFalse(any("diamond" in item.value for item in app.caption))
                            self.assertIn('"type":"category"', app.get("plotly_chart")[1].proto.spec)
                            trend = json.loads(app.get("plotly_chart")[1].proto.spec)
                            self.assertEqual(trend["layout"]["title"]["text"],
                                             "Realized Savings by Month")
                            self.assertIn("Realized Savings: %{customdata[0]}",
                                          trend["data"][0]["hovertemplate"])
                        if title == "Architecture":
                            chart = app.get('plotly_chart')[0]
                            self.assertEqual(chart.proto.theme, '')
                            spec = json.loads(chart.proto.spec)
                            self.assertEqual(spec['layout']['paper_bgcolor'], '#ffffff')
                            self.assertEqual(spec['data'][0]['node']['color'][0], '#0078d4')

    def test_savings_page_stays_usable_before_datamart_refresh(self):
        fixture = pd.DataFrame([{
            "billing_month": "2026-01", "list_cost": 1300, "contracted_cost": 1000,
            "effective_cost": 1100, "negotiated_savings": 300,
            "commitment_savings": -100, "total_savings": 200, "savings_rate": 15.38,
        }])
        with (
            patch.object(DatabricksDataSource, "healthcheck"),
            patch.object(DatabricksDataSource, "query", side_effect=lambda _: fixture.copy()),
            patch.object(st, "Page", CallablePage),
            patch.object(st, "navigation",
                         side_effect=lambda pages, **_: next(p for p in pages if p.title == "Savings")),
        ):
            app = AppTest.from_file(str(APP / "app.py"), default_timeout=30).run()
            self.assertFalse(app.exception)
            self.assertTrue(app.dataframe[0].value["Reservation"].isna().all())
            self.assertTrue(any("Refresh dm_savings_monthly" in item.value for item in app.info))

    def test_annual_and_yoy_views_render_and_weight_rates(self):
        history = pd.DataFrame({
            "billing_month": ["2025-01", "2025-02", "2025-03", "2026-01", "2026-03"],
            "billed_cost": [100, 9999, 200, 120, 240],
            "effective_cost": [100, 9999, 200, 120, 240],
            "list_cost": [125, 9999, 250, 150, 300],
            "savings_vs_list": [25, 0, 50, 30, 60],
            "charge_lines": [10, 10, 20, 12, 24],
        })
        with (patch.object(DatabricksDataSource, "healthcheck"),
              patch.object(DatabricksDataSource, "query", side_effect=lambda _: history.copy())):
            # Enter Annual before the rerun to avoid requiring monthly-only fixture columns.
            app = AppTest.from_file(str(APP / "app.py"), default_timeout=30)
            app.session_state["overview_view"] = "Annual"
            app.run()
            self.assertFalse(app.exception)
            self.assertEqual(app.metric[0].value, "360,00 €")
            self.assertEqual(app.metric[3].value, "20,00 %")
            self.assertEqual(app.metric[2].label, "Savings vs. Catalog Price")
            self.assertEqual(app.metric[2].value, "90,00 €")
            self.assertEqual(list(app.dataframe[0].value.columns), [
                "Billing Month", "Billed Cost", "Effective Cost",
                "List Cost", "Savings vs. Catalog Price", "Charge Lines",
            ])
            app.sidebar.selectbox(key="overview_view").set_value("Year-over-year").run()
            self.assertFalse(app.exception)
            self.assertEqual(app.metric[0].delta, "+20,00 % YoY")
            self.assertIn("01, 03", app.info[0].value)


if __name__ == "__main__":
    unittest.main()
