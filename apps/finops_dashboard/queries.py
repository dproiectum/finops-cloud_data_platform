"""SQL queries against certified PROD datamarts and shared operational audits."""

from __future__ import annotations

from config import DashboardConfig


def _literal(value: str) -> str:
    return value.replace("'", "''")


def available_months(config: DashboardConfig) -> str:
    return f"""
        SELECT DISTINCT billing_month
        FROM {config.datamart('dm_executive_summary_monthly')}
        WHERE billing_month IS NOT NULL
        ORDER BY billing_month DESC
    """


def executive_summary(config: DashboardConfig, month: str) -> str:
    value = _literal(month)
    return f"""
        WITH history AS (
          SELECT
            billing_month,
            charge_lines,
            active_resources,
            consumed_services,
            billed_cost,
            effective_cost,
            list_cost,
            total_savings_vs_list,
            lag(billed_cost) OVER (ORDER BY billing_month) AS previous_billed_cost
          FROM {config.datamart('dm_executive_summary_monthly')}
        )
        SELECT
          charge_lines,
          active_resources AS resources,
          consumed_services AS services,
          billed_cost,
          effective_cost,
          list_cost,
          total_savings_vs_list AS savings_vs_list,
          previous_billed_cost,
          billed_cost - previous_billed_cost AS month_change,
          CASE
            WHEN previous_billed_cost IS NULL OR previous_billed_cost = 0 THEN NULL
            ELSE 100 * (billed_cost - previous_billed_cost) / abs(previous_billed_cost)
          END AS month_change_rate,
          CASE WHEN active_resources = 0 THEN 0 ELSE billed_cost / active_resources END
            AS average_cost_per_resource,
          CASE WHEN consumed_services = 0 THEN 0 ELSE billed_cost / consumed_services END
            AS average_cost_per_service
        FROM history
        WHERE billing_month = '{value}'
    """


def monthly_trend(config: DashboardConfig) -> str:
    return f"""
        SELECT billing_month, monthly_billed_cost
        FROM {config.datamart('dm_monthly_billing')}
        ORDER BY billing_month
    """


def daily_trend(config: DashboardConfig, month: str) -> str:
    value = _literal(month)
    return f"""
        SELECT date, daily_billed_cost
        FROM {config.datamart('dm_daily_billing')}
        WHERE CAST(date AS STRING) LIKE '{value}%'
        ORDER BY date
    """


def savings_summary(config: DashboardConfig, month: str) -> str:
    value = _literal(month)
    return f"""
        SELECT list_cost, contracted_cost, effective_cost,
               negotiated_savings, commitment_savings,
               total_savings_vs_list AS total_savings, savings_rate
        FROM {config.datamart('dm_savings_monthly')}
        WHERE billing_month = '{value}'
    """


def monthly_savings(config: DashboardConfig) -> str:
    return f"""
        SELECT billing_month, negotiated_savings, commitment_savings,
               total_savings_vs_list AS total_savings, savings_rate
        FROM {config.datamart('dm_savings_monthly')}
        ORDER BY billing_month
    """


def services(config: DashboardConfig, month: str, limit: int = 15) -> str:
    value = _literal(month)
    return f"""
        SELECT service_category, service_name,
               SUM(total_billed_cost) AS total_billed_cost
        FROM {config.datamart('dm_cost_by_scope_service_month')}
        WHERE billing_month = '{value}'
        GROUP BY service_category, service_name
        ORDER BY total_billed_cost DESC
        LIMIT {int(limit)}
    """


def cost_centers(config: DashboardConfig, month: str, limit: int = 20) -> str:
    value = _literal(month)
    return f"""
        SELECT coalesce(cost_center, 'Unallocated') AS cost_center,
               SUM(total_billed_cost) AS total_billed_cost
        FROM {config.datamart('dm_cost_by_scope_service_month')}
        WHERE billing_month = '{value}'
        GROUP BY cost_center
        ORDER BY total_billed_cost DESC
        LIMIT {int(limit)}
    """


def charge_types(config: DashboardConfig, month: str) -> str:
    value = _literal(month)
    return f"""
        SELECT charge_category, charge_subcategory, charge_frequency,
               total_billed_cost
        FROM {config.datamart('dm_cost_by_charge_type')}
        WHERE billing_month = '{value}'
        ORDER BY total_billed_cost DESC
    """


