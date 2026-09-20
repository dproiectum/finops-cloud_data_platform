"""Databricks Python script entry point for the billing backfill pipeline."""

from pathlib import Path
import sys


SOURCE_ROOT = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SOURCE_ROOT))

from finops_cloud.pipelines.billing_backfill import main  # noqa: E402


if __name__ == "__main__":
    main()
