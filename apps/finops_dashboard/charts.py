"""Readable cost charts and period comparisons for the dashboard."""

from __future__ import annotations

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

from formatting import chart_layout, money


def service_cost_chart(frame: pd.DataFrame, title: str, order: str = "Highest cost first"):
    # One bar per service, even when it belongs to several source categories.
    totals = frame.groupby("service_name", dropna=False, as_index=False)[
        "total_billed_cost"
    ].sum()
    if order == "Name A–Z":
        totals = totals.sort_values("service_name")
    else:
        totals = totals.sort_values(
            "total_billed_cost", ascending=order == "Lowest cost first"
        )
    figure = px.bar(
        totals, x="total_billed_cost", y="service_name", orientation="h",
        title=title, labels={"total_billed_cost": "Billed cost (€)", "service_name": "Service"},
        color_discrete_sequence=["#0078d4"],
    )
    figure.update_yaxes(
        categoryorder="array", categoryarray=totals["service_name"].tolist(),
        autorange="reversed",
    )
    figure.update_traces(
        customdata=[[money(value)] for value in totals["total_billed_cost"]],
        hovertemplate="%{y}<br>Billed cost: %{customdata[0]}<extra></extra>",
    )
    figure.update_layout(showlegend=False)
    return chart_layout(figure, max(360, min(900, 90 + 24 * len(totals))))


def charge_cost_chart(frame: pd.DataFrame):
    totals = frame.groupby("charge_category", dropna=False, as_index=False)[
        "total_billed_cost"
    ].sum().sort_values("total_billed_cost", ascending=False)
    totals["charge_category"] = totals["charge_category"].fillna("Not specified")
    figure = px.bar(
        totals, x="total_billed_cost", y="charge_category", orientation="h",
        title="What makes up the bill?",
        labels={"total_billed_cost": "Billed cost (€)", "charge_category": "Charge category"},
        color_discrete_sequence=["#0078d4"],
    )
    figure.update_yaxes(
        categoryorder="array", categoryarray=totals["charge_category"].tolist(),
        autorange="reversed",
    )
    figure.update_traces(
        text=[money(value) for value in totals["total_billed_cost"]],
        textposition="auto", cliponaxis=False,
        hovertemplate="%{y}<br>%{text}<extra></extra>",
    )
    return chart_layout(figure, 520)


def cost_bridge(savings: pd.Series):
    list_cost = float(savings["list_cost"])
    contracted = float(savings["contracted_cost"])
    effective = float(savings["effective_cost"])
    negotiated_step = contracted - list_cost
    commitment_step = effective - contracted
    figure = go.Figure(go.Waterfall(
        x=["List cost", "Negotiated-price effect", "Commitment / allocation effect", "Effective cost"],
        measure=["absolute", "relative", "relative", "total"],
        y=[list_cost, negotiated_step, commitment_step, 0],
        text=[money(value) for value in (list_cost, negotiated_step, commitment_step, effective)],
        textposition="outside", cliponaxis=False,
        customdata=[money(value) for value in (list_cost, contracted, effective, effective)],
        hovertemplate="%{x}<br>Step: %{text}<br>Cost after step: %{customdata}<extra></extra>",
        decreasing={"marker": {"color": "#107c10"}},
        increasing={"marker": {"color": "#d97706"}},
        totals={"marker": {"color": "#0078d4"}},
        connector={"line": {"color": "#a19f9d"}},
    ))
    figure.update_layout(title="From list price to effective cost", yaxis_title="Cost (€)")
    return chart_layout(figure, 420)


def savings_cost_chart(frame: pd.DataFrame):
    """Stack effective cost and its list-price gap, never stack full cost bases."""
    costs = frame.sort_values("billing_month").copy()
    bases = ["list_cost", "effective_cost"]
    for column in bases:
        costs[column] = pd.to_numeric(costs[column], errors="coerce")
    costs["price_benefit"] = costs["list_cost"] - costs["effective_cost"]
    # Credits, missing values and net cost increases must not become fake savings.
    stacked = bool(
        not costs.empty
        and costs[bases].notna().all().all()
        and (costs[bases] >= 0).all().all()
        and (costs["price_benefit"] >= 0).all()
    )
    figure = go.Figure()
    for column, name, color in (
        ("effective_cost", "Effective Cost", "#005a9e"),
        ("price_benefit", "Net Price Benefit", "#8fd5a6"),
    ):
        figure.add_trace(go.Bar(
            x=costs["billing_month"], y=costs[column], name=name, marker_color=color,
            customdata=[
                [money(value) if pd.notna(value) else "Unavailable"]
                for value in costs[column]
            ],
            hovertemplate=f"%{{x}}<br>{name}: %{{customdata[0]}}<extra></extra>",
        ))
    figure.update_layout(
        barmode="stack" if stacked else "group", title="Net Price Benefit",
    )
    figure.update_xaxes(title="Month", type="category")
    figure.update_yaxes(title="Cost (€)")
    return chart_layout(figure, 440), stacked


def year_history(frame: pd.DataFrame, year: str) -> pd.DataFrame:
    months = frame["billing_month"].astype(str)
    return frame.loc[months.str.startswith(f"{year}-")].copy().sort_values("billing_month")


def comparable_years(frame: pd.DataFrame, year: str, other_year: str):
    """Compare only month numbers present in both years; never fill gaps with zero."""
    current = year_history(frame, year)
    previous = year_history(frame, other_year)
    current["month_number"] = current["billing_month"].astype(str).str[5:7]
    previous["month_number"] = previous["billing_month"].astype(str).str[5:7]
    common = sorted(set(current["month_number"]) & set(previous["month_number"]))
    return (
        current[current["month_number"].isin(common)].copy(),
        previous[previous["month_number"].isin(common)].copy(),
        common,
    )
