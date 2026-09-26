from pathlib import Path
import sys
import tomllib
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from finops_cloud.config import load_config  # noqa: E402
from finops_cloud.medallion.gold import (  # noqa: E402
    DATAMART_SCRIPTS,
    GOLD_DDL,
    GOLD_LOAD_SCRIPTS,
)
from finops_cloud.sql.runner import (  # noqa: E402
    placeholders,
    render_sql,
    sql_text,
    table_context,
)


def platform_text(relative_path: str) -> str:
    return (ROOT / "platform" / relative_path).read_text(encoding="utf-8")


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

    def test_operations_sql_is_environment_aware_in_both_scenarios(self):
        for relative_path in (
            "serverless/sql/04_create_ops.sql",
            "classic_compute/sql/04_create_ops.sql",
        ):
            with self.subTest(relative_path=relative_path):
                setup = platform_text(relative_path)
                self.assertEqual(placeholders(setup), set())
                self.assertEqual(setup.count("environment STRING"), 5)
                self.assertIn("CREATE CATALOG IF NOT EXISTS `finops_ops`", setup)
                self.assertEqual(setup.count("`finops_ops`.`audit`."), 5)

    def test_monthly_fact_load_replaces_instead_of_appending(self):
        fact_load = sql_text("gold/data_loading/30_replace_fact_month.sql")
        self.assertIn("REPLACE WHERE billing_month = '{billing_month}'", fact_load)

    def test_all_datamarts_are_rebuilt_instead_of_appended(self):
        for relative_path in DATAMART_SCRIPTS:
            self.assertIn("CREATE OR REPLACE TABLE", sql_text(relative_path))

    def test_full_reset_drops_exactly_the_four_project_catalogs(self):
        reset = sql_text("controls/00_drop_all_project_catalogs.sql")
        for catalog in ("finops_raw", "finops_dev", "finops_prod", "finops_ops"):
            self.assertIn(f"DROP CATALOG IF EXISTS `{catalog}` CASCADE", reset)
        self.assertEqual(reset.count("DROP CATALOG IF EXISTS"), 4)
        for protected in ("main", "system", "samples"):
            self.assertNotIn(f"DROP CATALOG IF EXISTS `{protected}`", reset)

    def test_platform_tree_has_three_unambiguous_themes(self):
        expected = {
            "serverless/sql": [
                "01_create_raw.sql",
                "02_create_dev.sql",
                "03_create_prod.sql",
                "04_create_ops.sql",
            ],
            "classic_compute/sql": [
                "00_validate_managed_storage.sql",
                "01_create_raw.sql",
                "02_create_dev.sql",
                "03_create_prod.sql",
                "04_create_ops.sql",
            ],
            "common/sql/controls": [
                "00_drop_all_project_catalogs.sql",
                "01_validate_empty_platform.sql",
                "02_validate_loaded_dev.sql",
                "03_validate_prod_ready.sql",
                "04_validate_loaded_prod.sql",
            ],
        }
        for directory, filenames in expected.items():
            with self.subTest(directory=directory):
                scripts = sorted((ROOT / "platform" / directory).glob("*.sql"))
                self.assertEqual([path.name for path in scripts], filenames)

        self.assertFalse((ROOT / "sql").exists())

    def test_raw_setups_verify_the_same_registered_volume_locations(self):
        for relative_path in (
            "serverless/sql/01_create_raw.sql",
            "classic_compute/sql/01_create_raw.sql",
        ):
            with self.subTest(relative_path=relative_path):
                raw_setup = platform_text(relative_path)
                self.assertIn("DESCRIBE VOLUME `finops_raw`.`landing`.`focus`", raw_setup)
                self.assertIn("LIST '/Volumes/finops_raw/landing/focus/monthly'", raw_setup)

    def test_classic_catalogs_have_managed_gcs_locations(self):
        for script, catalog in (
            ("01_create_raw.sql", "finops_raw"),
            ("02_create_dev.sql", "finops_dev"),
            ("03_create_prod.sql", "finops_prod"),
            ("04_create_ops.sql", "finops_ops"),
        ):
            setup = platform_text(f"classic_compute/sql/{script}")
            self.assertIn(
                f"CREATE CATALOG IF NOT EXISTS `{catalog}`\n"
                "MANAGED LOCATION "
                f"'gs://dtl_finops-unitycatalog-euw1/catalogs/{catalog}'",
                setup,
            )

    def test_serverless_catalogs_rely_on_default_storage(self):
        for script in (
            "01_create_raw.sql",
            "02_create_dev.sql",
            "03_create_prod.sql",
            "04_create_ops.sql",
        ):
            with self.subTest(script=script):
                setup = platform_text(f"serverless/sql/{script}")
                self.assertNotIn("MANAGED LOCATION", setup)

    def test_classic_preflight_registers_only_the_managed_data_bucket(self):
        preflight = platform_text("classic_compute/sql/00_validate_managed_storage.sql")
        self.assertIn("WITH (STORAGE CREDENTIAL `finops_uc_storage_be`)", preflight)
        self.assertIn("CREATE EXTERNAL LOCATION IF NOT EXISTS `finops_uc_managed_be`", preflight)
        self.assertIn("gs://dtl_finops-unitycatalog-euw1", preflight)
        self.assertNotIn("gs://dtl_finops/focus", preflight)

    def test_dev_and_prod_create_the_same_processing_schemas(self):
        for directory in ("serverless/sql", "classic_compute/sql"):
            dev = platform_text(f"{directory}/02_create_dev.sql")
            prod = platform_text(f"{directory}/03_create_prod.sql")
            for schema in ("bronze", "silver", "gold", "datamart"):
                self.assertIn(f"`finops_dev`.`{schema}`", dev)
                self.assertIn(f"`finops_prod`.`{schema}`", prod)

    def test_empty_platform_validation_checks_all_sixty_business_tables(self):
        validation = sql_text("controls/01_validate_empty_platform.sql")
        self.assertEqual(validation.count("SELECT 'finops_dev."), 30)
        self.assertEqual(validation.count("SELECT 'finops_prod."), 30)

    def test_loaded_validation_contains_blocking_job_assertions(self):
        validation = sql_text("controls/02_validate_loaded_dev.sql")
        self.assertGreaterEqual(validation.count("assert_true("), 7)
        self.assertIn("CONTROL FAILED: PROD is no longer empty", validation)

    def test_prod_preflight_is_empty_and_environment_scoped(self):
        preflight = sql_text("controls/03_validate_prod_ready.sql")
        self.assertIn("30-table inventory", preflight)
        self.assertGreaterEqual(preflight.count("assert_true("), 3)
        self.assertIn("environment = 'prod'", preflight)
        self.assertNotIn("DROP CATALOG", preflight)

    def test_prod_loaded_validation_has_blocking_controls(self):
        validation = sql_text("controls/04_validate_loaded_prod.sql")
        self.assertGreaterEqual(validation.count("assert_true("), 8)
        self.assertIn("latest PROD pipeline run is not successful", validation)
        self.assertIn("PROD Silver still contains a null ServiceName", validation)
        self.assertIn("environment = 'prod'", validation)
        self.assertNotIn("`finops_dev`", validation)

    def test_wheel_configuration_embeds_only_common_runtime_sql(self):
        with (ROOT / "pyproject.toml").open("rb") as stream:
            project = tomllib.load(stream)
        data_files = project["tool"]["setuptools"]["data-files"]
        self.assertEqual(data_files["share/finops_cloud/config"], ["config/*.toml"])
        self.assertEqual(
            data_files["share/finops_cloud/contracts/focus_cost_usage/v1.0.0"],
            ["contracts/focus_cost_usage/v1.0.0/*.yaml"],
        )
        self.assertEqual(
            data_files["share/finops_cloud/sql"],
            ["platform/common/sql/README.md"],
        )
        self.assertEqual(
            data_files["share/finops_cloud/sql/controls"],
            ["platform/common/sql/controls/*.sql"],
        )
        self.assertEqual(
            data_files["share/finops_cloud/sql/gold/table_creation"],
            ["platform/common/sql/gold/table_creation/*.sql"],
        )
        self.assertEqual(
            data_files["share/finops_cloud/sql/gold/data_loading"],
            ["platform/common/sql/gold/data_loading/*.sql"],
        )
        self.assertEqual(
            data_files["share/finops_cloud/sql/datamarts/table_refresh"],
            ["platform/common/sql/datamarts/table_refresh/*.sql"],
        )
        self.assertNotIn("share/finops_cloud/sql/platform_setup_serverless", data_files)
        self.assertNotIn("share/finops_cloud/sql/platform_setup_classic_be", data_files)


if __name__ == "__main__":
    unittest.main()
