"""Databricks Python script entry point for a pending GCS archive retry."""

from pathlib import Path
import sys


# Make the repository's src/ package importable when Databricks runs this file.
SOURCE_ROOT = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SOURCE_ROOT))

from finops_cloud.pipelines.archive_retry import main  # noqa: E402


# Keep this entry point thin: business logic belongs in src/ and remains testable.
if __name__ == "__main__":
    main()
