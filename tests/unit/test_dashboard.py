import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "apps/finops_dashboard"
sys.path.insert(0, str(APP))

from config import DashboardConfig  # noqa: E402
import queries  # noqa: E402


class DashboardTests(unittest.TestCase):
    def test_dashboard_python_files_compile(self):
        for path in APP.glob("*.py"):
            compile(path.read_text(encoding="utf-8"), str(path), "exec")

    def test_dashboard_defaults_to_prod_and_shared_ops(self):
        with patch.dict(os.environ, {}, clear=True):
            config = DashboardConfig.from_environment()
        self.assertEqual(config.environment, "prod")
        self.assertEqual(config.data_catalog, "finops_prod")
        self.assertEqual(
            config.datamart("dm_monthly_billing"),
            "`finops_prod`.`datamart`.`dm_monthly_billing`",
        )
        self.assertEqual(
            config.audit("pipeline_run"),
            "`finops_ops`.`audit`.`pipeline_run`",
        )

    def test_operations_queries_are_environment_scoped(self):
        config = DashboardConfig.from_environment()
        pipeline_sql = queries.latest_pipeline_runs(config)
        reconciliation_sql = queries.latest_reconciliations(config)
        self.assertIn("environment = 'prod'", pipeline_sql)
        self.assertIn("environment = 'prod'", reconciliation_sql)
        self.assertIn("`finops_ops`.`audit`.`pipeline_run`", pipeline_sql)

    def test_knowledge_pages_keep_columns_and_formulas(self):
        content = (APP / "knowledge.py").read_text(encoding="utf-8")
        for name in (
            "BilledCost",
            "EffectiveCost",
            "ListCost",
            "ContractedCost",
            "ServiceName",
            "_source_file",
        ):
            self.assertIn(name, content)
        self.assertIn("List cost − Effective cost", content)
        self.assertIn("Month-over-month change", content)

    def test_app_uses_managed_warehouse_resource_without_token(self):
        manifest = (APP / "app.yaml").read_text(encoding="utf-8")
        adapter = (APP / "data_access.py").read_text(encoding="utf-8")
        self.assertIn("valueFrom: sql-warehouse", manifest)
        self.assertIn("DATABRICKS_WAREHOUSE_ID", adapter)
        self.assertNotIn("DATABRICKS_TOKEN", manifest)


if __name__ == "__main__":
    unittest.main()
