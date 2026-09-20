"""Common metadata and canonical Silver preparation."""

from __future__ import annotations


def add_ingestion_metadata(frame, run_id: str, source_type: str, data_status: str):
    """Add source lineage, run, ingestion-time, and provisional/final metadata."""
    from pyspark.sql import functions as F

    return (
        # Unity Catalog/serverless exposes the source path through the hidden
        # file metadata column; input_file_name() is not supported there.
        frame.withColumn("_source_file", F.col("_metadata.file_path"))
        .withColumn("_source_type", F.lit(source_type))
        .withColumn("_ingestion_run_id", F.lit(run_id))
        .withColumn("_ingested_at", F.current_timestamp())
        .withColumn("_data_status", F.lit(data_status))
    )


def prepare_canonical(frame, contract_version: str):
    """Add canonical Silver columns after Data Contract validation succeeds."""
    from pyspark.sql import functions as F

    # These columns make month filtering and contract lineage explicit.
    return (
        frame.withColumn(
            "billing_month",
            F.date_format(F.col("BillingPeriodStart"), "yyyy-MM"),
        )
        .withColumn("_contract_version", F.lit(contract_version))
    )


def month_frame(frame, month: str):
    """Filter a canonical DataFrame to one YYYY-MM billing period."""
    from pyspark.sql import functions as F

    return frame.filter(
        F.date_format(F.col("BillingPeriodStart"), "yyyy-MM") == F.lit(month)
    )


def assert_month_is_open(spark, config, frame) -> None:
    """Prevent daily data from modifying months already closed by billing."""
    from pyspark.sql import functions as F

    # A monthly billing close makes that month immutable to later daily loads.
    status_table = config.table("month_status", "ops")
    if not spark.catalog.tableExists(status_table):
        return
    months = frame.select(
        F.date_format(F.col("BillingPeriodStart"), "yyyy-MM").alias("billing_month")
    ).distinct()
    closed = (
        months.join(spark.table(status_table), on="billing_month", how="inner")
        .where(
            F.col("status").isin(
                "CLOSED",
                "CLOSED_DATA_LOADED",
                "CLOSED_ARCHIVE_PENDING",
            )
        )
        .select("billing_month")
        .collect()
    )
    if closed:
        values = [row["billing_month"] for row in closed]
        raise ValueError(f"Daily data targets already closed months: {values}")
