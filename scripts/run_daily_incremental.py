"""Databricks Python script entry point for the daily incremental pipeline."""

from pathlib import Path
import sys


SOURCE_ROOT = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SOURCE_ROOT))

from finops_cloud.pipelines.daily_incremental import main  # noqa: E402


if __name__ == "__main__":
    main()
