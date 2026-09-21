"""Reconcile daily data with billing and atomically replace the month."""

from __future__ import annotations

import argparse
import json
import re

from finops_cloud.audit.runs import finish_run, set_month_status, start_run
from finops_cloud.audit.snapshots import (
    capture_frame_state,
    ensure_audit_tables,
    write_reconciliation,
    write_snapshot,
)
from finops_cloud.config import load_config
from finops_cloud.medallion.bronze import add_ingestion_metadata
from finops_cloud.medallion.contract import apply_focus_contract, validate_single_month
from finops_cloud.medallion.delta import (
    append_new_source_files,
    delta_version,
    replace_month,
    table_exists,
)
from finops_cloud.medallion.gold import refresh_gold_for_month
from finops_cloud.medallion.silver import (
    month_frame,
    prepare_canonical,
)
from finops_cloud.runtime import ensure_schemas, get_spark
from finops_cloud.storage.archive import archive_month, write_archive_audit


def _validate_month(month: str) -> None:
    """Require a safe YYYY-MM monthly-close parameter."""
    if not re.fullmatch(r"[0-9]{4}-(0[1-9]|1[0-2])", month):
        raise ValueError("month must use YYYY-MM")


def _month_status(spark, config, month: str) -> str | None:
    """Read the latest processing status for a billing month, when present."""
    table = config.table("month_status", "ops")
    rows = (
        spark.table(table)
        .where(
            f"environment = '{config.environment}' AND billing_month = '{month}'"
        )
        .select("status")
        .take(1)
    )
    return rows[0]["status"] if rows else None


def _archive_only(spark, config, month: str, run_id: str) -> dict[str, object]:
    """Resume only archival after data loading previously completed."""
    records = archive_month(config, month)
    write_archive_audit(spark, config, run_id, month, records)
    set_month_status(spark, config, month, "CLOSED", "MONTHLY_BILLING", run_id)
    finish_run(spark, config, run_id, "SUCCESS", "Archive retry completed")
    return {"run_id": run_id, "month": month, "archive_objects": len(records), "archive_only": True}


def run(
    environment: str,
    month: str,
    source_uri: str | None = None,
    archive: bool = False,
) -> dict[str, object]:
    """Replace one month with billing data and optionally archive sources."""
    _validate_month(month)

    # 1. Prepare configuration, Spark, schemas, audit tables, and run tracking.
    config = load_config(environment)
    spark = get_spark(config.profile)
    ensure_schemas(spark, config)
    ensure_audit_tables(spark, config)
    run_id = start_run(spark, config, "monthly_close", month)
    archive_enabled = archive and (config.archive_daily or config.archive_billing)

    # If loading succeeded previously, retry only the failed archive operation.
    if archive_enabled and _month_status(spark, config, month) == "CLOSED_ARCHIVE_PENDING":
        try:
            return _archive_only(spark, config, month, run_id)
        except Exception as exc:
            finish_run(spark, config, run_id, "ARCHIVE_PENDING", str(exc))
            raise

    source = source_uri or config.billing_volume_uri(month)
    try:
        # 2. Land the authoritative monthly billing file in Bronze.
        raw = spark.read.parquet(source)
        bronze = add_ingestion_metadata(raw, run_id, "MONTHLY_BILLING", "FINAL")
        bronze_rows = append_new_source_files(
            spark,
            bronze,
            config.table("bronze_billing", "bronze"),
        )

        # 3. Enforce the Data Contract before entering canonical Silver.
        validated = apply_focus_contract(
            bronze,
            config.contract_path,
            config.currency,
            config.provider,
        )
        validate_single_month(validated, month)
        candidate = prepare_canonical(validated, config.contract_version)

        # 4. Capture DAILY and BILLING states before replacing the month.
        silver_table = config.table("silver_canonical", "silver")
        before_version = delta_version(spark, silver_table)
        before_frame = (
            month_frame(spark.table(silver_table), month)
            if table_exists(spark, silver_table)
            else candidate.limit(0)
        )
        before = capture_frame_state(
            before_frame,
            run_id=run_id,
            pipeline_name="monthly_close",
            environment=config.environment,
            month=month,
            stage="BEFORE",
            source_type="DAILY",
            delta_version=before_version,
        )
        billing = capture_frame_state(
            candidate,
            run_id=run_id,
            pipeline_name="monthly_close",
            environment=config.environment,
            month=month,
            stage="SOURCE",
            source_type="MONTHLY_BILLING",
        )
        write_snapshot(spark, config, before)
        write_snapshot(spark, config, billing)
        set_month_status(spark, config, month, "RECONCILING", "DAILY", run_id)

        # 5. Atomically replace the provisional daily month in both Silver tables.
        replace_month(spark, candidate, silver_table, month)
        replace_month(
            spark,
            candidate,
            config.table("silver_central", "silver"),
            month,
        )

        # 6. Verify that the stored result exactly matches the billing source.
        after_version = delta_version(spark, silver_table)
        after_frame = month_frame(spark.table(silver_table), month)
        after = capture_frame_state(
            after_frame,
            run_id=run_id,
            pipeline_name="monthly_close",
            environment=config.environment,
            month=month,
            stage="AFTER",
            source_type="MONTHLY_BILLING",
            delta_version=after_version,
        )
        write_snapshot(spark, config, after)
        write_reconciliation(spark, config, run_id, month, before, billing, after)

        # 7. Refresh the dimensional Gold model and certified datamarts.
        refresh_gold_for_month(spark, config, after_frame, month)
        set_month_status(spark, config, month, "CLOSED_DATA_LOADED", "MONTHLY_BILLING", run_id)

        archive_objects = 0
        if archive_enabled:
            # 8. Move processed source objects only after the data load succeeds.
            try:
                records = archive_month(config, month)
                write_archive_audit(spark, config, run_id, month, records)
                archive_objects = len(records)
            except Exception as archive_error:
                set_month_status(
                    spark,
                    config,
                    month,
                    "CLOSED_ARCHIVE_PENDING",
                    "MONTHLY_BILLING",
                    run_id,
                )
                finish_run(spark, config, run_id, "ARCHIVE_PENDING", str(archive_error))
                raise

        final_status = "CLOSED" if archive_enabled else "CLOSED_DATA_LOADED"
        set_month_status(spark, config, month, final_status, "MONTHLY_BILLING", run_id)
        finish_run(spark, config, run_id, "SUCCESS")
        return {
            "run_id": run_id,
            "month": month,
            "bronze_rows_written": bronze_rows,
            "before_rows": before["row_count"],
            "billing_rows": billing["row_count"],
            "after_rows": after["row_count"],
            "billing_daily_difference": str(
                billing["billed_cost_total"] - before["billed_cost_total"]
            ),
            "archive_objects": archive_objects,
            "status": final_status,
        }
    except Exception as exc:
        current = _month_status(spark, config, month)
        if current != "CLOSED_ARCHIVE_PENDING":
            finish_run(spark, config, run_id, "FAILED", str(exc))
        raise


def main() -> None:
    """Parse Python Script Task arguments and run the monthly-close pipeline."""
    # Databricks Jobs passes these values as command-line parameters.
    parser = argparse.ArgumentParser()
    parser.add_argument("--environment", choices=("dev", "prod"), required=True)
    parser.add_argument("--month", required=True)
    parser.add_argument("--source-uri")
    parser.add_argument("--archive", action="store_true")
    args = parser.parse_args()
    result = run(
        args.environment,
        args.month,
        source_uri=args.source_uri,
        archive=args.archive,
    )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
