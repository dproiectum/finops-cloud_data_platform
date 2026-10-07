"""Readable cost charts and period comparisons for the dashboard."""

from __future__ import annotations

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

from formatting import COST_BLUE, SAVINGS_GREEN, chart_layout, money


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
        title=title, labels={"total_billed_cost": "Billed Cost (€)", "service_name": "Service"},
        color_discrete_sequence=[COST_BLUE],
    )
    figure.update_yaxes(
        categoryorder="array", categoryarray=totals["service_name"].tolist(),
        autorange="reversed",
    )
    figure.update_traces(
        customdata=[[money(value)] for value in totals["total_billed_cost"]],
        hovertemplate="%{y}<br>Billed Cost: %{customdata[0]}<extra></extra>",
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
        title="Billed Cost by Charge Category",
        labels={"total_billed_cost": "Billed Cost (€)", "charge_category": "Charge Category"},
        color_discrete_sequence=[COST_BLUE],
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
        x=["List Cost", "Negotiated Price Effect", "Commitment / Allocation Effect", "Effective Cost"],
        measure=["absolute", "relative", "relative", "total"],
        y=[list_cost, negotiated_step, commitment_step, 0],
        text=[money(value) for value in (list_cost, negotiated_step, commitment_step, effective)],
        textposition="outside", cliponaxis=False,
        customdata=[money(value) for value in (list_cost, contracted, effective, effective)],
        hovertemplate="%{x}<br>Step: %{text}<br>Cost After Step: %{customdata}<extra></extra>",
        decreasing={"marker": {"color": SAVINGS_GREEN}},
        increasing={"marker": {"color": "#d97706"}},
        totals={"marker": {"color": COST_BLUE}},
        connector={"line": {"color": "#a19f9d"}},
    ))
    figure.update_layout(title="From List Price to Effective Cost", yaxis_title="Cost (€)")
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
        ("effective_cost", "Effective Cost", COST_BLUE),
        ("price_benefit", "Realized Savings", SAVINGS_GREEN),
    ):
        figure.add_trace(go.Bar(
            x=costs["billing_month"], y=costs[column], name=name, marker_color=color,
            customdata=[
                [money(value) if pd.notna(value) else "Unavailable",
                 money(list_cost) if pd.notna(list_cost) else "Unavailable"]
                for value, list_cost in zip(costs[column], costs["list_cost"])
            ],
            hovertemplate=(
                "%{x}<br>List Cost: %{customdata[1]}"
                "<br>Realized Savings: %{customdata[0]}<extra></extra>"
                if column == "price_benefit"
                else "%{x}<br>Effective Cost: %{customdata[0]}<extra></extra>"
            ),
        ))
    figure.update_layout(
        barmode="stack" if stacked else "group", title="Realized Savings",
    )
    figure.update_xaxes(title="Month", type="category")
    figure.update_yaxes(title="Cost (€)")
    return chart_layout(figure, 440), stacked


def lineage_chart() -> go.Figure:
    """Public lineage structure and palette with a stable, readable layout."""
    labels = ["GCS Parquet", "RAW Volume", "Bronze", "FOCUS Contract", "Silver",
              "Gold", "Datamarts", "Streamlit", "OPS Audit"]
    links = [(0, 1), (1, 2), (2, 3), (3, 4), (4, 5), (5, 6), (6, 7),
             (2, 8), (4, 8), (5, 8)]
    figure = go.Figure(go.Sankey(
        arrangement="fixed",
        textfont=dict(color="#424242", size=14, shadow="none"),
        node=dict(
            label=labels,
            # Keep the audit branch above the main chain. Automatic Sankey
            # placement varies across Plotly/front-end versions and viewport sizes.
            x=[.01, .14, .28, .42, .56, .70, .84, .99, .99],
            y=[.125, .125, .25, .375, .50, .75, .875, .875, .375],
            color=["#0078d4", "#2b88d8", "#2b88d8", "#71afe5", "#71afe5",
                   "#00a4ef", "#50e6ff", "#deecf9", "#8764b8"],
            pad=24, thickness=24, line=dict(color="#005a9e", width=1),
        ),
        link=dict(source=[source for source, _ in links],
                  target=[target for _, target in links],
                  value=[1] * len(links), color="rgba(0,120,212,.20)"),
    ))
    figure.update_layout(
        template="none", height=590, margin=dict(l=12, r=12, t=48, b=12),
        paper_bgcolor="#ffffff", plot_bgcolor="#ffffff",
        font=dict(color="#424242"), title_font=dict(color="#242424", size=17),
        legend_title_text="", separators=",\u202f",
    )
    return figure


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
