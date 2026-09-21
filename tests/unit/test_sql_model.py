from pathlib import Path
import sys
import tomllib
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from finops_cloud.config import load_config  # noqa: E402
from finops_cloud.sql.runner import placeholders, render_sql, sql_text, table_context  # noqa: E402
from finops_cloud.medallion.gold import (  # noqa: E402
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

    def test_operations_sql_is_environment_aware(self):
        relative_path = "platform_setup/03_create_ops.sql"
        rendered = render_sql(relative_path, {})
        self.assertEqual(placeholders(rendered), set())
        self.assertEqual(rendered.count("environment STRING"), 5)
        self.assertIn("CREATE CATALOG IF NOT EXISTS `finops_ops`", rendered)
        self.assertEqual(rendered.count("`finops_ops`.`audit`."), 5)

    def test_dev_reset_has_no_dependency_on_operations_catalog(self):
        reset = sql_text("platform_setup/00_reset_dev.sql")
        self.assertIn("DROP CATALOG IF EXISTS `finops_dev` CASCADE", reset)
        self.assertNotIn("DROP CATALOG IF EXISTS `finops_raw`", reset)
        self.assertNotIn("DROP CATALOG IF EXISTS `finops_prod`", reset)
        self.assertNotIn("`finops_ops`", reset)

        clear_ops = sql_text("platform_setup/04_clear_dev_ops.sql")
        self.assertEqual(clear_ops.count("WHERE environment = 'dev'"), 5)

    def test_platform_setup_scripts_have_an_unambiguous_order(self):
        scripts = sorted((ROOT / "sql" / "platform_setup").glob("*.sql"))
        self.assertEqual(
            [path.name for path in scripts],
            [
                "00_reset_dev.sql",
                "01_create_or_verify_raw.sql",
                "02_create_dev.sql",
                "03_create_ops.sql",
                "04_clear_dev_ops.sql",
                "05_validate_empty_dev.sql",
                "06_validate_loaded_dev.sql",
            ],
        )

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
        self.assertEqual(
            data_files["share/finops_cloud/sql/platform_setup"],
            ["sql/platform_setup/*.sql"],
        )


if __name__ == "__main__":
    unittest.main()
