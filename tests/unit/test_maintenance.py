from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from finops_cloud.config import load_config  # noqa: E402
from finops_cloud.maintenance import all_tables_empty, project_tables  # noqa: E402


class MaintenanceTests(unittest.TestCase):
    def test_registry_covers_every_configured_table(self):
        config = load_config("dev", ROOT)
        tables = project_tables(config)
        self.assertEqual({key for _layer, key, _table in tables}, set(config.tables))
        self.assertEqual(tables[0][0], "datamart")
        self.assertEqual(tables[-1][0], "ops")

    def test_missing_and_empty_tables_are_safe(self):
        states = [
            {"exists": False, "is_empty": True},
            {"exists": True, "is_empty": True},
        ]
        self.assertTrue(all_tables_empty(states))
        states.append({"exists": True, "is_empty": False})
        self.assertFalse(all_tables_empty(states))


if __name__ == "__main__":
    unittest.main()
