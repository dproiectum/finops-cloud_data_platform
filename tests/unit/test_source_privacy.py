from pathlib import Path
import re
import sys
import unittest
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src'))
from finops_cloud.medallion.privacy import ORGANIZATION_PATTERN, assert_source_privacy, privacy_expressions


class SourcePrivacyTests(unittest.TestCase):
    def test_known_markers_and_false_positive_boundaries(self):
        for value in ['TEN Data Platform', 'AZ_TEN_Linux', 'T.EN NET', 'technipenergies.com', 'TechnipFMC']:
            self.assertIsNotNone(re.search(ORGANIZATION_PATTERN, value))
        for value in ['Tenant', 'Content', 'Data Platform', 'APP00013057', 'North Europe']:
            self.assertIsNone(re.search(ORGANIZATION_PATTERN, value))

    def test_sql_escapes_columns_and_uses_raw_regex_strings(self):
        expression = privacy_expressions(['Tags', 'column`name'])[1]
        self.assertIn('`column``name`', expression)
        self.assertIn("r'", expression)
        self.assertIn('regexp_extract_all', expression)
        self.assertIn('address -> NOT', expression)

    def test_error_is_fail_closed_without_disclosing_text(self):
        class Frame:
            schema = SimpleNamespace(fields=[SimpleNamespace(name='Tags', dataType=SimpleNamespace(simpleString=lambda: 'string'))])
            def selectExpr(self, *expressions):
                return self
            def collect(self):
                return [SimpleNamespace(asDict=lambda: {'Tags': 12})]
        with self.assertRaisesRegex(ValueError, "Tags.*12") as caught:
            assert_source_privacy(Frame(), '/Volumes/finops_raw/landing/focus/monthly/billing-2026-01.parquet')
        self.assertNotIn('TEN Data Platform', str(caught.exception))

    def test_both_ingestion_paths_check_before_bronze_append(self):
        for name in ['daily_incremental', 'monthly_close']:
            text = (ROOT / f'src/finops_cloud/pipelines/{name}.py').read_text()
            self.assertLess(text.index('assert_source_privacy(raw,'), text.index('bronze_rows = append_new_source_files('))


if __name__ == '__main__':
    unittest.main()
