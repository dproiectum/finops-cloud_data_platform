"""Before/source/after snapshots for monthly billing replacement."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any


SNAPSHOT_SCHEMA = """
run_id string,
pipeline_name string,
environment string,
billing_month string,
capture_stage string,
source_type string,
row_count long,
billed_cost_total decimal(38,6),
effective_cost_total decimal(38,6),
list_cost_total decimal(38,6),
distinct_accounts long,
distinct_resources long,
duplicate_charge_ids long,
null_critical_count long,
min_charge_period timestamp,
max_charge_period timestamp,
delta_table_version long,
captured_at timestamp
"""


def ensure_audit_tables(spark, config) -> None:
    """Fail clearly when a manually provisioned operations table is absent."""
    for key in (
        "pipeline_run",
        "month_snapshot",
        "reconciliation",
        "month_status",
        "file_archive",
    ):
        spark.sql(f"DESCRIBE TABLE {config.table(key, 'ops')}")


def capture_frame_state(
    frame,
    *,
    run_id: str,
    pipeline_name: str,
    environment: str,
    month: str,
    stage: str,
    source_type: str,
    delta_version: int | None = None,
) -> dict[str, Any]:
    """Calculate reproducible row, cost, quality, and date metrics for a stage."""
    from pyspark.sql import functions as F

    columns = set(frame.columns)

    # Optional metrics return typed defaults so older schemas remain measurable.

    def amount(column: str):
        """Return a decimal sum expression or a typed null when unavailable."""
        if column in columns:
            return F.sum(F.col(column).cast("decimal(38,6)"))
        return F.lit(None).cast("decimal(38,6)")

    def distinct(column: str):
        """Return a distinct-count expression or zero when unavailable."""
        if column in columns:
            return F.countDistinct(F.col(column))
        return F.lit(0).cast("long")

    def timestamp_metric(column: str, function):
        """Apply a timestamp aggregation or return a typed null expression."""
        if column in columns:
            return function(F.col(column).cast("timestamp"))
        return F.lit(None).cast("timestamp")

    critical = [
        name
        for name in (
            "BilledCost",
            "BillingCurrency",
            "BillingPeriodStart",
            "ChargePeriodStart",
            "ProviderName",
        )
        if name in columns
    ]
    if critical:
        null_expression = sum(
            (F.when(F.col(name).isNull(), F.lit(1)).otherwise(F.lit(0)) for name in critical),
            F.lit(0),
        )
        null_metric = F.sum(null_expression).cast("long")
    else:
        null_metric = F.lit(0).cast("long")

    row = frame.agg(
        F.count(F.lit(1)).alias("row_count"),
        amount("BilledCost").alias("billed_cost_total"),
        amount("EffectiveCost").alias("effective_cost_total"),
        amount("ListCost").alias("list_cost_total"),
        distinct("BillingAccountId").alias("distinct_accounts"),
        distinct("ResourceId").alias("distinct_resources"),
        null_metric.alias("null_critical_count"),
        timestamp_metric("ChargePeriodStart", F.min).alias("min_charge_period"),
        timestamp_metric("ChargePeriodEnd", F.max).alias("max_charge_period"),
    ).first()

    # Duplicate charge IDs are useful but are not present in every source.
    duplicate_charge_ids = 0
    if "x_ChargeId" in columns:
        duplicate_charge_ids = (
            frame.where(F.col("x_ChargeId").isNotNull())
            .groupBy("x_ChargeId")
            .count()
            .where(F.col("count") > 1)
            .count()
        )
    return {
        "run_id": run_id,
        "pipeline_name": pipeline_name,
        "environment": environment,
        "billing_month": month,
        "capture_stage": stage,
        "source_type": source_type,
        "row_count": int(row["row_count"]),
        "billed_cost_total": row["billed_cost_total"] or Decimal("0"),
        "effective_cost_total": row["effective_cost_total"] or Decimal("0"),
        "list_cost_total": row["list_cost_total"] or Decimal("0"),
        "distinct_accounts": int(row["distinct_accounts"]),
        "distinct_resources": int(row["distinct_resources"]),
        "duplicate_charge_ids": int(duplicate_charge_ids),
        "null_critical_count": int(row["null_critical_count"] or 0),
        "min_charge_period": row["min_charge_period"],
        "max_charge_period": row["max_charge_period"],
        "delta_table_version": delta_version,
        "captured_at": datetime.now(timezone.utc).replace(tzinfo=None),
    }


def write_snapshot(spark, config, snapshot: dict[str, Any]) -> None:
    """Append one BEFORE, SOURCE, or AFTER metric snapshot to Delta."""
    # Parse by line so decimal(38,6) remains one type declaration.
    ordered = [
        line.strip().rstrip(",").split()[0]
        for line in SNAPSHOT_SCHEMA.strip().splitlines()
        if line.strip()
    ]
    values = tuple(snapshot[name] for name in ordered)
    spark.createDataFrame([values], SNAPSHOT_SCHEMA).write.mode("append").saveAsTable(
        config.table("month_snapshot", "ops")
    )


def write_reconciliation(spark, config, run_id, month, before, source, after) -> str:
    """Persist and enforce the technical reconciliation after monthly replace."""
    billed_difference = source["billed_cost_total"] - before["billed_cost_total"]
    technical_difference = after["billed_cost_total"] - source["billed_cost_total"]
    # Replacement passes only when stored rows match the authoritative source.
    passed = (
        after["row_count"] == source["row_count"]
        and abs(technical_difference) < Decimal(config.amount_tolerance)
        and after["null_critical_count"] == 0
    )
    status = "PASSED" if passed else "FAILED"
    schema = """
      run_id string, environment string, billing_month string,
      before_rows long, billing_rows long, after_rows long,
      before_billed_cost decimal(38,6), billing_billed_cost decimal(38,6),
      after_billed_cost decimal(38,6), billing_daily_difference decimal(38,6),
      after_billing_difference decimal(38,6), status string, reconciled_at timestamp
    """
    values = (
        run_id,
        config.environment,
        month,
        before["row_count"],
        source["row_count"],
        after["row_count"],
        before["billed_cost_total"],
        source["billed_cost_total"],
        after["billed_cost_total"],
        billed_difference,
        technical_difference,
        status,
        datetime.now(timezone.utc).replace(tzinfo=None),
    )
    spark.createDataFrame([values], schema).write.mode("append").saveAsTable(
        config.table("reconciliation", "ops")
    )
    if not passed:
        raise ValueError("Post-load reconciliation failed")
    return status
