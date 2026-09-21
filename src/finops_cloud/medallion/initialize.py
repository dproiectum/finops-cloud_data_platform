"""Manual creation of empty Bronze, Silver, Gold, and datamart tables."""

from __future__ import annotations

import re

from finops_cloud.audit.snapshots import ensure_audit_tables
from finops_cloud.config import load_config
from finops_cloud.medallion.bronze import add_ingestion_metadata
from finops_cloud.medallion.contract import apply_focus_contract
from finops_cloud.medallion.delta import align_to_target, table_exists
from finops_cloud.medallion.gold import ensure_gold_tables, refresh_datamarts
from finops_cloud.medallion.silver import prepare_canonical
from finops_cloud.runtime import ensure_schemas, get_spark


DERIVED_TABLES = (
    ("bronze_daily", "bronze"),
    ("bronze_billing", "bronze"),
    ("silver_canonical", "silver"),
    ("silver_central", "silver"),
)

GOLD_TABLE_KEYS = (
    "dim_date",
    "dim_billing_scope",
    "dim_resource",
    "dim_service",
    "dim_sku",
    "dim_location",
    "dim_commitment_discount",
    "dim_pricing",
    "dim_charge_type",
    "dim_tag",
    "bridge_resource_tag",
    "fact_cost_usage",
)

DATAMART_TABLE_KEYS = (
    "dm_monthly_billing",
    "dm_daily_billing",
    "dm_cost_by_scope_service_month",
    "dm_top_services",
    "dm_top_resources",
    "dm_cost_by_charge_type",
    "dm_sku_cost",
    "dm_savings_monthly",
    "dm_executive_summary_monthly",
    "dm_top_resources_monthly",
    "dm_data_quality_monthly",
    "dm_cost_by_resource_group_month",
    "dm_cost_by_subscription_month",
    "dm_cost_by_application_owner_month",
)


def business_tables(config) -> tuple[str, ...]:
    """Return the 30 managed business tables expected in one environment."""
    derived = tuple(config.table(key, layer) for key, layer in DERIVED_TABLES)
    gold = tuple(config.table(key, "gold") for key in GOLD_TABLE_KEYS)
    datamarts = tuple(config.table(key, "datamart") for key in DATAMART_TABLE_KEYS)
    return (*derived, *gold, *datamarts)


def _validate_month(month: str) -> None:
    if not re.fullmatch(r"[0-9]{4}-(0[1-9]|1[0-2])", month):
        raise ValueError("sample_month must use YYYY-MM")


def _assert_existing_tables_empty(spark, table_names: tuple[str, ...]) -> None:
    """Refuse to initialize over any business table that already contains data."""
    non_empty = [
        name
        for name in table_names
        if table_exists(spark, name) and spark.table(name).limit(1).count() > 0
    ]
    if non_empty:
        raise ValueError(
            "Initialization is allowed only on empty business tables; non-empty: "
            + ", ".join(non_empty)
        )


def _create_empty_table(spark, frame, table_name: str) -> None:
    """Create one empty Delta table, or validate a table from a partial retry."""
    empty_frame = frame.limit(0)
    if table_exists(spark, table_name):
        align_to_target(spark, empty_frame, table_name)
        return
    empty_frame.write.format("delta").mode("errorifexists").saveAsTable(table_name)


def initialize_empty_tables(environment: str, sample_month: str) -> dict[str, object]:
    """Create every empty business table without writing rows or OPS events.

    A monthly Parquet is read only to derive the exact Bronze and Silver schemas.
    Gold schemas remain SQL-owned, and datamarts are built from empty source tables.
    """
    _validate_month(sample_month)
    config = load_config(environment)
    spark = get_spark(config.profile)
    ensure_schemas(spark, config)
    ensure_audit_tables(spark, config)

    expected_tables = business_tables(config)
    _assert_existing_tables_empty(spark, expected_tables)
    existing_before = {name for name in expected_tables if table_exists(spark, name)}

    source_uri = config.billing_volume_uri(sample_month)
    raw = spark.read.parquet(source_uri)
    empty_bronze = add_ingestion_metadata(
        raw,
        run_id="SCHEMA_INITIALIZATION_ONLY",
        source_type="MONTHLY_BILLING",
        data_status="FINAL",
    ).limit(0)
    empty_silver = prepare_canonical(
        apply_focus_contract(
            empty_bronze,
            config.contract_path,
            config.currency,
            config.provider,
        ),
        config.contract_version,
    ).limit(0)

    for key in ("bronze_daily", "bronze_billing"):
        _create_empty_table(spark, empty_bronze, config.table(key, "bronze"))
    for key in ("silver_canonical", "silver_central"):
        _create_empty_table(spark, empty_silver, config.table(key, "silver"))

    ensure_gold_tables(spark, config)
    refresh_datamarts(spark, config)

    missing = [name for name in expected_tables if not table_exists(spark, name)]
    non_empty = [
        name for name in expected_tables if spark.table(name).limit(1).count() > 0
    ]
    if missing or non_empty:
        raise RuntimeError(
            f"Empty-table initialization failed; missing={missing}, non_empty={non_empty}"
        )

    return {
        "environment": environment,
        "catalog": config.catalog,
        "sample_source": source_uri,
        "expected_table_count": len(expected_tables),
        "created_table_count": len(set(expected_tables) - existing_before),
        "all_tables_empty": True,
    }
