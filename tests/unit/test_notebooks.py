import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]


class NotebookTests(unittest.TestCase):
    def test_notebooks_are_clean_and_valid(self):
        notebooks = sorted((ROOT / "notebooks").rglob("*.ipynb"))
        self.assertEqual(len(notebooks), 8)
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
            "pipelines/01_daily_incremental.ipynb": "finops_cloud.pipelines.daily_incremental import run",
            "pipelines/02_monthly_close.ipynb": "finops_cloud.pipelines.monthly_close import run",
            "pipelines/03_billing_backfill.ipynb": "finops_cloud.pipelines.billing_backfill import run",
            "operations/archive_retry.ipynb": "finops_cloud.pipelines.archive_retry import run",
            "pipelines/00_all_monthly_to_gold.ipynb": "finops_cloud.pipelines.billing_backfill import run",
        }
        for name, import_line in expected.items():
            content = (ROOT / "notebooks" / name).read_text(encoding="utf-8")
            self.assertIn(import_line, content)

    def test_bundle_jobs_use_git_python_scripts(self):
        jobs = (ROOT / "resources/jobs.yml").read_text(encoding="utf-8")
        self.assertEqual(jobs.count("spark_python_task:"), 4)
        self.assertEqual(jobs.count("source: GIT"), 4)
        self.assertEqual(jobs.count("git_source:"), 4)
        self.assertNotIn("notebook_task:", jobs)
        self.assertNotIn("python_wheel_task:", jobs)
        self.assertIn(
            "default: /Volumes/finops_dev/raw/focus/daily/2025/01/2025-01-01.parquet",
            jobs,
        )

    def test_python_script_entry_points_call_maintained_modules(self):
        expected = {
            "run_daily_incremental.py": "finops_cloud.pipelines.daily_incremental import main",
            "run_monthly_close.py": "finops_cloud.pipelines.monthly_close import main",
            "run_billing_backfill.py": "finops_cloud.pipelines.billing_backfill import main",
            "run_archive_retry.py": "finops_cloud.pipelines.archive_retry import main",
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
