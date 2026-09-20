from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from finops_cloud.archive import _move_one  # noqa: E402
from finops_cloud.config import load_config  # noqa: E402


class FakeBlob:
    def __init__(self, name, generation="1", crc32c="crc", size=10, exists=True):
        self.name = name
        self.generation = generation
        self.crc32c = crc32c
        self.size = size
        self._exists = exists
        self.deleted = False

    def exists(self):
        return self._exists

    def reload(self):
        return None

    def delete(self, if_generation_match=None):
        if str(if_generation_match) != str(self.generation):
            raise AssertionError("generation precondition was not applied")
        self.deleted = True


class FakeBucket:
    name = "dtl_finops"

    def __init__(self):
        self.objects = {}

    def blob(self, name):
        return self.objects.setdefault(name, FakeBlob(name, exists=False))

    def copy_blob(self, source, bucket, new_name, **conditions):
        if conditions != {
            "if_generation_match": 0,
            "if_source_generation_match": source.generation,
        }:
            raise AssertionError("copy preconditions were not applied")
        copied = FakeBlob(
            new_name,
            generation="99",
            crc32c=source.crc32c,
            size=source.size,
        )
        self.objects[new_name] = copied
        return copied


class ArchiveLayoutTests(unittest.TestCase):
    def test_archive_preserves_dataset_partition_layout(self):
        config = load_config("dev", ROOT)
        self.assertEqual(
            config.daily_gcs_month_prefix("2025-01"),
            "focus/daily/year=2025/month=01/",
        )
        self.assertEqual(
            config.billing_gcs_object("2025-01"),
            "focus/monthly/year=2025/month=01/billing-2025-01.parquet",
        )

    def test_corrected_billing_is_archived_as_a_revision(self):
        bucket = FakeBucket()
        destination = (
            "focus_archive/monthly/year=2025/month=01/billing-2025-01.parquet"
        )
        bucket.objects[destination] = FakeBlob(destination, crc32c="old", size=9)
        source = FakeBlob(
            "focus/monthly/year=2025/month=01/billing-2025-01.parquet",
            generation="42",
            crc32c="new",
            size=10,
        )
        result = _move_one(bucket, source, destination)
        self.assertEqual(
            result["archive_uri"],
            "gs://dtl_finops/focus_archive/monthly/year=2025/month=01/"
            "revision=42/billing-2025-01.parquet",
        )
        self.assertTrue(source.deleted)


if __name__ == "__main__":
    unittest.main()
