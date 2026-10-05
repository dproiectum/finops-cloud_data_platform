"""Manually apply a synthetic allocation policy to already loaded environments.

Only a Gold view and the allocation datamart are published. Source Parquet,
Bronze, Silver, Gold facts, and security assignments are never changed here.
"""

from decimal import Decimal

from finops_cloud.medallion.gold import cost_allocation_context, refresh_cost_allocation_view
from finops_cloud.sql.runner import execute_sql_file


ALLOCATION_DATAMART = "datamarts/table_refresh/03_dm_cost_by_scope_service_month.sql"
CONFIRMATION = "APPLY_COST_CENTER_ALLOCATION"


def _totals(spark, table, columns):
    aggregates = ", ".join(
        f"coalesce(SUM({column}), 0) AS {alias}" for alias, column in columns.items()
    )
    rows = spark.sql(
        f"SELECT billing_month, count(*) AS row_count, {aggregates} "
        f"FROM {table} GROUP BY billing_month"
    ).collect()
    result = {}
    for row in rows:
        values = row.asDict()
        month = values.pop("billing_month")
        if not month:
            raise ValueError("Allocation refused: a loaded row has no billing_month")
        result[month] = values
    return result


def _compare(expected, actual, tolerance, *, check_rows=True):
    if set(expected) != set(actual):
        raise ValueError("Allocation reconciliation failed: billing months differ")
    for month, reference in expected.items():
        for name, value in reference.items():
            if name == "row_count":
                if check_rows and value != actual[month][name]:
                    raise ValueError(f"Allocation reconciliation failed: {month} row count differs")
            elif abs(Decimal(str(value)) - Decimal(str(actual[month][name]))) > tolerance:
                raise ValueError(f"Allocation reconciliation failed: {month} {name} differs")


def apply_cost_allocation(spark, config, confirmation):
    """Run after loaded DEV/PROD controls pass, with paused ingestion jobs."""
    if confirmation != CONFIRMATION:
        raise ValueError(f"Set confirmation to {CONFIRMATION}")
    if config.environment not in {"dev", "prod"} or config.catalog != f"finops_{config.environment}":
        raise ValueError("Allocation maintenance requires the matching finops_dev/finops_prod catalog")
    context = cost_allocation_context(config)  # Validate identifiers and allowlist before DDL.
    tolerance = Decimal(config.amount_tolerance)
    amounts = {"billed": "BilledCost", "effective": "EffectiveCost", "list_cost": "ListCost"}
    baseline = _totals(spark, context["silver_central"], amounts)
    if not baseline:
        raise ValueError("Allocation maintenance requires loaded Silver and Gold data")
    fact_totals = _totals(spark, context["fact_cost_usage"], {
        "billed": "billed_cost", "effective": "effective_cost", "list_cost": "list_cost",
    })
    _compare(baseline, fact_totals, tolerance)

    refresh_cost_allocation_view(spark, config)
    _compare(baseline, _totals(spark, context["cost_allocation_view"], amounts), tolerance)
    execute_sql_file(spark, ALLOCATION_DATAMART, context)
    mart_totals = _totals(spark, context["dm_cost_by_scope_service_month"], {
        "billed": "total_billed_cost",
    })
    billed_baseline = {month: {"billed": values["billed"]} for month, values in baseline.items()}
    _compare(billed_baseline, mart_totals, tolerance, check_rows=False)
    # Detect ingestion during maintenance; do not report success over changing sources.
    _compare(baseline, _totals(spark, context["silver_central"], amounts), Decimal(0))
    _compare(fact_totals, _totals(spark, context["fact_cost_usage"], {
        "billed": "billed_cost", "effective": "effective_cost", "list_cost": "list_cost",
    }), Decimal(0))
    return {
        "status": "PASS", "environment": config.environment,
        "policy": "REGION_FALLBACK_V1", "loaded_months": len(baseline),
        "source_rows": sum(values["row_count"] for values in baseline.values()),
        "allocation_view": context["cost_allocation_view"],
        "allocation_datamart": context["dm_cost_by_scope_service_month"],
    }
