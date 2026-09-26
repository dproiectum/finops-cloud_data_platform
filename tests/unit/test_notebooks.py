import json
from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[2]
COMMON_NOTEBOOKS = ROOT / "platform/common/notebooks"
CLASSIC_NOTEBOOKS = ROOT / "platform/classic_compute/notebooks"


class NotebookTests(unittest.TestCase):
    def test_notebooks_are_clean_valid_and_platform_scoped(self):
        notebooks = sorted((ROOT / "platform").rglob("*.ipynb"))
        self.assertEqual(len(notebooks), 8)
        self.assertFalse((ROOT / "notebooks").exists())
        for path in notebooks:
            notebook = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(notebook["nbformat"], 4)
            for index, cell in enumerate(notebook["cells"]):
                if cell["cell_type"] == "code":
                    self.assertIsNone(cell["execution_count"])
                    self.assertEqual(cell["outputs"], [])
                    compile(
                        "".join(cell["source"]),
                        f"{path}:cell-{index}",
                        "exec",
                    )

    def test_pipeline_notebooks_call_maintained_job_modules(self):
        expected = {
            "pipelines/01_daily_incremental.ipynb": (
                "finops_cloud.pipelines.daily_incremental import run"
            ),
            "pipelines/02_monthly_close.ipynb": "finops_cloud.pipelines.monthly_close import run",
            "pipelines/03_billing_backfill.ipynb": (
                "import finops_cloud.pipelines.billing_backfill as billing_backfill_module"
            ),
        }
        for name, import_line in expected.items():
            content = (COMMON_NOTEBOOKS / name).read_text(encoding="utf-8")
            self.assertIn(import_line, content)

    def test_daily_operation_notebooks_call_maintained_modules(self):
        expected = {
            "operations/discover_daily_files.ipynb": (
                "finops_cloud.storage.discover_daily import inventory_daily_files, "
                "select_daily_file"
            ),
            "operations/validate_daily_load.ipynb": (
                "finops_cloud.audit.daily_controls import validate_daily_load"
            ),
        }
        for name, import_line in expected.items():
            content = (COMMON_NOTEBOOKS / name).read_text(encoding="utf-8")
            self.assertIn(import_line, content)

    def test_classic_validation_notebook_forces_common_sql_assertions(self):
        content = (
            CLASSIC_NOTEBOOKS / "validate_loaded_environment_classic.ipynb"
        ).read_text(encoding="utf-8")
        self.assertIn("controls/02_validate_loaded_dev.sql", content)
        self.assertIn("controls/04_validate_loaded_prod.sql", content)
        self.assertIn("rows = result.collect()", content)

    def test_environment_check_verifies_raw_and_operations_objects(self):
        content = (COMMON_NOTEBOOKS / "operations/environment_check.ipynb").read_text(
            encoding="utf-8"
        )
        self.assertIn("ensure_audit_tables", content)
        self.assertIn("SHOW VOLUMES IN", content)
        self.assertIn("SHOW TABLES IN", content)
        self.assertIn("/monthly", content)

    def test_empty_table_initialization_is_explicit_and_calls_maintained_code(self):
        content = (
            COMMON_NOTEBOOKS / "operations/initialize_empty_data_tables.ipynb"
        ).read_text(encoding="utf-8")
        self.assertIn(
            "finops_cloud.medallion.initialize import initialize_empty_tables",
            content,
        )
        self.assertIn("CREATE_EMPTY_TABLES", content)
        self.assertIn('ENVIRONMENT = \\"dev\\"', content)
        self.assertNotIn("_create_empty_table =", content)

    def test_manual_monthly_notebooks_do_not_offer_archival(self):
        for name in (
            "pipelines/02_monthly_close.ipynb",
            "pipelines/03_billing_backfill.ipynb",
        ):
            content = (COMMON_NOTEBOOKS / name).read_text(encoding="utf-8")
            self.assertNotIn('widgets.dropdown(\\"archive\\"', content)
            self.assertNotIn("ARCHIVE =", content)

    def test_bundle_jobs_use_git_python_scripts(self):
        jobs = (ROOT / "platform/serverless/jobs/pipeline_jobs.yml").read_text(
            encoding="utf-8"
        )
        self.assertEqual(jobs.count("spark_python_task:"), 3)
        self.assertEqual(jobs.count("source: GIT"), 3)
        self.assertEqual(jobs.count("git_source:"), 3)
        self.assertEqual(jobs.count("max_concurrent_runs: 1"), 3)
        self.assertNotIn("notebook_task:", jobs)
        self.assertNotIn("python_wheel_task:", jobs)
        self.assertIn(
            "default: /Volumes/finops_raw/landing/focus/daily/2026/07/2026-07-01.parquet",
            jobs,
        )

    def test_manual_full_load_jobs_match_their_compute_scenarios(self):
        serverless = (
            ROOT / "platform/serverless/jobs/billing_full_load_by_month.yml"
        ).read_text(encoding="utf-8")
        classic = (
            ROOT
            / "platform/classic_compute/jobs/billing-dev-full_load_by_month-no_photon.yml"
        ).read_text(encoding="utf-8")

        self.assertIn("sql_task:", serverless)
        self.assertIn("warehouse_id: 81cb90d52797f414", serverless)
        self.assertNotIn("existing_cluster_id:", serverless)
        self.assertNotIn("sql_task:", classic)
        self.assertEqual(classic.count("existing_cluster_id: 5925-212130-elwuj3uu"), 3)
        self.assertIn("validate_loaded_environment_classic", classic)

        for content in (serverless, classic):
            notebook_paths = re.findall(
                r"notebook_path: .*/finops-cloud_data_platform/(.+)", content
            )
            sql_paths = re.findall(r"path: .*/finops-cloud_data_platform/(.+\.sql)", content)
            for relative_path in notebook_paths:
                self.assertTrue((ROOT / f"{relative_path}.ipynb").is_file(), relative_path)
            for relative_path in sql_paths:
                self.assertTrue((ROOT / relative_path).is_file(), relative_path)

    def test_classic_prod_promotion_job_is_isolated_and_uses_prod_controls(self):
        prod = (
            ROOT
            / "platform/classic_compute/jobs/billing-prod-full_load_by_month-with_photon.yml"
        ).read_text(encoding="utf-8")

        self.assertIn("name: finops-prod-billing-promotion-with_photon", prod)
        self.assertIn("max_concurrent_runs: 1", prod)
        self.assertIn("task_key: check_environment_prod", prod)
        self.assertIn("task_key: load_billing_range_prod", prod)
        self.assertIn("task_key: validate_loaded_prod", prod)
        self.assertIn("default: prod", prod)
        self.assertEqual(prod.count("existing_cluster_id: 5925-212130-elwuj3uu"), 3)
        self.assertIn("validate_loaded_environment_classic", prod)
        self.assertNotIn("sql_task:", prod)

        notebook_paths = re.findall(
            r"notebook_path: .*/finops-cloud_data_platform/(.+)", prod
        )
        for relative_path in notebook_paths:
            self.assertTrue((ROOT / f"{relative_path}.ipynb").is_file(), relative_path)

    def test_classic_daily_job_gates_new_files_and_prod_promotion(self):
        daily = (
            ROOT / "platform/classic_compute/jobs/daily_dev_to_prod.yml"
        ).read_text(encoding="utf-8")

        for task_key in (
            "discover_daily_files",
            "new_file_gate",
            "check_environment_dev",
            "load_daily_dev",
            "validate_daily_dev",
            "promotion_gate",
            "check_environment_prod",
            "load_daily_prod",
            "validate_daily_prod",
        ):
            self.assertIn(f"task_key: {task_key}", daily)

        self.assertEqual(daily.count("condition_task:"), 2)
        self.assertEqual(daily.count("existing_cluster_id: 5925-212130-elwuj3uu"), 7)
        self.assertIn('left: "{{tasks.discover_daily_files.values.has_new_file}}"', daily)
        self.assertIn('left: "{{job.parameters.promote_to_prod}}"', daily)
        self.assertIn('source_uri: "{{tasks.discover_daily_files.values.source_uri}}"', daily)
        self.assertIn('environment: "{{job.parameters.discovery_environment}}"', daily)
        self.assertIn("name: discovery_environment\n          default: prod", daily)
        self.assertIn('default: "true"', daily)
        self.assertNotIn("schedule:", daily)
        self.assertNotIn("sql_task:", daily)

        notebook_paths = re.findall(
            r"notebook_path: .*/finops-cloud_data_platform/(.+)", daily
        )
        for relative_path in notebook_paths:
            self.assertTrue((ROOT / f"{relative_path}.ipynb").is_file(), relative_path)

    def test_python_script_entry_points_call_maintained_modules(self):
        expected = {
            "run_daily_incremental.py": "finops_cloud.pipelines.daily_incremental import main",
            "run_monthly_close.py": "finops_cloud.pipelines.monthly_close import main",
            "run_billing_backfill.py": "finops_cloud.pipelines.billing_backfill import main",
        }
        for name, import_line in expected.items():
            content = (ROOT / "scripts" / name).read_text(encoding="utf-8")
            self.assertIn(import_line, content)

    def test_python_script_entry_points_work_without_dunder_file(self):
        """Reproduce Databricks exec(), which does not define __file__."""
        for script in sorted((ROOT / "scripts").glob("run_*.py")):
            source = script.read_text(encoding="utf-8")
            namespace = {"__name__": "databricks_python_script_task"}
            exec(compile(source, str(script), "exec"), namespace)
            self.assertEqual(namespace["SOURCE_ROOT"], ROOT / "src")


if __name__ == "__main__":
    unittest.main()
