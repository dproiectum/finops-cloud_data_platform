"""Execute the SQL-owned Gold star schema and certified datamarts."""

from __future__ import annotations

import re
from uuid import uuid4

from finops_cloud.sql_runner import execute_sql_file, table_context


GOLD_DDL = "gold/table_creation/00_create_gold_tables.sql"
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
    if not re.fullmatch(r"[0-9]{4}-(0[1-9]|1[0-2])", month):
        raise ValueError("month must use YYYY-MM")


def ensure_gold_tables(spark, config) -> None:
    execute_sql_file(spark, GOLD_DDL, table_context(config))


def refresh_datamarts(spark, config) -> None:
    context = table_context(config)
    for relative_path in DATAMART_SCRIPTS:
        execute_sql_file(spark, relative_path, context)


def refresh_gold_for_month(spark, config, month_frame, month: str) -> None:
    """Load one complete month into Gold, then rebuild certified datamarts."""
    _validate_month(month)
    if month_frame.limit(1).count() == 0:
        raise ValueError("Refusing to refresh Gold from an empty month")

    source_view = f"finops_gold_month_{uuid4().hex}"
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
