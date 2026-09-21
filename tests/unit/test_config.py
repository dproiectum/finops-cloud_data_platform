import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from finops_cloud.config import load_config  # noqa: E402


class ConfigTests(unittest.TestCase):
    def test_dev_configuration_and_paths(self):
        config = load_config("dev", ROOT)
        self.assertEqual(config.catalog, "finops_dev")
        self.assertEqual(config.raw_catalog, "finops_raw")
        self.assertEqual(config.raw_schema, "landing")
        self.assertEqual(config.schema("ops"), "finops_ops.audit")
        self.assertEqual(
            config.table("month_snapshot", "ops"),
            "finops_ops.audit.month_snapshot",
        )
        self.assertEqual(
            config.daily_volume_uri("2026-07-19"),
            "/Volumes/finops_raw/landing/focus/daily/year=2026/month=07/day=19/focus-2026-07-19.parquet",
        )
        self.assertEqual(
            config.billing_volume_uri("2026-07"),
            "/Volumes/finops_raw/landing/focus/monthly/billing-2026-07.parquet",
        )
        self.assertEqual(
            config.daily_gcs_month_prefix("2026-07"),
            "focus/daily/year=2026/month=07/",
        )
        self.assertEqual(
            config.billing_gcs_object("2026-07"),
            "focus/monthly/billing-2026-07.parquet",
        )
        self.assertEqual(
            config.table("silver_canonical", "silver"),
            "finops_dev.silver.focus_cost_usage",
        )
        self.assertEqual(config.focus_version, "1.0")
        self.assertEqual(
            config.table("dm_cost_by_application_owner_month", "datamart"),
            "finops_dev.datamart.dm_cost_by_application_owner_month",
        )

    def test_non_secret_environment_overrides(self):
        with patch.dict(
            os.environ,
            {
                "FINOPS_CATALOG": "custom_dev",
                "FINOPS_GCS_BUCKET": "custom_bucket",
                "FINOPS_OPERATIONS_CATALOG": "custom_ops",
                "FINOPS_OPERATIONS_SCHEMA": "history",
                "FINOPS_RAW_CATALOG": "custom_raw",
                "FINOPS_RAW_SCHEMA": "source",
            },
        ):
            config = load_config("dev", ROOT)
        self.assertEqual(config.catalog, "custom_dev")
        self.assertEqual(config.gcs_bucket, "custom_bucket")
        self.assertEqual(config.schema("ops"), "custom_ops.history")
        self.assertEqual(config.raw_catalog, "custom_raw")
        self.assertEqual(config.raw_schema, "source")

    def test_dev_and_prod_use_same_raw_and_operations_namespaces(self):
        dev = load_config("dev", ROOT)
        prod = load_config("prod", ROOT)
        self.assertNotEqual(dev.catalog, prod.catalog)
        self.assertEqual(dev.schema("ops"), "finops_ops.audit")
        self.assertEqual(prod.schema("ops"), "finops_ops.audit")
        self.assertEqual(dev.source_volume, prod.source_volume)
        self.assertEqual(dev.source_volume, "/Volumes/finops_raw/landing/focus")
        self.assertFalse(dev.archive_daily)
        self.assertFalse(dev.archive_billing)


if __name__ == "__main__":
    unittest.main()
