from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from finops_cloud.config import load_config  # noqa: E402
from finops_cloud.storage.discover_daily import (  # noqa: E402
    DailyFile,
    list_parquet_files,
    normalize_source_uri,
    parse_daily_uri,
    select_daily_file,
)


class _FileInfo:
    def __init__(self, path: str, directory: bool = False):
        self.path = path
        self._directory = directory

    def isDir(self):
        return self._directory


class DailyDiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.config = load_config("dev", ROOT)

    def test_normalizes_gcs_and_databricks_volume_paths(self):
        expected = (
            "/Volumes/finops_raw/landing/focus/daily/2026/07/2026-07-01.parquet"
        )
        self.assertEqual(
            normalize_source_uri(
                "gs://dtl_finops/focus/daily/2026/07/2026-07-01.parquet",
                self.config,
            ),
            expected,
        )
        self.assertEqual(
            normalize_source_uri(f"dbfs:{expected}", self.config),
            expected,
        )

    def test_parses_only_the_confirmed_daily_layout(self):
        uri, day, month = parse_daily_uri(
            "/Volumes/finops_raw/landing/focus/daily/2026/07/2026-07-19.parquet",
            self.config,
        )
        self.assertTrue(uri.endswith("/daily/2026/07/2026-07-19.parquet"))
        self.assertEqual(day, "2026-07-19")
        self.assertEqual(month, "2026-07")
        with self.assertRaisesRegex(ValueError, "partitions disagree"):
            parse_daily_uri(
                "/Volumes/finops_raw/landing/focus/daily/2026/08/2026-07-19.parquet",
                self.config,
            )

    def test_recursively_lists_only_parquet_files(self):
        tree = {
            "/root/": [
                _FileInfo("/root/2026/", True),
                _FileInfo("/root/readme.txt"),
            ],
            "/root/2026/": [
                _FileInfo("/root/2026/a.parquet"),
                _FileInfo("/root/2026/b.PARQUET"),
            ],
        }
        self.assertEqual(
            list_parquet_files("/root", lambda path: tree[path]),
            ["/root/2026/a.parquet", "/root/2026/b.PARQUET"],
        )

    def test_selects_oldest_new_file_and_allows_explicit_idempotent_rerun(self):
        items = [
            DailyFile("/daily/2026/07/2026-07-01.parquet", "2026-07-01", "2026-07", "LOADED"),
            DailyFile("/daily/2026/07/2026-07-03.parquet", "2026-07-03", "2026-07", "NEW"),
            DailyFile("/daily/2026/07/2026-07-02.parquet", "2026-07-02", "2026-07", "NEW"),
        ]
        selected = select_daily_file(items, config=self.config)
        self.assertEqual(selected.processing_date, "2026-07-02")
        rerun = select_daily_file(
            items,
            source_uri_override="/daily/2026/07/2026-07-01.parquet",
            config=self.config,
        )
        self.assertEqual(rerun.status, "LOADED")

    def test_refuses_an_explicit_closed_month(self):
        items = [
            DailyFile("/daily/2026/06/2026-06-30.parquet", "2026-06-30", "2026-06", "CLOSED")
        ]
        with self.assertRaisesRegex(ValueError, "closed month"):
            select_daily_file(
                items,
                source_uri_override="/daily/2026/06/2026-06-30.parquet",
                config=self.config,
            )


if __name__ == "__main__":
    unittest.main()
