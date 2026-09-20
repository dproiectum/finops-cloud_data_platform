"""Run and month-status logging."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4


RUN_SCHEMA = """
run_id string, pipeline_name string, environment string, billing_month string,
status string, started_at timestamp, finished_at timestamp, message string
"""


def utc_timestamp():
    """Return a timezone-normalized UTC timestamp accepted by Spark."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def start_run(spark, config, pipeline_name: str, month: str | None = None) -> str:
    """Create a RUNNING pipeline audit row and return its unique run ID."""
    # The run ID is propagated to data metadata and operational audits.
    run_id = uuid4().hex
    values = (
        run_id,
        pipeline_name,
        config.environment,
        month,
        "RUNNING",
        utc_timestamp(),
        None,
        None,
    )
    spark.createDataFrame([values], RUN_SCHEMA).write.mode("append").saveAsTable(
        config.table("pipeline_run", "ops")
    )
    return run_id


def finish_run(spark, config, run_id: str, status: str, message: str | None = None) -> None:
    """Finalize one pipeline audit row with status, time, and safe message."""
    escaped = (message or "").replace("'", "''")[:4000]
    spark.sql(
        f"""
        UPDATE {config.table('pipeline_run', 'ops')}
        SET status = '{status}', finished_at = current_timestamp(), message = '{escaped}'
        WHERE run_id = '{run_id}'
        """
    )


def set_month_status(spark, config, month: str, status: str, source: str, run_id: str) -> None:
    """Upsert the authoritative processing status for one billing month."""
    # One row per month records whether daily ingestion is still allowed.
    table = config.table("month_status", "ops")
    spark.sql(
        f"""
        MERGE INTO {table} AS target
        USING (
          SELECT '{month}' AS billing_month, '{status}' AS status,
                 '{source}' AS authoritative_source, '{run_id}' AS last_run_id,
                 current_timestamp() AS updated_at
        ) AS source
        ON target.billing_month = source.billing_month
        WHEN MATCHED THEN UPDATE SET *
        WHEN NOT MATCHED THEN INSERT *
        """
    )
