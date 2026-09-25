"""Blocking reconciliation controls for one daily DEV or PROD ingestion."""

from __future__ import annotations

from decimal import Decimal
from typing import Any


def _require_table(spark, table_name: str) -> None:
    if not spark.catalog.tableExists(table_name):
        raise ValueError(f"Required daily-control table is missing: {table_name}")


def _measure(frame, amount_column: str) -> tuple[int, Decimal]:
    from pyspark.sql import functions as F

    row = frame.agg(
        F.count(F.lit(1)).alias("row_count"),
        F.coalesce(
            F.sum(F.col(amount_column).cast("decimal(38,6)")),
            F.lit(0).cast("decimal(38,6)"),
        ).alias("billed_cost"),
    ).first()
    return int(row["row_count"]), Decimal(row["billed_cost"])


def _month_measure(frame, month: str, amount_column: str) -> tuple[int, Decimal]:
    from pyspark.sql import functions as F

    return _measure(
        frame.where(F.col("billing_month") == F.lit(month)),
        amount_column,
    )


def validate_daily_load(spark, config, source_uri: str) -> dict[str, Any]:
    """Validate one source file from raw input through certified datamarts."""
    from pyspark.sql import functions as F

    if not source_uri:
        raise ValueError("source_uri is required for daily validation")

    raw = spark.read.parquet(source_uri)
    required_source_columns = {"BillingPeriodStart", "BilledCost"}
    missing = sorted(required_source_columns - set(raw.columns))
    if missing:
        raise ValueError(f"Daily source is missing validation columns: {missing}")

    source_with_lineage = raw.select(
        F.col("_metadata.file_path").alias("_source_file"),
        "*",
    )
    source_paths = [
        row["_source_file"]
        for row in source_with_lineage.select("_source_file").distinct().collect()
    ]
    if len(source_paths) != 1:
        raise ValueError(
            "Daily validation requires exactly one physical Parquet file; "
            f"source={source_uri}, physical_files={source_paths}"
        )

    months = [
        row["billing_month"]
        for row in source_with_lineage.select(
            F.date_format(F.to_date("BillingPeriodStart"), "yyyy-MM").alias(
                "billing_month"
            )
        )
        .distinct()
        .collect()
    ]
    if len(months) != 1 or months[0] is None:
        raise ValueError(
            "Daily validation requires exactly one billing month; "
            f"source={source_uri}, months={months}"
        )
    month = months[0]
    source_path = source_paths[0]

    tables = {
        "bronze": config.table("bronze_daily", "bronze"),
        "silver": config.table("silver_canonical", "silver"),
        "central": config.table("silver_central", "silver"),
        "gold": config.table("fact_cost_usage", "gold"),
        "monthly_dm": config.table("dm_monthly_billing", "datamart"),
        "daily_dm": config.table("dm_daily_billing", "datamart"),
        "runs": config.table("pipeline_run", "ops"),
        "month_status": config.table("month_status", "ops"),
    }
    for table_name in tables.values():
        _require_table(spark, table_name)

    source_rows, source_cost = _measure(source_with_lineage, "BilledCost")
    bronze = spark.table(tables["bronze"]).where(
        F.col("_source_file") == F.lit(source_path)
    )
    silver = spark.table(tables["silver"]).where(
        F.col("_source_file") == F.lit(source_path)
    )
    central = spark.table(tables["central"]).where(
        F.col("_source_file") == F.lit(source_path)
    )
    bronze_rows, bronze_cost = _measure(bronze, "BilledCost")
    silver_rows, silver_cost = _measure(silver, "BilledCost")
    central_rows, central_cost = _measure(central, "BilledCost")
    gold_rows, gold_cost = _month_measure(
        spark.table(tables["gold"]), month, "billed_cost"
    )
    silver_month_rows, silver_month_cost = _month_measure(
        spark.table(tables["central"]), month, "BilledCost"
    )

    tolerance = Decimal(config.amount_tolerance)
    errors: list[str] = []
    file_row_counts = {source_rows, bronze_rows, silver_rows, central_rows}
    if len(file_row_counts) != 1 or source_rows == 0:
        errors.append(
            "source/Bronze/Silver file row counts differ: "
            f"source={source_rows}, bronze={bronze_rows}, "
            f"silver={silver_rows}, central={central_rows}"
        )
    for label, value in (
        ("bronze", bronze_cost),
        ("silver", silver_cost),
        ("central", central_cost),
    ):
        if abs(value - source_cost) >= tolerance:
            errors.append(
                f"source/{label} file billed cost differs: "
                f"source={source_cost}, {label}={value}"
            )
    if silver_month_rows != gold_rows:
        errors.append(
            "Silver/Gold month row counts differ: "
            f"silver={silver_month_rows}, gold={gold_rows}"
        )
    if abs(silver_month_cost - gold_cost) >= tolerance:
        errors.append(
            "Silver/Gold month billed cost differs: "
            f"silver={silver_month_cost}, gold={gold_cost}"
        )

    duplicate_source_runs = (
        bronze.select("_ingestion_run_id").distinct().count()
        if bronze_rows
        else 0
    )
    if duplicate_source_runs != 1:
        errors.append(
            "one source must belong to exactly one Bronze ingestion run: "
            f"distinct_runs={duplicate_source_runs}"
        )

    duplicate_gold_keys = (
        spark.table(tables["gold"])
        .where(F.col("billing_month") == F.lit(month))
        .groupBy("cost_usage_sk")
        .count()
        .where(F.col("count") > 1)
        .count()
    )
    if duplicate_gold_keys:
        errors.append(f"Gold contains {duplicate_gold_keys} duplicate fact keys")

    latest_run = (
        spark.table(tables["runs"])
        .where(F.col("environment") == F.lit(config.environment))
        .where(F.col("pipeline_name") == F.lit("daily_incremental"))
        .where(F.col("billing_month") == F.lit(month))
        .orderBy(F.col("started_at").desc())
        .first()
    )
    if latest_run is None or latest_run["status"] != "SUCCESS":
        errors.append("latest daily_incremental run for the month is not SUCCESS")

    status = (
        spark.table(tables["month_status"])
        .where(F.col("environment") == F.lit(config.environment))
        .where(F.col("billing_month") == F.lit(month))
        .orderBy(F.col("updated_at").desc())
        .first()
    )
    if (
        status is None
        or status["status"] != "OPEN"
        or status["authoritative_source"] != "DAILY"
    ):
        errors.append("month status is not OPEN with authoritative source DAILY")

    monthly_dm = spark.table(tables["monthly_dm"]).where(
        F.col("billing_month") == F.lit(month)
    )
    monthly_dm_rows = monthly_dm.count()
    if monthly_dm_rows != 1:
        errors.append(
            f"monthly billing datamart must contain one row for {month}: "
            f"rows={monthly_dm_rows}"
        )
    elif abs(Decimal(monthly_dm.first()["monthly_billed_cost"]) - gold_cost) >= tolerance:
        errors.append("monthly billing datamart cost differs from Gold")

    daily_dm_rows = (
        spark.table(tables["daily_dm"])
        .where(F.date_format(F.col("date"), "yyyy-MM") == F.lit(month))
        .count()
    )
    if daily_dm_rows == 0:
        errors.append(f"daily billing datamart has no row for {month}")

    comparison: dict[str, Any] = {}
    if config.environment == "prod":
        from finops_cloud.config import load_config

        dev_config = load_config("dev")
        dev_gold_table = dev_config.table("fact_cost_usage", "gold")
        _require_table(spark, dev_gold_table)
        dev_rows, dev_cost = _month_measure(
            spark.table(dev_gold_table), month, "billed_cost"
        )
        comparison = {"dev_gold_rows": dev_rows, "dev_gold_billed_cost": dev_cost}
        if dev_rows != gold_rows or abs(dev_cost - gold_cost) >= tolerance:
            errors.append(
                "DEV/PROD Gold month differs: "
                f"dev_rows={dev_rows}, prod_rows={gold_rows}, "
                f"dev_cost={dev_cost}, prod_cost={gold_cost}"
            )

    result = {
        "environment": config.environment,
        "source_uri": source_uri,
        "physical_source_file": source_path,
        "billing_month": month,
        "source_rows": source_rows,
        "bronze_rows": bronze_rows,
        "silver_rows": silver_rows,
        "central_rows": central_rows,
        "silver_month_rows": silver_month_rows,
        "gold_month_rows": gold_rows,
        "source_billed_cost": source_cost,
        "silver_month_billed_cost": silver_month_cost,
        "gold_month_billed_cost": gold_cost,
        "daily_datamart_rows": daily_dm_rows,
        "status": "PASSED" if not errors else "FAILED",
        **comparison,
    }
    if errors:
        details = "\n - ".join(errors)
        raise ValueError(
            "Daily load validation failed; no promotion is allowed:\n - " + details
        )
    return result
