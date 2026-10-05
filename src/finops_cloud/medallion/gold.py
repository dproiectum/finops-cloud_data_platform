"""Execute the SQL-owned Gold star schema and certified datamarts."""

from __future__ import annotations

import re
from uuid import uuid4

from finops_cloud.sql.runner import execute_sql_file, table_context


# Python orchestrates execution; SQL remains the source of truth for warehouse logic.
GOLD_DDL = "gold/table_creation/00_create_gold_tables.sql"
COST_ALLOCATION_DDL = "gold/table_creation/01_create_cost_allocation_view.sql"
GOLD_LOAD_SCRIPTS = (
    "gold/data_loading/10_merge_dimensions.sql",
    "gold/data_loading/20_merge_tags.sql",
    "gold/data_loading/30_replace_fact_month.sql",
)
DATAMART_SCRIPTS = tuple(
    f"datamarts/table_refresh/{index:02d}_{name}.sql"
    for index, name in enumerate(
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
        start=1,
    )
)


def _validate_month(month: str) -> None:
    """Validate the YYYY-MM value injected into month-scoped Gold SQL."""
    if not re.fullmatch(r"[0-9]{4}-(0[1-9]|1[0-2])", month):
        raise ValueError("month must use YYYY-MM")


def ensure_gold_tables(spark, config) -> None:
    """Run the idempotent DDL that creates the Gold star schema tables."""
    execute_sql_file(spark, GOLD_DDL, table_context(config))


def refresh_datamarts(spark, config) -> None:
    """Rebuild all certified datamart tables from Silver and Gold sources."""
    context = table_context(config)
    refresh_cost_allocation_view(spark, config)
    # Numeric filenames make execution order explicit and reproducible.
    for relative_path in DATAMART_SCRIPTS:
        execute_sql_file(spark, relative_path, context)


def cost_allocation_context(config) -> dict[str, str]:
    """Validate the explicit Corporate region allowlist before rendering SQL."""
    regions = config.corporate_regions
    if not isinstance(regions, tuple) or any(
        not isinstance(region, str) or not region.strip() for region in regions
    ):
        raise ValueError("corporate_regions must contain non-empty region names")
    normalized = tuple(region.strip().lower() for region in regions)
    if any(not re.fullmatch(r'[a-z0-9][a-z0-9 _-]*', region) for region in normalized):
        raise ValueError("corporate_regions must use plain Azure region names")
    reserved = {'west europe', 'north europe', 'france central', 'sweden central',
                'uk south', 'global'}
    if len(set(normalized)) != len(normalized) or reserved.intersection(normalized):
        raise ValueError("corporate_regions must be unique and exclude Europe/Global defaults")
    # An empty allowlist matches nothing, including rows with a missing Region.
    region_sql = ', '.join("'" + region.replace("'", "''") + "'" for region in normalized)
    return {**table_context(config), 'corporate_regions_sql': region_sql or 'NULL'}


def refresh_cost_allocation_view(spark, config) -> None:
    """Publish the shared line-level allocation policy for marts and serving."""
    execute_sql_file(spark, COST_ALLOCATION_DDL, cost_allocation_context(config))


def refresh_gold_for_month(spark, config, month_frame, month: str) -> None:
    """Load one complete month into Gold, then rebuild certified datamarts."""
    _validate_month(month)
    if month_frame.limit(1).count() == 0:
        raise ValueError("Refusing to refresh Gold from an empty month")

    source_view = f"finops_gold_month_{uuid4().hex}"
    # SQL scripts read this temporary view without knowing how Python built it.
    month_frame.createOrReplaceTempView(source_view)
    context = table_context(config)
    context.update(
        {
            "source_month": source_view,
            "billing_month": month,
            "focus_version": config.focus_version.replace("'", "''"),
        }
    )
    try:
        execute_sql_file(spark, GOLD_DDL, context)
        for relative_path in GOLD_LOAD_SCRIPTS:
            execute_sql_file(spark, relative_path, context)
    finally:
        spark.catalog.dropTempView(source_view)

    refresh_datamarts(spark, config)
