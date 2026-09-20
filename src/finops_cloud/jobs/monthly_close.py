"""Reconcile daily data with billing, atomically replace the month, then archive."""

from __future__ import annotations

import argparse
import json
import re

from finops_cloud.archive.gcs_archive import archive_month, write_archive_audit
from finops_cloud.audit.month_snapshot import (
    capture_frame_state,
    ensure_audit_tables,
    write_reconciliation,
    write_snapshot,
)
from finops_cloud.audit.run_log import finish_run, set_month_status, start_run
from finops_cloud.config import load_config
from finops_cloud.loaders.delta import (
    append_new_source_files,
    delta_version,
    replace_month,
    table_exists,
)
from finops_cloud.quality.focus_contract import apply_focus_contract, validate_single_month
from finops_cloud.runtime import ensure_schemas, get_spark
from finops_cloud.transformations.gold import refresh_gold_for_month
from finops_cloud.transformations.silver import (
    add_ingestion_metadata,
    month_frame,
    prepare_canonical,
)


def _validate_month(month: str) -> None:
    if not re.fullmatch(r"[0-9]{4}-(0[1-9]|1[0-2])", month):
        raise ValueError("month must use YYYY-MM")


def _month_status(spark, config, month: str) -> str | None:
    table = config.table("month_status", "ops")
    rows = spark.table(table).where(f"billing_month = '{month}'").select("status").take(1)
    return rows[0]["status"] if rows else None


def _archive_only(spark, config, month: str, run_id: str) -> dict[str, object]:
    records = archive_month(config, month)
    write_archive_audit(spark, config, run_id, month, records)
    set_month_status(spark, config, month, "CLOSED", "MONTHLY_BILLING", run_id)
    finish_run(spark, config, run_id, "SUCCESS", "Archive retry completed")
    return {"run_id": run_id, "month": month, "archive_objects": len(records), "archive_only": True}


def run(
    environment: str,
    month: str,
    source_uri: str | None = None,
    archive: bool = True,
) -> dict[str, object]:
    _validate_month(month)
    config = load_config(environment)
    spark = get_spark(config.profile)
    ensure_schemas(spark, config)
    ensure_audit_tables(spark, config)
    run_id = start_run(spark, config, "monthly_close", month)

    if _month_status(spark, config, month) == "CLOSED_ARCHIVE_PENDING":
        try:
            return _archive_only(spark, config, month, run_id)
        except Exception as exc:
            finish_run(spark, config, run_id, "ARCHIVE_PENDING", str(exc))
            raise

    source = source_uri or config.billing_volume_uri(month)
    try:
        raw = spark.read.parquet(source)
        bronze = add_ingestion_metadata(raw, run_id, "MONTHLY_BILLING", "FINAL")
        bronze_rows = append_new_source_files(
            spark,
            bronze,
            config.table("bronze_billing", "bronze"),
        )
        validated = apply_focus_contract(
            bronze,
            config.contract_path,
            config.currency,
            config.provider,
        )
        validate_single_month(validated, month)
        candidate = prepare_canonical(validated, config.contract_version)

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
            month=month,
            stage="BEFORE",
            source_type="DAILY",
            delta_version=before_version,
        )
        billing = capture_frame_state(
            candidate,
            run_id=run_id,
            pipeline_name="monthly_close",
            month=month,
            stage="SOURCE",
            source_type="MONTHLY_BILLING",
        )
        write_snapshot(spark, config, before)
        write_snapshot(spark, config, billing)
        set_month_status(spark, config, month, "RECONCILING", "DAILY", run_id)

        replace_month(spark, candidate, silver_table, month)
        replace_month(
            spark,
            candidate,
            config.table("silver_central", "silver"),
            month,
        )
        after_version = delta_version(spark, silver_table)
        after_frame = month_frame(spark.table(silver_table), month)
        after = capture_frame_state(
            after_frame,
            run_id=run_id,
            pipeline_name="monthly_close",
            month=month,
            stage="AFTER",
            source_type="MONTHLY_BILLING",
            delta_version=after_version,
        )
        write_snapshot(spark, config, after)
        write_reconciliation(spark, config, run_id, month, before, billing, after)

        refresh_gold_for_month(spark, config, after_frame, month)
        set_month_status(spark, config, month, "CLOSED_DATA_LOADED", "MONTHLY_BILLING", run_id)

        archive_objects = 0
        if archive:
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

        final_status = "CLOSED" if archive else "CLOSED_DATA_LOADED"
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
    parser = argparse.ArgumentParser()
    parser.add_argument("--environment", choices=("dev", "prod"), required=True)
    parser.add_argument("--month", required=True)
    parser.add_argument("--source-uri")
    parser.add_argument("--no-archive", action="store_true")
    args = parser.parse_args()
    result = run(
        args.environment,
        args.month,
        source_uri=args.source_uri,
        archive=not args.no_archive,
    )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
