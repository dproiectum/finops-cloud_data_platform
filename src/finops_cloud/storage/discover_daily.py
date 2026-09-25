"""Discover daily Parquet files that have not reached an environment's Silver layer."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import re
from typing import Callable, Iterable


DAILY_FILE_PATTERN = re.compile(
    r"/daily/(?P<year>[0-9]{4})/(?P<month>0[1-9]|1[0-2])/"
    r"(?P<date>[0-9]{4}-(?:0[1-9]|1[0-2])-(?:0[1-9]|[12][0-9]|3[01]))\.parquet$"
)
CLOSED_STATUSES = {
    "CLOSED",
    "CLOSED_DATA_LOADED",
    "CLOSED_ARCHIVE_PENDING",
}


@dataclass(frozen=True)
class DailyFile:
    """One daily object and its eligibility for incremental processing."""

    source_uri: str
    processing_date: str
    billing_month: str
    status: str

    def as_dict(self) -> dict[str, str]:
        return asdict(self)


def normalize_source_uri(path: str, config) -> str:
    """Map GCS, DBFS, file, and Volume spellings to one Volume path."""
    value = str(path).strip()
    for prefix in ("dbfs:", "file:"):
        if value.startswith(prefix):
            value = value[len(prefix) :]
    if value.startswith("/dbfs/Volumes/"):
        value = value[len("/dbfs") :]
    gcs_prefix = f"gs://{config.gcs_bucket}/{config.active_prefix}/"
    if value.startswith(gcs_prefix):
        relative = value[len(gcs_prefix) :]
        value = f"{config.source_volume}/{relative}"
    return value.rstrip("/")


def parse_daily_uri(path: str, config) -> tuple[str, str, str]:
    """Return normalized URI, processing date, and month for a valid daily path."""
    normalized = normalize_source_uri(path, config)
    match = DAILY_FILE_PATTERN.search(normalized)
    if match is None:
        raise ValueError(
            "Daily path must use daily/YYYY/MM/YYYY-MM-DD.parquet: "
            f"{normalized}"
        )
    date = match.group("date")
    if date[:4] != match.group("year") or date[5:7] != match.group("month"):
        raise ValueError(f"Daily path partitions disagree with its filename: {normalized}")
    return normalized, date, date[:7]


def list_parquet_files(
    root: str,
    list_directory: Callable[[str], Iterable[object]],
) -> list[str]:
    """Recursively list Parquet files using ``dbutils.fs.ls``-compatible output."""
    pending = [root.rstrip("/") + "/"]
    result: list[str] = []
    while pending:
        current = pending.pop()
        for item in list_directory(current):
            path = str(getattr(item, "path", item))
            is_directory = bool(
                item.isDir() if callable(getattr(item, "isDir", None))
                else getattr(item, "is_dir", path.endswith("/"))
            )
            if is_directory:
                pending.append(path)
            elif path.lower().endswith(".parquet"):
                result.append(path)
    return sorted(set(result))


def _existing_source_files(spark, config) -> set[str]:
    table = config.table("silver_canonical", "silver")
    if not spark.catalog.tableExists(table):
        return set()
    return {
        normalize_source_uri(row["_source_file"], config)
        for row in spark.table(table).select("_source_file").distinct().collect()
        if row["_source_file"]
    }


def _closed_months(spark, config) -> set[str]:
    from pyspark.sql import functions as F

    table = config.table("month_status", "ops")
    if not spark.catalog.tableExists(table):
        return set()
    rows = (
        spark.table(table)
        .where(F.col("environment") == F.lit(config.environment))
        .where(F.col("status").isin(*sorted(CLOSED_STATUSES)))
        .select("billing_month")
        .distinct()
        .collect()
    )
    return {row["billing_month"] for row in rows}


def inventory_daily_files(
    spark,
    config,
    list_directory: Callable[[str], Iterable[object]],
) -> list[DailyFile]:
    """Classify all storage files as NEW, LOADED, or CLOSED for one environment."""
    storage_files = list_parquet_files(
        f"{config.source_volume}/daily",
        list_directory,
    )
    existing = _existing_source_files(spark, config)
    closed = _closed_months(spark, config)
    inventory: list[DailyFile] = []
    for path in storage_files:
        uri, processing_date, billing_month = parse_daily_uri(path, config)
        if billing_month in closed:
            status = "CLOSED"
        elif uri in existing:
            status = "LOADED"
        else:
            status = "NEW"
        inventory.append(DailyFile(uri, processing_date, billing_month, status))
    return sorted(inventory, key=lambda item: (item.processing_date, item.source_uri))


def select_daily_file(
    inventory: Iterable[DailyFile],
    *,
    processing_date: str = "",
    source_uri_override: str = "",
    config,
) -> DailyFile | None:
    """Select an explicit candidate or the oldest unprocessed daily file."""
    items = list(inventory)
    if source_uri_override:
        requested = normalize_source_uri(source_uri_override, config)
        matches = [item for item in items if item.source_uri == requested]
        if not matches:
            raise ValueError(f"Daily source is absent from storage: {requested}")
        selected = matches[0]
        if selected.status == "CLOSED":
            raise ValueError(
                f"Daily source targets a closed month: {selected.billing_month}"
            )
        return selected
    candidates = sorted(
        (item for item in items if item.status == "NEW"),
        key=lambda item: (item.processing_date, item.source_uri),
    )
    if processing_date:
        candidates = [
            item for item in candidates if item.processing_date == processing_date
        ]
        if not candidates:
            raise ValueError(
                f"No new daily source is available for {processing_date}"
            )
    return candidates[0] if candidates else None
