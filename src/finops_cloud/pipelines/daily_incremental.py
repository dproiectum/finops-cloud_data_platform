"""Incrementally ingest new daily FOCUS Parquets into an open month."""

from __future__ import annotations

import argparse
import json

from finops_cloud.audit.runs import finish_run, set_month_status, start_run
from finops_cloud.audit.snapshots import ensure_audit_tables
from finops_cloud.config import load_config
from finops_cloud.medallion.bronze import add_ingestion_metadata
from finops_cloud.medallion.contract import apply_focus_contract
from finops_cloud.medallion.delta import append_new_source_files
from finops_cloud.medallion.gold import refresh_gold_for_month
from finops_cloud.medallion.silver import (
    assert_month_is_open,
    month_frame,
    prepare_canonical,
)
from finops_cloud.runtime import ensure_schemas, get_spark


def run(environment: str, source_uri: str) -> dict[str, object]:
    """Process one daily Parquet through Bronze, Silver, Gold, and datamarts."""
    if not source_uri:
        raise ValueError("source_uri is required")

    # 1. Load environment-specific settings and verify platform objects.
    config = load_config(environment)
    spark = get_spark(config.profile)
    ensure_schemas(spark, config)
    ensure_audit_tables(spark, config)

    # One run identifier links all data writes and audit records produced below.
    run_id = start_run(spark, config, "daily_incremental")
    try:
        # 2. Bronze keeps source columns and adds technical ingestion metadata.
        raw = spark.read.parquet(source_uri)
        bronze = add_ingestion_metadata(raw, run_id, "DAILY", "PROVISIONAL")
        bronze_rows = append_new_source_files(
            spark,
            bronze,
            config.table("bronze_daily", "bronze"),
        )

        # 3. The Data Contract validates types and mandatory business fields.
        validated = apply_focus_contract(
            bronze,
            config.contract_path,
            config.currency,
            config.provider,
        )

        # 4. Silver is the canonical FOCUS dataset for downstream consumers.
        canonical = prepare_canonical(validated, config.contract_version)
        assert_month_is_open(spark, config, canonical)
        silver_rows = append_new_source_files(
            spark,
            canonical,
            config.table("silver_canonical", "silver"),
        )
        append_new_source_files(
            spark,
            canonical,
            config.table("silver_central", "silver"),
        )

        # 5. Refresh affected months in Gold, then rebuild the datamarts.
        months = [row["billing_month"] for row in canonical.select("billing_month").distinct().collect()]
        silver_table = config.table("silver_canonical", "silver")
        for month in months:
            complete_month = month_frame(spark.table(silver_table), month)
            refresh_gold_for_month(spark, config, complete_month, month)
            set_month_status(spark, config, month, "OPEN", "DAILY", run_id)
        finish_run(spark, config, run_id, "SUCCESS")
        return {
            "run_id": run_id,
            "bronze_rows_written": bronze_rows,
            "silver_rows_written": silver_rows,
            "months": sorted(months),
        }
    except Exception as exc:
        finish_run(spark, config, run_id, "FAILED", str(exc))
        raise


def main() -> None:
    """Parse Python Script Task arguments and run the daily pipeline."""
    # Databricks Jobs passes these values as command-line parameters.
    parser = argparse.ArgumentParser()
    parser.add_argument("--environment", choices=("dev", "prod"), required=True)
    parser.add_argument("--source-uri", required=True)
    args = parser.parse_args()
    print(json.dumps(run(args.environment, args.source_uri), indent=2))


if __name__ == "__main__":
    main()
