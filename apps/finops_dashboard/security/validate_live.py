"""Optional read-only live checks of the two seeded synthetic application scopes.

Run manually from apps/finops_dashboard with a Belgian Databricks profile.
Does not change grants, entitlements, Cloud Run, or business tables.
"""

from __future__ import annotations

import argparse
from decimal import Decimal
import re

from config import DashboardConfig
from data_access import DatabricksDataSource
from .authorization import resolve_access
from .identity import SecurityError, demo_identity
from .queries import ScopedQueries


def validate(source, config, month: str) -> list[dict]:
    if not re.fullmatch(r"[0-9]{4}-(0[1-9]|1[0-2])", month):
        raise ValueError("month must use YYYY-MM")
    if config.environment != "prod" or config.data_catalog != "finops_prod":
        raise ValueError("This seed-specific validation targets the confirmed PROD demo dataset")
    try:
        resolve_access(source, config, demo_identity("demo-no-access"))
    except SecurityError:
        pass
    else:
        raise AssertionError("demo-no-access unexpectedly has access")

    evidence = []
    for principal, application in [
        ("demo-app-owner-a", "APP00013057"),
        ("demo-app-owner-b", "BSN0003965"),
    ]:
        context = resolve_access(source, config, demo_identity(principal))
        if context.is_admin:
            raise AssertionError("Application owner unexpectedly has a global role")
        query = ScopedQueries(context)
        owners_query = query.application_owners(config, month)
        owners = source.query(owners_query.text, owners_query.parameters)
        if owners.empty or set(owners["application_code"]) != {application}:
            raise AssertionError("Owner/export query does not match its expected application")
        scoped_query = query.savings_summary(config, month)
        scoped = source.query(scoped_query.text, scoped_query.parameters)
        reference = source.query(f"""
            SELECT COUNT(*) AS charge_lines,
                   coalesce(SUM(billed_cost), 0) AS billed_cost,
                   coalesce(SUM(list_cost), 0) AS list_cost,
                   coalesce(SUM(contracted_cost), 0) AS contracted_cost,
                   coalesce(SUM(effective_cost), 0) AS effective_cost
            FROM {config.datamart('v_dashboard_charge_scoped')}
            WHERE environment = :environment AND application_code = :application
              AND billing_month = :month
        """, {"environment": config.environment, "application": application, "month": month})
        if len(scoped) != 1 or reference.iloc[0]["charge_lines"] == 0:
            raise AssertionError("Select a billing month with charges for both applications")
        for column in ("list_cost", "contracted_cost", "effective_cost"):
            if abs(Decimal(str(scoped.iloc[0][column]))
                   - Decimal(str(reference.iloc[0][column]))) > Decimal("0.000001"):
                raise AssertionError(f"Scoped {column} does not match the exact application subset")
        summary_query = query.executive_summary(config, month)
        summary = source.query(summary_query.text, summary_query.parameters)
        if len(summary) != 1 or summary.iloc[0]["charge_lines"] != reference.iloc[0]["charge_lines"]:
            raise AssertionError("Scoped executive charge count differs from reference")
        if abs(Decimal(str(summary.iloc[0]["billed_cost"]))
               - Decimal(str(reference.iloc[0]["billed_cost"]))) > Decimal("0.000001"):
            raise AssertionError("Scoped billed cost differs from reference")
        try:
            query.latest_pipeline_runs(config)
        except SecurityError:
            pass
        else:
            raise AssertionError("Application owner unexpectedly has OPS access")
        evidence.append({
            "principal": principal, "application": application, "month": month,
            "charge_lines": int(reference.iloc[0]["charge_lines"]),
            "billed_cost": str(reference.iloc[0]["billed_cost"]),
            "effective_cost": str(scoped.iloc[0]["effective_cost"]),
            "status": "PASSED",
        })
    return evidence


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--month", required=True, help="Loaded billing month YYYY-MM")
    args = parser.parse_args()
    try:
        results = validate(DatabricksDataSource(), DashboardConfig.from_environment(), args.month)
    except Exception:
        # Do not expose connector errors with configuration details or token data.
        raise SystemExit("FAILED: check SQL setup, Belgian profile and the selected month") from None
    for result in results:
        print(result)
    print("PASS: live query isolation and reference totals; IAP/browser deployment not tested")


if __name__ == "__main__":
    main()
