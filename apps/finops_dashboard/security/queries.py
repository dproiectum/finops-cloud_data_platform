"""Protected counterparts of ALL dashboard queries.

Serving views retain charge/application-grain data. Every business query applies
live entitlements before aggregating. Real DBU telemetry needs a verified admin.
"""

from __future__ import annotations

import re
from consumption import azure_history_body

from .authorization import (
    AccessContext, BoundQuery, admin_predicate, charge_predicate, viewer_parameters,
)
from .identity import SecurityError, PORTFOLIO_PROFILES


class ScopedQueries:
    def __init__(self, context: AccessContext):
        self.context = context

    def _validate(self, config):
        if config.environment != self.context.environment:
            raise SecurityError("Cross-environment query refused.")
        if config.data_catalog != f"finops_{config.environment}":
            raise SecurityError("Cross-catalog query refused.")
        if self.context.portfolio_demo:
            expected = PORTFOLIO_PROFILES.get(self.context.identity.subject)
            if (config.environment != 'prod' or self.context.identity.provider != 'demo'
                    or expected is None or self.context.is_admin != (expected[0] == 'FINOPS_ADMIN')):
                raise SecurityError("Invalid portfolio demonstration context.")

    def _query(self, config, body: str, month: str | None = None, *,
               source_view: str = 'v_dashboard_charge_scoped') -> BoundQuery:
        self._validate(config)
        if source_view not in {'v_dashboard_charge_scoped', 'v_consumption_monthly'}:
            raise SecurityError('Unsupported scoped serving view.')
        bindings = viewer_parameters(self.context)
        if month is not None:
            if not re.fullmatch(r"[0-9]{4}-(0[1-9]|1[0-2])", month):
                raise SecurityError("Invalid billing month.")
            bindings["billing_month"] = month
        sandbox = ''
        if self.context.portfolio_demo:
            _, scope_type, scope_id = PORTFOLIO_PROFILES[self.context.identity.subject]
            if scope_type == 'APPLICATION':
                bindings['portfolio_application'] = scope_id
                sandbox = ' AND c.application_code = :portfolio_application'
            else:
                sandbox = ' AND ' + admin_predicate(config)
        text = f"""WITH authorized_rows AS (
            SELECT c.* FROM {config.datamart(source_view)} c
            WHERE {charge_predicate(config)}{sandbox}
        ) {body}"""
        return BoundQuery(text, tuple(bindings.items()))

    @staticmethod
    def _limit(limit: int) -> int:
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
            raise SecurityError("Invalid result limit.")
        return limit

    def available_months(self, config):
        return self._query(config, """SELECT DISTINCT billing_month FROM authorized_rows
            WHERE billing_month IS NOT NULL ORDER BY billing_month DESC""")

    def consumption_months(self, config):
        return self._query(config, """SELECT DISTINCT billing_month FROM authorized_rows
            WHERE billing_month IS NOT NULL ORDER BY billing_month DESC""",
            source_view='v_consumption_monthly')

    def consumption_history(self, config, year):
        if not isinstance(year, str) or not re.fullmatch(r'[0-9]{4}', year):
            raise SecurityError('Invalid consumption year.')
        statement = self._query(
            config, azure_history_body('billing_month LIKE :consumption_year'),
            source_view='v_consumption_monthly',
        )
        return BoundQuery(statement.text, (*statement.bindings, ('consumption_year', f'{year}-%')))

    def databricks_consumption(self, config):
        # Local/selectable demo admins are not authenticated operational viewers.
        if (self.context.identity.provider != 'iap' or self.context.portfolio_demo
                or self.context.environment != 'prod'):
            raise SecurityError('Real DBU telemetry requires a verified private PROD administrator.')
        return self._ops(config, f"""SELECT usage_month, workspace_label, sku_name,
            billing_origin_product, usage_unit, is_genie_free_usage,
            net_dbu, billing_records, first_available_usage_date, last_available_usage_date
            FROM `{config.operations_catalog}`.`monitoring`.`v_databricks_consumption_monthly`
            WHERE {admin_predicate(config)}
            ORDER BY usage_month DESC, workspace_label, sku_name, billing_origin_product""")

    def executive_history(self, config):
        return self._query(config, """SELECT billing_month, COUNT(*) AS charge_lines,
            coalesce(SUM(billed_cost), 0) AS billed_cost,
            coalesce(SUM(effective_cost), 0) AS effective_cost,
            coalesce(SUM(list_cost), 0) AS list_cost,
            coalesce(SUM(list_cost), 0) - coalesce(SUM(effective_cost), 0) AS savings_vs_list
            FROM authorized_rows WHERE billing_month IS NOT NULL
            GROUP BY billing_month ORDER BY billing_month""")

    def executive_summary(self, config, month):
        return self._query(config, """, monthly AS (
            SELECT billing_month, COUNT(*) AS charge_lines,
              COUNT(DISTINCT resource_id) AS resources,
              COUNT(DISTINCT service_name) AS services,
              coalesce(SUM(billed_cost), 0) AS billed_cost,
              coalesce(SUM(effective_cost), 0) AS effective_cost,
              coalesce(SUM(list_cost), 0) AS list_cost
            FROM authorized_rows WHERE billing_month IS NOT NULL GROUP BY billing_month
        ), history AS (
            SELECT *, lag(billed_cost) OVER (ORDER BY billing_month) AS previous_billed_cost
            FROM monthly
        ) SELECT *, list_cost - effective_cost AS savings_vs_list,
            billed_cost - previous_billed_cost AS month_change,
            CASE WHEN previous_billed_cost IS NULL OR previous_billed_cost = 0 THEN NULL
              ELSE 100 * (billed_cost - previous_billed_cost) / abs(previous_billed_cost)
            END AS month_change_rate,
            CASE WHEN resources = 0 THEN 0 ELSE billed_cost / resources END
              AS average_cost_per_resource,
            CASE WHEN services = 0 THEN 0 ELSE billed_cost / services END
              AS average_cost_per_service
            FROM history WHERE billing_month = :billing_month""", month)

    def monthly_trend(self, config):
        return self._query(config, """SELECT billing_month,
            coalesce(SUM(billed_cost), 0) AS monthly_billed_cost
            FROM authorized_rows WHERE billing_month IS NOT NULL
            GROUP BY billing_month ORDER BY billing_month""")

    def daily_trend(self, config, month):
        return self._query(config, """SELECT date, SUM(billed_cost) AS daily_billed_cost
            FROM authorized_rows WHERE billing_month = :billing_month
            GROUP BY date ORDER BY date""", month)

    @staticmethod
    def _savings_body(where: str = "") -> str:
        return f"""SELECT billing_month,
            coalesce(SUM(list_cost), 0) AS list_cost,
            coalesce(SUM(contracted_cost), 0) AS contracted_cost,
            coalesce(SUM(effective_cost), 0) AS effective_cost,
            coalesce(SUM(list_cost), 0) - coalesce(SUM(contracted_cost), 0)
              AS negotiated_savings,
            coalesce(SUM(list_cost), 0) - coalesce(SUM(effective_cost), 0) AS total_savings,
            coalesce(SUM(list_cost), 0) - coalesce(SUM(effective_cost), 0)
              AS total_savings_vs_list,
            CASE WHEN coalesce(SUM(list_cost), 0) = 0 THEN 0
              ELSE 100 * (coalesce(SUM(list_cost), 0) - coalesce(SUM(effective_cost), 0))
                / SUM(list_cost) END AS savings_rate,
            coalesce(SUM(CASE WHEN effective_cost_component = 'reservation'
              THEN effective_cost ELSE 0 END), 0) AS reservation,
            coalesce(SUM(CASE WHEN effective_cost_component = 'savings_plan'
              THEN effective_cost ELSE 0 END), 0) AS savings_plan,
            coalesce(SUM(CASE WHEN effective_cost_component = 'usage_on_demand'
              THEN effective_cost ELSE 0 END), 0) AS usage_on_demand,
            coalesce(SUM(CASE WHEN effective_cost_component = 'usage_dynamic'
              THEN effective_cost ELSE 0 END), 0) AS usage_dynamic,
            coalesce(SUM(CASE WHEN effective_cost_component = 'adjustment'
              THEN effective_cost ELSE 0 END), 0) AS adjustment,
            coalesce(SUM(CASE WHEN effective_cost_component = 'other'
              THEN effective_cost ELSE 0 END), 0) AS other_effective_cost
            FROM authorized_rows WHERE billing_month IS NOT NULL {where}
            GROUP BY billing_month ORDER BY billing_month"""

    def monthly_savings(self, config):
        return self._query(config, self._savings_body())

    def savings_summary(self, config, month):
        return self._query(config, self._savings_body("AND billing_month = :billing_month"), month)

    def _grouped(self, config, fields, month=None, limit=None, extra=""):
        # fields/extra are internal constants, never UI inputs.
        period = "WHERE billing_month = :billing_month" if month is not None else ""
        top = f"LIMIT {self._limit(limit)}" if limit is not None else ""
        return self._query(config, f"""SELECT {fields}, SUM(billed_cost) AS total_billed_cost
            {extra} FROM authorized_rows {period} GROUP BY {fields}
            ORDER BY total_billed_cost DESC {top}""", month)

    def services(self, config, month, limit=15):
        return self._grouped(config, "service_name", month, limit)

    def cost_centers(self, config, month, limit=20):
        return self._query(config, f""", labeled AS (
            SELECT CASE WHEN cost_center IS NULL OR lower(trim(cost_center))
              IN ('', 'unknown', 'unallocated', 'unallocated costs', 'no cost center assigned')
              THEN 'Unallocated Costs' ELSE trim(cost_center) END AS cost_center,
              billed_cost FROM authorized_rows WHERE billing_month = :billing_month
        ) SELECT cost_center, SUM(billed_cost) AS total_billed_cost FROM labeled
          GROUP BY cost_center ORDER BY total_billed_cost DESC
          LIMIT {self._limit(limit)}""", month)

    def charge_types(self, config, month):
        return self._grouped(config, "charge_category, charge_frequency", month)

    def resources(self, config, month, limit=25):
        return self._grouped(config, "resource_group_name, resource_name, region", month, limit)

    def resource_groups(self, config, month, limit=25):
        return self._grouped(config, "resource_group_name", month, limit,
                             ", COUNT(DISTINCT resource_id) AS resource_count")

    def subscriptions(self, config, month):
        return self._grouped(config, "subscription_id, subscription_name", month,
                             extra=", COUNT(DISTINCT resource_id) AS resource_count")

    def application_owners(self, config, month, limit=50):
        return self._grouped(config, """application_owner_id, application_owner_email,
            application_business_owner, application_code, application_name""", month, limit,
            ", COUNT(DISTINCT resource_id) AS resource_count")

    def portfolio_services(self, config):
        return self._grouped(config, "service_name", limit=30)

    def portfolio_resources(self, config):
        return self._grouped(config, "resource_group_name, resource_name, region", limit=30)

    def sku_costs(self, config):
        return self._grouped(config, "sku_id, meter_category, meter_name", limit=50)

    def _ops(self, config, body):
        self._validate(config)
        if self.context.portfolio_demo:
            raise SecurityError("Raw operational history is not published in portfolio demonstrations.")
        if not self.context.is_admin:
            raise SecurityError("Operations access is restricted to FinOps administrators.")
        # Recheck the live admin grant in SQL too, even if navigation was resolved earlier.
        return BoundQuery(body, tuple(viewer_parameters(self.context).items()))

    def data_quality(self, config, month):
        if not self.context.is_admin:
            raise SecurityError("Operations access is restricted to FinOps administrators.")
        return self._query(config, """SELECT COUNT(*) AS total_rows,
            SUM(CASE WHEN billed_cost IS NULL THEN 1 ELSE 0 END) AS billed_cost_nulls,
            SUM(CASE WHEN billing_currency IS NULL THEN 1 ELSE 0 END) AS currency_nulls,
            SUM(CASE WHEN service_name IS NULL THEN 1 ELSE 0 END) AS service_nulls,
            COUNT(DISTINCT ingestion_run_id) AS batches,
            MAX(ingested_at) AS latest_silver_load,
            CASE WHEN COUNT(*) = 0 THEN 0 ELSE 100 * (1 - CAST(SUM(
              CASE WHEN billed_cost IS NULL THEN 1 ELSE 0 END +
              CASE WHEN billing_currency IS NULL THEN 1 ELSE 0 END +
              CASE WHEN service_name IS NULL THEN 1 ELSE 0 END) AS DOUBLE)
                / (3 * COUNT(*))) END AS critical_completeness_rate
            FROM authorized_rows WHERE billing_month = :billing_month""", month)

    def latest_pipeline_runs(self, config, limit=30):
        return self._ops(config, f"""WITH latest AS (
            SELECT *, row_number() OVER (
              PARTITION BY environment, pipeline_name, billing_month ORDER BY started_at DESC
            ) AS rn FROM {config.audit('pipeline_run')}
            WHERE environment = :viewer_environment AND {admin_predicate(config)}
        ) SELECT run_id, pipeline_name, billing_month, status, started_at, finished_at, message
          FROM latest WHERE rn = 1 ORDER BY started_at DESC LIMIT {self._limit(limit)}""")

    def latest_reconciliations(self, config, limit=24):
        return self._ops(config, f"""WITH latest AS (
            SELECT *, row_number() OVER (
              PARTITION BY environment, billing_month ORDER BY reconciled_at DESC
            ) AS rn FROM {config.audit('monthly_reconciliation')}
            WHERE environment = :viewer_environment AND {admin_predicate(config)}
        ) SELECT billing_month, status, billing_rows, after_rows,
          after_billing_difference, reconciled_at FROM latest WHERE rn = 1
          ORDER BY billing_month DESC LIMIT {self._limit(limit)}""")

    def environment_run_counts(self, config):
        return self._ops(config, f"""SELECT environment, COUNT(*) AS total_runs,
            SUM(CASE WHEN status = 'SUCCESS' THEN 1 ELSE 0 END) AS successful_runs,
            MAX(started_at) AS latest_run FROM {config.audit('pipeline_run')}
            WHERE environment = :viewer_environment AND {admin_predicate(config)}
            GROUP BY environment ORDER BY environment""")
