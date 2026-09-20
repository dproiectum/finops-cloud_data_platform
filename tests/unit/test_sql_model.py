from pathlib import Path
import sys
import tomllib
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from finops_cloud.config import load_config  # noqa: E402
from finops_cloud.sql_runner import placeholders, render_sql, sql_text, table_context  # noqa: E402
from finops_cloud.gold import (  # noqa: E402
    DATAMART_SCRIPTS,
    GOLD_DDL,
    GOLD_LOAD_SCRIPTS,
)


class SqlModelTests(unittest.TestCase):
    def setUp(self):
        self.config = load_config("dev", ROOT)
        self.context = table_context(self.config)

    def test_complete_poc_model_is_declared(self):
        ddl = sql_text(GOLD_DDL)
        self.assertEqual(ddl.count("CREATE TABLE IF NOT EXISTS"), 12)
        for key in (
            "dim_date",
            "dim_billing_scope",
            "dim_resource",
            "dim_service",
            "dim_sku",
            "dim_location",
            "dim_commitment_discount",
            "dim_pricing",
            "dim_charge_type",
            "dim_tag",
            "bridge_resource_tag",
            "fact_cost_usage",
        ):
            self.assertIn("{" + key + "}", ddl)

    def test_fourteen_datamarts_are_packaged_and_renderable(self):
        self.assertEqual(len(DATAMART_SCRIPTS), 14)
        for relative_path in DATAMART_SCRIPTS:
            rendered = render_sql(relative_path, self.context)
            self.assertIn("CREATE OR REPLACE TABLE", rendered)
            self.assertEqual(placeholders(rendered), set())

    def test_gold_sql_is_packaged_and_renderable(self):
        values = {
            **self.context,
            "source_month": "source_month_view",
            "billing_month": "2026-07",
            "focus_version": self.config.focus_version,
        }
        for relative_path in (GOLD_DDL, *GOLD_LOAD_SCRIPTS):
            rendered = render_sql(relative_path, values)
            self.assertEqual(placeholders(rendered), set())
        fact_sql = render_sql(GOLD_LOAD_SCRIPTS[-1], values)
        self.assertIn("REPLACE WHERE billing_month = '2026-07'", fact_sql)

    def test_wheel_configuration_embeds_root_sql_directories(self):
        with (ROOT / "pyproject.toml").open("rb") as stream:
            project = tomllib.load(stream)
        data_files = project["tool"]["setuptools"]["data-files"]
        self.assertEqual(data_files["share/finops_cloud/config"], ["config/*.toml"])
        self.assertEqual(
            data_files["share/finops_cloud/contracts/focus_cost_usage/v1.0.0"],
            ["contracts/focus_cost_usage/v1.0.0/*.yaml"],
        )
        self.assertEqual(
            data_files["share/finops_cloud/sql/gold/table_creation"],
            ["sql/gold/table_creation/*.sql"],
        )
        self.assertEqual(
            data_files["share/finops_cloud/sql/gold/data_loading"],
            ["sql/gold/data_loading/*.sql"],
        )
        self.assertEqual(
            data_files["share/finops_cloud/sql/datamarts/table_refresh"],
            ["sql/datamarts/table_refresh/*.sql"],
        )


if __name__ == "__main__":
    unittest.main()
