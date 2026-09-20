from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from finops_cloud.pipelines.billing_backfill import month_range  # noqa: E402


class BackfillTests(unittest.TestCase):
    def test_inclusive_month_range_across_year(self):
        self.assertEqual(
            month_range("2025-11", "2026-02"),
            ["2025-11", "2025-12", "2026-01", "2026-02"],
        )

    def test_reversed_range_is_refused(self):
        with self.assertRaises(ValueError):
            month_range("2026-02", "2025-11")


if __name__ == "__main__":
    unittest.main()
