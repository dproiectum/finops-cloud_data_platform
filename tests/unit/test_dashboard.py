import os
import sqlite3
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
        for path in APP.rglob("*.py"):
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

    def test_service_query_aggregates_before_top_n_limit(self):
        sql = queries.services(DashboardConfig.from_environment(), "2026-06", 30)
        self.assertIn("GROUP BY service_name", sql)
        self.assertNotIn("GROUP BY service_category", sql)
        self.assertIn("SUM(total_billed_cost)", sql)
        self.assertIn("LIMIT 30", sql)

    def test_cost_centers_normalize_missing_labels_without_losing_signed_costs(self):
        config = DashboardConfig.from_environment()
        sql = queries.cost_centers(config, '2026-06').replace(
            config.datamart('dm_cost_by_scope_service_month'), 'source'
        )
        with sqlite3.connect(':memory:') as connection:
            connection.execute('CREATE TABLE source (billing_month TEXT, cost_center TEXT, total_billed_cost REAL)')
            connection.executemany('INSERT INTO source VALUES (?,?,?)', [
                ('2026-06', None, 100), ('2026-06', '', 20),
                ('2026-06', ' Unknown ', -5), ('2026-06', 'Unallocated', 2),
                ('2026-06', 'No Cost Center Assigned', 3),
                ('2026-06', 'CostCenter_APAC', 40), ('2026-05', None, 999),
            ])
            self.assertEqual(connection.execute(sql).fetchall(), [
                ('Unallocated Costs', 120), ('CostCenter_APAC', 40),
            ])

    def test_charge_queries_do_not_require_an_invented_attribute(self):
        sql = queries.charge_types(DashboardConfig.from_environment(), '2026-06')
        self.assertNotIn('charge_subcategory', sql)
        self.assertIn('charge_category, charge_frequency', sql)
        knowledge = (APP / 'knowledge.py').read_text(encoding='utf-8')
        self.assertIn('Unallocated Costs', knowledge)
        self.assertIn('not a Reservation/Savings Plan indicator', knowledge)

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
        self.assertIn("List Cost − Effective Cost", content)
        self.assertIn("Month-over-Month Change", content)
        self.assertIn("Effective Cost Breakdown", content)
        self.assertIn("Reservation + Savings Plan + Usage On-Demand + Usage Dynamic + Adjustment", content)
        self.assertNotIn("Commitment difference", content)

    def test_savings_queries_allow_a_rolling_datamart_update(self):
        config = DashboardConfig.from_environment()
        sql = queries.monthly_savings(config)
        self.assertIn("SELECT *, total_savings_vs_list AS total_savings", sql)
        self.assertIn("`finops_prod`.`datamart`.`dm_savings_monthly`", sql)
        self.assertNotIn("silver", sql)
        self.assertNotIn("commitment_savings", queries.savings_summary(config, "2026-01"))

    def test_app_uses_managed_warehouse_resource_without_token(self):
        manifest = (APP / "app.yaml").read_text(encoding="utf-8")
        adapter = (APP / "data_access.py").read_text(encoding="utf-8")
        self.assertIn("valueFrom: sql-warehouse", manifest)
        self.assertIn("DATABRICKS_WAREHOUSE_ID", adapter)
        self.assertNotIn("DATABRICKS_TOKEN", manifest)


if __name__ == "__main__":
    unittest.main()
