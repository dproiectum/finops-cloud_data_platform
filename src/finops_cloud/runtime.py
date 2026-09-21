"""Spark session creation for Jobs and Databricks Connect."""

from __future__ import annotations


def get_spark(profile: str | None = None):
    """Return an active Job session or create a Databricks Connect session."""
    try:
        from pyspark.sql import SparkSession

        # Databricks Jobs already provide an active remote Spark session.
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

    # Local VS Code execution falls back to Databricks Connect.
    builder = DatabricksSession.builder
    if profile:
        builder = builder.profile(profile)
    return builder.getOrCreate()


def ensure_schemas(spark, config) -> None:
    """Fail clearly when manually provisioned Unity Catalog schemas are absent."""
    namespaces = [
        (config.raw_catalog, config.raw_schema),
        *((config.catalog, schema) for schema in config.schemas.values()),
        (config.operations_catalog, config.operations_schema),
    ]
    for catalog, schema in namespaces:
        spark.sql(f"DESCRIBE SCHEMA `{catalog}`.`{schema}`")
