"""Shared presentation helpers."""

from __future__ import annotations

import pandas as pd


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


def financial_table(frame: pd.DataFrame):
    """Format known measures for display without converting numeric data to text."""
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
    return frame.style.format(
        {column: formatter for column, formatter in formatters.items() if column in frame},
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
            axis.update(tickformat=",.0f", hoverformat=",.2f")
    return figure
