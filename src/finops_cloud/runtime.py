"""Spark session creation for Jobs and Databricks Connect."""

from __future__ import annotations


def get_spark(profile: str | None = None):
    """Return an active Job session or create a Databricks Connect session."""
    try:
        from pyspark.sql import SparkSession

        active = SparkSession.getActiveSession()
        if active is not None:
            return active
    except ImportError:
        pass

    try:
        from databricks.connect import DatabricksSession
    except ImportError as exc:
        raise RuntimeError(
            "No active Databricks Spark session. Install the Databricks Connect "
            "version matching the target Runtime or run this code as a Databricks Job."
        ) from exc

    builder = DatabricksSession.builder
    if profile:
        builder = builder.profile(profile)
    return builder.getOrCreate()


def ensure_schemas(spark, config) -> None:
    """Create every configured medallion and operations schema if absent."""
    for schema in config.schemas.values():
        spark.sql(f"CREATE SCHEMA IF NOT EXISTS `{config.catalog}`.`{schema}`")
