"""Shared presentation helpers."""

from __future__ import annotations

import pandas as pd


SAVINGS_COMPONENTS = (
    "reservation", "savings_plan", "usage_on_demand", "usage_dynamic", "adjustment",
)
SAVINGS_DETAIL_COLUMNS = {
    "billing_month": "Billing Month",
    "list_cost": "List Cost",
    "contracted_cost": "Contract Cost",
    "negotiated_savings": "Negotiated Savings",
    "reservation": "Reservation",
    "savings_plan": "Savings Plan",
    "usage_on_demand": "Usage On-Demand",
    "usage_dynamic": "Usage Dynamic",
    "adjustment": "Adjustment",
    "effective_cost": "Effective Cost",
    "total_savings": "Realized Savings",
    "savings_rate": "Saving Rate",
}


def decimal_number(value: object, *, signed: bool = False) -> str:
    if value is None or pd.isna(value):
        value = 0
    rendered = f"{float(value):+,.2f}" if signed else f"{float(value):,.2f}"
    return rendered.translate(str.maketrans({",": "\u202f", ".": ","}))


def money(value: object) -> str:
    return f"{decimal_number(value)} €"


def integer(value: object) -> str:
    if value is None or pd.isna(value):
        value = 0
    return f"{int(value):,}".replace(",", "\u202f")


def percent(value: object, *, signed: bool = False) -> str:
    return f"{decimal_number(value, signed=signed)} %"


def measurement_number(value: object) -> str:
    """Two-decimal European display only; missing is not zero, source values stay exact."""
    if value is None or pd.isna(value):
        return '—'
    return decimal_number(value)


def consumption_table(frame: pd.DataFrame):
    """Readable measures on a copy, with source precision and signed values retained."""
    labels = {column: column_label(column) for column in frame.columns}
    display = frame.rename(columns=labels)
    formatters = {}
    for column in frame.columns:
        if column in {'consumed_quantity', 'net_dbu', 'scenario_vm_hours',
                      'scenario_energy_kwh', 'scenario_kgco2e', 'comparison_kgco2e'}:
            formatters[labels[column]] = measurement_number
        elif column.endswith('_rows') or column == 'billing_records':
            formatters[labels[column]] = integer
        elif column.endswith('_date'):
            formatters[labels[column]] = lambda value: pd.to_datetime(value).strftime('%d/%m/%Y')
    return display.style.format(formatters, na_rep='—')


def column_label(column: object) -> str:
    """Business-facing headers only; source/query identifiers stay unchanged."""
    aliases = {
        "average_cost_per_resource": "Average by Resource",
        "savings_vs_list": "Savings vs. Catalog Price",
        "total_savings": "Realized Savings",
        "total_savings_vs_list": "Total Savings vs. List Price",
        "contracted_cost": "Contract Cost",
        "savings_rate": "Saving Rate",
        "usage_on_demand": "Usage On-Demand",
        "month_change_rate": "Month-over-Month Change Rate",
        "critical_completeness_rate": "Critical Completeness Rate",
        "net_dbu": "Net DBUs",
        "is_genie_free_usage": "Genie Free Usage",
        "missing_measurement_rows": "Missing Measurements",
        "scenario_vm_hours": "Modelled VM Billing Hours",
        "scenario_energy_kwh": "Scenario Energy (kWh)",
        "scenario_kgco2e": "Illustrative Emissions (kgCO₂e)",
        "comparison_kgco2e": "Comparison Scenario (kgCO₂e)",
    }
    name = str(column)
    if name in aliases:
        return aliases[name]
    acronyms = {"id": "ID", "ids": "IDs", "sku": "SKU", "skus": "SKUs",
                "sql": "SQL", "kpi": "KPI", "dbu": "DBU", "url": "URL",
                "dev": "DEV", "prod": "PROD", "ops": "OPS"}
    return " ".join(acronyms.get(word.lower(), word.capitalize())
                    for word in name.replace("_", " ").split())


def comparison_state(value: object) -> str:
    """Do not paint a cost increase, zero or missing value as a benefit."""
    if value is None or pd.isna(value) or value == 0:
        return "neutral"
    return "positive" if value > 0 else "negative"


def financial_table(frame: pd.DataFrame):
    """Readable headers and European measures on a copy, never on source data."""
    formatters = {
        "total_billed_cost": money,
        "billed_cost": money,
        "monthly_billed_cost": money,
        "daily_billed_cost": money,
        "effective_cost": money,
        "list_cost": money,
        "contracted_cost": money,
        "savings_vs_list": money,
        "negotiated_savings": money,
        "commitment_savings": money,
        "total_savings": money,
        "savings_rate": percent,
        "charge_lines": integer,
        "resources": integer,
        "services": integer,
        "after_billing_difference": money,
        "resource_count": integer,
        "billing_rows": integer,
        "after_rows": integer,
        "total_runs": integer,
        "successful_runs": integer,
        "Value": integer,  # Count-only quality-control table.
    }
    labels = {column: column_label(column) for column in frame.columns}
    display = frame.rename(columns=labels)
    return display.style.format(
        {labels[column]: formatter for column, formatter in formatters.items() if column in frame},
        na_rep="—",
    )


def savings_detail_table(frame: pd.DataFrame):
    """Show ordered business labels; missing new measures stay unavailable."""
    columns = dict(SAVINGS_DETAIL_COLUMNS)
    if "other_effective_cost" in frame and (
        pd.to_numeric(frame["other_effective_cost"], errors="coerce").fillna(0).ne(0).any()
    ):
        # Future tax/credit/purchase or unclassified charges must not disappear.
        columns = {
            **{key: value for key, value in columns.items()
               if key not in {"effective_cost", "total_savings", "savings_rate"}},
            "other_effective_cost": "Other Charges",
            "effective_cost": "Effective Cost",
            "total_savings": "Realized Savings",
            "savings_rate": "Saving Rate",
        }
    detail = frame.reindex(columns=columns).rename(columns=columns)
    return detail.style.format(
        {label: percent if key == "savings_rate" else money
         for key, label in columns.items() if key != "billing_month"},
        na_rep="—",
    )


def chart_layout(figure, height: int = 360):
    figure.update_layout(
        height=height,
        margin=dict(l=12, r=12, t=48, b=12),
        paper_bgcolor="#ffffff",
        plot_bgcolor="#ffffff",
        font=dict(color="#424242"),
        title_font=dict(color="#242424", size=17),
        xaxis=dict(gridcolor="#edebe9", linecolor="#d2d0ce"),
        yaxis=dict(gridcolor="#edebe9", linecolor="#d2d0ce"),
        legend_title_text="",
        separators=",\u202f",
    )
    for axis_name in ("xaxis", "yaxis"):
        axis = getattr(figure.layout, axis_name)
        if axis.title.text and "€" in axis.title.text:
            axis.update(tickformat=",.2f", hoverformat=",.2f")
    return figure
