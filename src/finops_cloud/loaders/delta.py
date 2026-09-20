"""Small Delta primitives used by all pipeline entry points."""

from __future__ import annotations

import re
from uuid import uuid4


def table_exists(spark, table_name: str) -> bool:
    return bool(spark.catalog.tableExists(table_name))


def append_new_source_files(spark, frame, table_name: str) -> int:
    """Append only source files that have not already reached the target."""
    if "_source_file" not in frame.columns:
        raise ValueError("_source_file is required for idempotent ingestion")
    candidate = frame
    if table_exists(spark, table_name):
        existing = spark.table(table_name).select("_source_file").distinct()
        candidate_files = frame.select("_source_file").distinct().join(
            existing,
            on="_source_file",
            how="left_anti",
        )
        candidate = frame.join(candidate_files, on="_source_file", how="inner")
    if candidate.limit(1).count() == 0:
        return 0
    rows = candidate.count()
    (
        candidate.write.format("delta")
        .mode("append")
        .option("mergeSchema", "true")
        .saveAsTable(table_name)
    )
    return rows


def append_frame(frame, table_name: str) -> int:
    if frame.limit(1).count() == 0:
        return 0
    rows = frame.count()
    (
        frame.write.format("delta")
        .mode("append")
        .option("mergeSchema", "true")
        .saveAsTable(table_name)
    )
    return rows


def _safe_view(prefix: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_]", "_", f"{prefix}_{uuid4().hex}")


def align_to_target(spark, frame, table_name: str):
    if not table_exists(spark, table_name):
        return frame
    target_fields = spark.table(table_name).schema.fields
    source_columns = set(frame.columns)
    missing = [field.name for field in target_fields if field.name not in source_columns]
    extra = [name for name in frame.columns if name not in {f.name for f in target_fields}]
    if missing or extra:
        raise ValueError(
            f"Schema differs from {table_name}; missing={missing}, extra={extra}. "
            "Apply an explicit schema migration before closing the month."
        )
    return frame.select(*[field.name for field in target_fields])


def replace_month(spark, frame, table_name: str, month: str) -> int:
    """Atomically replace a billing month in a Delta table."""
    if frame.limit(1).count() == 0:
        raise ValueError("Refusing to replace a month with an empty dataset")
    rows = frame.count()
    if not table_exists(spark, table_name):
        frame.write.format("delta").mode("errorifexists").saveAsTable(table_name)
        return rows

    aligned = align_to_target(spark, frame, table_name)
    view_name = _safe_view("billing_month")
    aligned.createOrReplaceTempView(view_name)
    month_start = f"{month}-01"
    try:
        spark.sql(
            f"""
            INSERT INTO TABLE {table_name}
            REPLACE WHERE BillingPeriodStart = DATE '{month_start}'
            SELECT * FROM {view_name}
            """
        )
    finally:
        spark.catalog.dropTempView(view_name)
    return rows


def delta_version(spark, table_name: str) -> int | None:
    if not table_exists(spark, table_name):
        return None
    row = spark.sql(f"DESCRIBE HISTORY {table_name} LIMIT 1").first()
    return int(row["version"]) if row is not None else None
