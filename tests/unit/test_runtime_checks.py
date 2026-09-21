from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from finops_cloud.audit.snapshots import ensure_audit_tables  # noqa: E402
from finops_cloud.runtime import ensure_schemas  # noqa: E402


class FakeSpark:
    def __init__(self):
        self.queries = []

    def sql(self, query):
        self.queries.append(query)


class FakeConfig:
    raw_catalog = "finops_raw"
    raw_schema = "landing"
    catalog = "finops_dev"
    operations_catalog = "finops_ops"
    operations_schema = "audit"
    schemas = {
        "bronze": "bronze",
        "silver": "silver",
        "gold": "gold",
        "datamart": "datamart",
    }
    tables = {
        "pipeline_run": "pipeline_run",
        "month_snapshot": "month_snapshot",
        "reconciliation": "monthly_reconciliation",
        "month_status": "month_status",
        "file_archive": "file_archive",
    }

    def table(self, key, layer):
        self.assert_ops(layer)
        return f"finops_ops.audit.{self.tables[key]}"

    @staticmethod
    def assert_ops(layer):
        if layer != "ops":
            raise AssertionError(f"Unexpected layer: {layer}")


class RuntimeCheckTests(unittest.TestCase):
    def test_schema_check_describes_every_required_namespace(self):
        spark = FakeSpark()
        ensure_schemas(spark, FakeConfig())
        self.assertEqual(len(spark.queries), 6)
        self.assertTrue(all(query.startswith("DESCRIBE SCHEMA") for query in spark.queries))

    def test_audit_check_never_creates_tables_implicitly(self):
        spark = FakeSpark()
        ensure_audit_tables(spark, FakeConfig())
        self.assertEqual(len(spark.queries), 5)
        self.assertTrue(all(query.startswith("DESCRIBE TABLE") for query in spark.queries))
        self.assertFalse(any("CREATE TABLE" in query for query in spark.queries))


if __name__ == "__main__":
    unittest.main()
