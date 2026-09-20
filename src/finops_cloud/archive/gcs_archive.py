"""Idempotent GCS archival with generation and checksum verification."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def _storage_client(config):
    try:
        from google.cloud import storage
    except ImportError as exc:
        raise RuntimeError("google-cloud-storage is required for archival") from exc

    credentials = None
    if config.gcs_service_credential:
        try:
            from databricks.sdk.runtime import dbutils

            credentials = dbutils.credentials.getServiceCredentialsProvider(
                config.gcs_service_credential
            )
        except (ImportError, AttributeError):
            # VS Code / Databricks Connect uses local Application Default
            # Credentials. Production Jobs use the named UC service credential.
            credentials = None
    project = config.gcp_project
    if project and project.startswith("CHANGE_ME"):
        project = None
    return storage.Client(project=project, credentials=credentials)


def _record(bucket_name: str, source_name: str, destination, status: str):
    return {
        "source_uri": f"gs://{bucket_name}/{source_name}",
        "archive_uri": f"gs://{bucket_name}/{destination.name}",
        "source_generation": None,
        "archive_generation": str(destination.generation),
        "crc32c": destination.crc32c,
        "size_bytes": int(destination.size or 0),
        "archive_status": status,
        "archived_at": datetime.now(timezone.utc).replace(tzinfo=None),
        "error_message": None,
    }


def _move_one(bucket, source, destination_name: str) -> dict[str, Any]:
    source.reload()
    source_generation = source.generation
    destination = bucket.blob(destination_name)
    if destination.exists():
        destination.reload()
        if source.crc32c == destination.crc32c and source.size == destination.size:
            source.delete(if_generation_match=source_generation)
            result = _record(bucket.name, source.name, destination, "RESUMED")
            result["source_generation"] = str(source_generation)
            return result
        # A corrected billing can reuse the active object name. Preserve both
        # immutable versions without overwriting the first archive object.
        parent, file_name = destination_name.rsplit("/", 1)
        destination_name = f"{parent}/revision={source_generation}/{file_name}"
        destination = bucket.blob(destination_name)
        if destination.exists():
            destination.reload()
            if source.crc32c != destination.crc32c or source.size != destination.size:
                raise ValueError(
                    "Revision archive destination differs from the source: "
                    f"gs://{bucket.name}/{destination_name}"
                )
            source.delete(if_generation_match=source_generation)
            result = _record(bucket.name, source.name, destination, "RESUMED_REVISION")
            result["source_generation"] = str(source_generation)
            return result

    copied = bucket.copy_blob(
        source,
        bucket,
        new_name=destination_name,
        if_generation_match=0,
        if_source_generation_match=source_generation,
    )
    copied.reload()
    if source.crc32c != copied.crc32c or source.size != copied.size:
        raise ValueError(f"Checksum verification failed for gs://{bucket.name}/{source.name}")
    source.delete(if_generation_match=source_generation)
    result = _record(bucket.name, source.name, copied, "SUCCESS")
    result["source_generation"] = str(source_generation)
    return result


def archive_month(config, month: str, client=None) -> list[dict[str, Any]]:
    """Archive the closed month's daily files and processed billing object."""
    if client is None:
        client = _storage_client(config)
    bucket = client.bucket(config.gcs_bucket)
    source_prefixes: list[str] = []
    if config.archive_daily:
        source_prefixes.append(config.daily_gcs_month_prefix(month))
    if config.archive_billing:
        source_prefixes.append(config.billing_gcs_object(month))

    records: list[dict[str, Any]] = []
    found_active = False
    for source_prefix in source_prefixes:
        for source in client.list_blobs(config.gcs_bucket, prefix=source_prefix):
            found_active = True
            suffix = source.name[len(config.active_prefix) :].lstrip("/")
            destination_name = f"{config.archive_prefix}/{suffix}"
            records.append(_move_one(bucket, source, destination_name))

    if found_active:
        return records

    # A retry after a completed move must succeed without rewriting Silver.
    for source_prefix in source_prefixes:
        suffix = source_prefix[len(config.active_prefix) :].lstrip("/")
        archive_prefix = f"{config.archive_prefix}/{suffix}"
        for destination in client.list_blobs(config.gcs_bucket, prefix=archive_prefix):
            source_name = f"{config.active_prefix}/{destination.name[len(config.archive_prefix):].lstrip('/')}"
            records.append(
                _record(
                    config.gcs_bucket,
                    source_name,
                    destination,
                    "ALREADY_ARCHIVED",
                )
            )
    if not records:
        raise FileNotFoundError(f"No active or archived GCS objects found for {month}")
    return records


def write_archive_audit(spark, config, run_id: str, month: str, records) -> None:
    schema = """
      run_id string, billing_month string, source_uri string, archive_uri string,
      source_generation string, archive_generation string, crc32c string,
      size_bytes long, archive_status string, archived_at timestamp,
      error_message string
    """
    values = [
        (
            run_id,
            month,
            record["source_uri"],
            record["archive_uri"],
            record["source_generation"],
            record["archive_generation"],
            record["crc32c"],
            record["size_bytes"],
            record["archive_status"],
            record["archived_at"],
            record["error_message"],
        )
        for record in records
    ]
    spark.createDataFrame(values, schema).write.mode("append").saveAsTable(
        config.table("file_archive", "ops")
    )
