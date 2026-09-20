"""Safe inspection and reset helpers for the FinOps project tables."""

from __future__ import annotations

import re


# Downstream-first order keeps the reset valid if constraints are added later.
TABLE_GROUPS = (
    (
        "datamart",
        (
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
        ),
    ),
    (
        "gold",
        (
            "bridge_resource_tag",
            "fact_cost_usage",
            "dim_tag",
            "dim_charge_type",
            "dim_pricing",
            "dim_commitment_discount",
            "dim_location",
            "dim_sku",
            "dim_resource",
            "dim_service",
            "dim_billing_scope",
            "dim_date",
        ),
    ),
    ("silver", ("silver_central", "silver_canonical")),
    ("bronze", ("bronze_billing", "bronze_daily")),
    (
        "ops",
        ("file_archive", "reconciliation", "month_snapshot", "month_status", "pipeline_run"),
    ),
)

_SAFE_TABLE = re.compile(
    r"^[A-Za-z_][A-Za-z0-9_]*\.[A-Za-z_][A-Za-z0-9_]*\.[A-Za-z_][A-Za-z0-9_]*$"
)


def project_tables(config) -> list[tuple[str, str, str]]:
    """Return every configured project table in safe reset order."""
    result = [
        (layer, key, config.table(key, layer))
        for layer, keys in TABLE_GROUPS
        for key in keys
    ]
    configured = set(config.tables)
    declared = {key for _layer, key, _table in result}
    if declared != configured:
        raise ValueError(
            "Maintenance table registry differs from configuration: "
            f"missing={sorted(configured - declared)}, extra={sorted(declared - configured)}"
        )
    unsafe = [table for _layer, _key, table in result if not _SAFE_TABLE.fullmatch(table)]
    if unsafe:
        raise ValueError(f"Unsafe table identifiers: {unsafe}")
    return result


def inspect_project_tables(spark, config) -> list[dict[str, object]]:
    """Check existence and emptiness without scanning complete tables."""
    states = []
    for layer, key, table in project_tables(config):
        exists = spark.catalog.tableExists(table)
        has_rows = bool(exists and spark.table(table).limit(1).count())
        states.append(
            {
                "layer": layer,
                "table_key": key,
                "table_name": table,
                "exists": exists,
                "is_empty": not has_rows,
            }
        )
    return states


def all_tables_empty(states: list[dict[str, object]]) -> bool:
    """Treat missing tables as empty and reject any table containing data."""
    return all(bool(state["is_empty"]) for state in states)


def truncate_project_tables(spark, config) -> list[str]:
    """Remove rows from existing project tables without deleting GCS source files."""
    truncated = []
    for _layer, _key, table in project_tables(config):
        if spark.catalog.tableExists(table):
            spark.sql(f"TRUNCATE TABLE {table}")
            truncated.append(table)
    remaining = inspect_project_tables(spark, config)
    if not all_tables_empty(remaining):
        non_empty = [state["table_name"] for state in remaining if not state["is_empty"]]
        raise RuntimeError(f"Reset verification failed for: {non_empty}")
    return truncated