def resources(config: DashboardConfig, month: str, limit: int = 25) -> str:
    value = _literal(month)
    return f"""
        SELECT resource_group_name, resource_name, region, total_billed_cost
        FROM {config.datamart('dm_top_resources_monthly')}
        WHERE billing_month = '{value}'
        ORDER BY total_billed_cost DESC
        LIMIT {int(limit)}
    """


def resource_groups(config: DashboardConfig, month: str, limit: int = 25) -> str:
    value = _literal(month)
    return f"""
        SELECT resource_group_name, total_billed_cost, resource_count
        FROM {config.datamart('dm_cost_by_resource_group_month')}
        WHERE billing_month = '{value}'
        ORDER BY total_billed_cost DESC
        LIMIT {int(limit)}
    """


def subscriptions(config: DashboardConfig, month: str) -> str:
    value = _literal(month)
    return f"""
        SELECT subscription_id, subscription_name, total_billed_cost, resource_count
        FROM {config.datamart('dm_cost_by_subscription_month')}
        WHERE billing_month = '{value}'
        ORDER BY total_billed_cost DESC
    """


def application_owners(config: DashboardConfig, month: str, limit: int = 50) -> str:
    value = _literal(month)
    return f"""
        SELECT application_owner_id, application_owner_email,
               application_business_owner, application_code, application_name,
               total_billed_cost, resource_count
        FROM {config.datamart('dm_cost_by_application_owner_month')}
        WHERE billing_month = '{value}'
        ORDER BY total_billed_cost DESC
        LIMIT {int(limit)}
    """


def portfolio_services(config: DashboardConfig) -> str:
    return f"""
        SELECT service_category, service_name, total_billed_cost
        FROM {config.datamart('dm_top_services')}
        ORDER BY total_billed_cost DESC
        LIMIT 30
    """


def portfolio_resources(config: DashboardConfig) -> str:
    return f"""
        SELECT resource_group_name, resource_name, region, total_billed_cost
        FROM {config.datamart('dm_top_resources')}
        ORDER BY total_billed_cost DESC
        LIMIT 30
    """


def sku_costs(config: DashboardConfig) -> str:
    return f"""
        SELECT sku_id, meter_category, meter_name, total_billed_cost
        FROM {config.datamart('dm_sku_cost')}
        ORDER BY total_billed_cost DESC
        LIMIT 50
    """


def data_quality(config: DashboardConfig, month: str) -> str:
    value = _literal(month)
    return f"""
        SELECT total_rows, billed_cost_nulls, currency_nulls, service_nulls,
               batches, latest_silver_load,
               CASE WHEN total_rows = 0 THEN 0 ELSE
                 100 * (1 - CAST(
                   billed_cost_nulls + currency_nulls + service_nulls AS DOUBLE
                 ) / (3 * total_rows))
               END AS critical_completeness_rate
        FROM {config.datamart('dm_data_quality_monthly')}
        WHERE billing_month = '{value}'
    """


def latest_pipeline_runs(config: DashboardConfig, limit: int = 30) -> str:
    environment = _literal(config.environment)
    return f"""
        WITH latest AS (
          SELECT *, row_number() OVER (
            PARTITION BY environment, pipeline_name, billing_month
            ORDER BY started_at DESC
          ) AS rn
          FROM {config.audit('pipeline_run')}
          WHERE environment = '{environment}'
        )
        SELECT run_id, pipeline_name, billing_month, status,
               started_at, finished_at, message
        FROM latest
        WHERE rn = 1
        ORDER BY started_at DESC
        LIMIT {int(limit)}
    """


def latest_reconciliations(config: DashboardConfig, limit: int = 24) -> str:
    environment = _literal(config.environment)
    return f"""
        WITH latest AS (
          SELECT *, row_number() OVER (
            PARTITION BY environment, billing_month
            ORDER BY reconciled_at DESC
          ) AS rn
          FROM {config.audit('monthly_reconciliation')}
          WHERE environment = '{environment}'
        )
        SELECT billing_month, status, billing_rows, after_rows,
               after_billing_difference, reconciled_at
        FROM latest
        WHERE rn = 1
        ORDER BY billing_month DESC
        LIMIT {int(limit)}
    """


def environment_run_counts(config: DashboardConfig) -> str:
    return f"""
        SELECT environment,
               count(*) AS total_runs,
               sum(CASE WHEN status = 'SUCCESS' THEN 1 ELSE 0 END) AS successful_runs,
               max(started_at) AS latest_run
        FROM {config.audit('pipeline_run')}
        GROUP BY environment
        ORDER BY environment
    """
