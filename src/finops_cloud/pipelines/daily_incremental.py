"""Incrementally ingest new daily FOCUS Parquets into an open month."""

from __future__ import annotations

import argparse
import json

from finops_cloud.audit_runs import finish_run, set_month_status, start_run
from finops_cloud.audit_snapshots import ensure_audit_tables
from finops_cloud.config import load_config
from finops_cloud.contract import apply_focus_contract
from finops_cloud.delta import append_new_source_files
from finops_cloud.gold import refresh_gold_for_month
from finops_cloud.runtime import ensure_schemas, get_spark
from finops_cloud.silver import (
    add_ingestion_metadata,
    assert_month_is_open,
    month_frame,
    prepare_canonical,
)


def run(environment: str, source_uri: str) -> dict[str, object]:
    """Process one daily Parquet through Bronze, Silver, Gold, and datamarts."""
    if not source_uri:
        raise ValueError("source_uri is required")
    config = load_config(environment)
    spark = get_spark(config.profile)
    ensure_schemas(spark, config)
    ensure_audit_tables(spark, config)
    run_id = start_run(spark, config, "daily_incremental")
    try:
        raw = spark.read.parquet(source_uri)
        bronze = add_ingestion_metadata(raw, run_id, "DAILY", "PROVISIONAL")
        bronze_rows = append_new_source_files(
            spark,
            bronze,
            config.table("bronze_daily", "bronze"),
        )
        validated = apply_focus_contract(
            bronze,
            config.contract_path,
            config.currency,
            config.provider,
        )
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
    parser = argparse.ArgumentParser()
    parser.add_argument("--environment", choices=("dev", "prod"), required=True)
    parser.add_argument("--source-uri", required=True)
    args = parser.parse_args()
    print(json.dumps(run(args.environment, args.source_uri), indent=2))


if __name__ == "__main__":
    main()
