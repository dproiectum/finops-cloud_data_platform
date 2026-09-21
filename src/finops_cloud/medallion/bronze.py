"""Bronze ingestion metadata applied to source Parquet files."""

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
