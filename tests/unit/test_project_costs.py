"""Project-cost publication, numeric correctness and offline page tests."""

from decimal import Decimal
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import pandas as pd
from streamlit.testing.v1 import AppTest

APP = Path(__file__).resolve().parents[2] / "apps/finops_dashboard"
sys.path.insert(0, str(APP))

from project_costs.model import amount, load_snapshot, provider_total, validate_records
from project_costs.publish_snapshot import build_payload, read_aggregate_csv
from project_costs.view import cost_trend
from about import PAGE_GUIDE, TECH_STACK


def row(provider="GCP", **changes):
    result = dict(month="2026-09", provider=provider, service="Cloud Run",
                  currency="EUR", cost_before_credits="1234.5678", credits="-100.25",
                  usage_quantity=None, usage_unit="", cost_basis="billing_export",
                  period_status="partial")
    if provider == "Databricks":
        result.update(service="PREMIUM_ALL_PURPOSE_COMPUTE", currency="USD",
                      credits=None, usage_quantity="10.1234", usage_unit="DBU",
                      cost_basis="list_estimate")
    return {**result, **changes}


class ProjectCostTests(unittest.TestCase):
    def test_missing_snapshot_is_unavailable_not_zero(self):
        as_of, frame = load_snapshot()
        self.assertIsNone(as_of)
        self.assertTrue(frame.empty)
        self.assertIsNone(provider_total(frame, "GCP", "reported_cost"))
        self.assertEqual(amount(None, "EUR"), "—")

    def test_signed_credits_and_full_precision(self):
        frame = validate_records([row(), row(service="Compute Engine", cost_before_credits="-2", credits="0")])
        self.assertEqual(frame.iloc[0]["reported_cost"], Decimal("1134.3178"))
        self.assertEqual(provider_total(frame, "GCP", "reported_cost"), Decimal("1132.3178"))
        self.assertEqual(amount(Decimal("1234.5678"), "EUR"), "1\u202f234,57 EUR")
        self.assertEqual(amount(-2, "USD"), "-2,00 USD")
        self.assertIsNone(provider_total(frame, "Databricks", "reported_cost"))

    def test_real_zero_remains_zero(self):
        frame = validate_records([row(cost_before_credits="0", credits="0")])
        self.assertEqual(amount(provider_total(frame, "GCP", "reported_cost"), "EUR"), "0,00 EUR")

    def test_rejects_missing_prices_nan_infinity_and_localized_input(self):
        for value in (None, "", "NaN", "Infinity", "1 234,56"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_records([row("Databricks", cost_before_credits=value)])

    def test_no_raw_identifiers_or_duplicate_monthly_keys(self):
        for changes in ({"workspace_id": "private"}, {"service": "user@example.com"},
                        {"service": "gs://private/bucket"}, {"month": "2026-13"},
                        {"cost_basis": "paid_invoice"}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                validate_records([row(**changes)])
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            validate_records([row(), row()])

    def test_mixed_units_and_fake_databricks_credits_are_refused(self):
        for record in (row(usage_quantity="123", usage_unit="Hours"),
                       row("Databricks", usage_unit="Hours"),
                       row("Databricks", credits="0")):
            with self.subTest(record=record), self.assertRaises(ValueError):
                validate_records([record])

    def test_approval_gate_and_extra_metadata_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "snapshot.json"
            payload = build_payload([row()], "2026-10-07")
            payload["approved_for_publication"] = False
            path.write_text(json.dumps(payload))
            self.assertTrue(load_snapshot(path)[1].empty)
            payload["approved_for_publication"] = True
            payload["project_id"] = "private"
            path.write_text(json.dumps(payload))
            with self.assertRaises(ValueError):
                load_snapshot(path)
            path.write_text("[]")
            with self.assertRaises(ValueError):
                load_snapshot(path)

    def test_publisher_round_trip_and_allowlisted_csv(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "snapshot.json"
            payload = build_payload([row(), row("Databricks")], "2026-10-07")
            path.write_text(json.dumps(payload))
            as_of, frame = load_snapshot(path)
            self.assertEqual(as_of, "2026-10-07")
            self.assertEqual(len(frame), 2)
            self.assertIn("1234.5678", path.read_text())
            csv_path = Path(directory) / "raw.csv"
            csv_path.write_text("project_id,cost\nprivate,12\n")
            with self.assertRaises(ValueError):
                read_aggregate_csv(csv_path)

    def test_chart_does_not_stack_cost_bases_or_fill_missing_months(self):
        frame = validate_records([row(), row("Databricks", currency="EUR")])
        figure = cost_trend(frame, "EUR")
        self.assertEqual(figure.layout.barmode, "group")
        self.assertEqual(list(figure.data[0].x), ["2026-09"])
        self.assertIn("List Cost Estimate", figure.data[1].name)
        self.assertIn("1\u202f134,32 EUR", figure.data[0].customdata[0])

    def test_page_renders_without_costs_and_without_live_billing_access(self):
        prefix = f"import sys\nsys.path.insert(0, {str(APP)!r})\n"
        app = AppTest.from_string(prefix + "from project_costs.view import render_project_costs\nrender_project_costs()\n").run()
        self.assertFalse(app.exception)
        self.assertEqual(len(app.metric), 0)
        self.assertIn("not zero", app.info[0].value)

    def test_currency_filters_keep_unavailable_provider_and_european_numbers(self):
        frame = validate_records([row(), row("Databricks")])
        prefix = f"import sys\nsys.path.insert(0, {str(APP)!r})\n"
        with patch("project_costs.view.load_snapshot", return_value=("2026-10-07", frame)):
            app = AppTest.from_string(prefix + "from project_costs.view import render_project_costs\nrender_project_costs()\n").run()
            self.assertFalse(app.exception)
            self.assertEqual(app.metric[1].value, "1\u202f134,32 EUR")
            self.assertEqual(app.metric[3].value, "—")
            app.selectbox(key="project_cost_currency").select("USD").run()
            self.assertFalse(app.exception)
            self.assertEqual(app.metric[1].value, "—")
            self.assertEqual(app.metric[2].value, "10,12")
            self.assertEqual(app.metric[3].value, "1\u202f234,57 USD")
            self.assertNotIn("Combined Total", [metric.label for metric in app.metric])

    def test_about_guide_and_stack_are_complete(self):
        self.assertNotIn("Project Costs", [page for page, _ in PAGE_GUIDE])
        self.assertIn("About the Project", [page for page, _ in PAGE_GUIDE])
        self.assertIn("About Me", [page for page, _ in PAGE_GUIDE])
        self.assertEqual(len({page for page, _ in PAGE_GUIDE}), len(PAGE_GUIDE))
        self.assertTrue(any("PySpark" in technology for _, technology, _ in TECH_STACK))
        prefix = f"import sys\nsys.path.insert(0, {str(APP)!r})\n"
        app = AppTest.from_string(prefix + "from about import render_about\nrender_about()\n").run()
        self.assertFalse(app.exception)
        self.assertEqual(app.title[0].value, "About the Project")
        self.assertEqual([tab.label for tab in app.tabs[:4]],
                         ["Overview", "Page Guide", "Technology Stack", "Project Costs"])
        self.assertEqual(len(app.title), 1)
        self.assertIn("not zero", app.tabs[3].info[0].value)
        self.assertTrue(any("Project Costs tab" in purpose for _, purpose in PAGE_GUIDE))
        self.assertTrue(any("synthetic" in text.value for text in app.markdown))

    def test_about_author_profile_and_contact(self):
        prefix = f"import sys\nsys.path.insert(0, {str(APP)!r})\n"
        app = AppTest.from_string(prefix + "from about import render_about_me\nrender_about_me()\n").run()
        self.assertFalse(app.exception)
        self.assertEqual(app.title[0].value, "About Me")
        self.assertFalse(app.tabs)
        author_text = "\n".join(text.value for text in app.markdown)
        self.assertIn("I am an engineer", author_text)
        for phrase in ("performance and efficiency", "design of the system itself",
                       "a form of value creation", "learning across disciplines"):
            self.assertIn(phrase, author_text)
        self.assertNotIn("final-year", author_text)
        self.assertNotIn("student", author_text)
        self.assertIn("[lumos@allops.cloud](mailto:lumos@allops.cloud)", author_text)
        self.assertNotIn("not a personal biography", "\n".join(text.value for text in app.markdown))


if __name__ == "__main__":
    unittest.main()
