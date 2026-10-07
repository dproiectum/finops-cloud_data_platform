"""Project costs are published snapshots, not selectable-profile telemetry."""

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from formatting import COST_BLUE, SAVINGS_GREEN, chart_layout, measurement_number
from .model import amount, load_snapshot, provider_total


def cost_trend(frame, currency):
    figure = go.Figure()
    for provider, label, color in (
        ("GCP", "GCP · Net Cost", COST_BLUE),
        ("Databricks", "Databricks · List Cost Estimate", SAVINGS_GREEN),
    ):
        rows = frame[frame["provider"] == provider]
        if rows.empty:
            continue
        totals = rows.groupby("month", as_index=False)["reported_cost"].sum().sort_values("month")
        figure.add_trace(go.Bar(
            x=totals["month"], y=[float(value) for value in totals["reported_cost"]],
            name=label, marker_color=color,
            customdata=[[amount(value, currency)] for value in totals["reported_cost"]],
            hovertemplate="%{x}<br>%{customdata[0]}<extra>%{fullData.name}</extra>",
        ))
    figure.update_layout(title="Monthly Project Costs", barmode="group")
    figure.update_xaxes(type="category", title="Usage Month")
    figure.update_yaxes(title=f"Cost ({currency})")
    return chart_layout(figure, 410)


def render_project_costs(*, embedded=False):
    if embedded:
        st.subheader("Project Costs")
    else:
        st.markdown('<div class="finops-kicker">FINOPS · PLATFORM OPERATIONS</div>', unsafe_allow_html=True)
        st.title("Project Costs")
    st.write("The cost of operating this FinOps platform, separate from its synthetic Azure portfolio.")
    overview, methodology = st.tabs(["Cost Overview", "Scope & Method"])
    with overview:
        try:
            as_of, frame = load_snapshot()
        except (ValueError, OSError):
            # No raw values, filesystem paths or rejected records in the public UI.
            st.error("The project cost snapshot is unavailable or failed validation.")
            frame = pd.DataFrame()
            as_of = None
        if frame.empty:
            st.info("No approved cost snapshot is published yet. Unavailable costs are not zero.")
            st.write("This page will show monthly GCP costs, credits and Databricks DBU estimates once the aggregated exports have been reviewed.")
        else:
            st.caption(f"Reviewed snapshot · extracted {as_of} · not a live billing feed")
            controls = st.columns(3)
            currency = controls[0].selectbox("Currency", sorted(frame["currency"].unique()), key="project_cost_currency")
            frame = frame[frame["currency"] == currency]
            year = controls[1].selectbox("Cost Year", ["All Available Years", *sorted(frame["month"].str[:4].unique(), reverse=True)], key="project_cost_year")
            if year != "All Available Years":
                frame = frame[frame["month"].str.startswith(year + "-")]
            month = controls[2].selectbox("Cost Month", ["All Available Months", *sorted(frame["month"].unique(), reverse=True)], key="project_cost_month")
            selected = frame if month == "All Available Months" else frame[frame["month"] == month]
            metrics = st.columns(4)
            metrics[0].metric("GCP Cost Before Credits", amount(provider_total(selected, "GCP", "cost_before_credits"), currency))
            metrics[1].metric("GCP Net Cost", amount(provider_total(selected, "GCP", "reported_cost"), currency))
            dbus = provider_total(selected, "Databricks", "usage_quantity")
            metrics[2].metric("Databricks Net DBUs", "—" if dbus is None else measurement_number(dbus))
            metrics[3].metric("Databricks List Cost Estimate", amount(provider_total(selected, "Databricks", "reported_cost"), currency))
            if (selected["period_status"] == "partial").any():
                st.caption("Partial periods are included. A shorter month must not be interpreted as an efficiency gain.")
            st.plotly_chart(cost_trend(frame, currency), width="stretch")
            st.caption("GCP billing-export costs and Databricks list-price estimates use different cost bases. They are not added into a billed total.")
            st.subheader("Service Breakdown")
            breakdown = selected.groupby(["provider", "service"], as_index=False)["reported_cost"].sum().sort_values("reported_cost", ascending=False)
            figure = go.Figure(go.Bar(
                x=[float(value) for value in breakdown["reported_cost"]],
                y=breakdown["provider"] + " · " + breakdown["service"], orientation="h",
                marker_color=[COST_BLUE if provider == "GCP" else SAVINGS_GREEN for provider in breakdown["provider"]],
                customdata=[[amount(value, currency)] for value in breakdown["reported_cost"]],
                hovertemplate="%{y}<br>%{customdata[0]}<extra></extra>",
            ))
            figure.update_yaxes(autorange="reversed")
            figure.update_xaxes(title=f"Reported Cost ({currency})")
            st.plotly_chart(chart_layout(figure, max(350, 28 * len(breakdown) + 90)), width="stretch")
            st.subheader("Detailed Cost Table")
            detail = selected.rename(columns={
                "month": "Usage Month", "provider": "Provider", "service": "Service / SKU",
                "currency": "Currency", "cost_before_credits": "Cost Before Credits",
                "credits": "Credits", "usage_quantity": "Net DBUs", "cost_basis": "Cost Basis",
                "period_status": "Period Status", "reported_cost": "Reported Cost",
            }).drop(columns="usage_unit")
            detail["Cost Basis"] = detail["Cost Basis"].map({"billing_export": "GCP Billing Export", "list_estimate": "Databricks List Estimate"})
            detail["Period Status"] = detail["Period Status"].str.title()
            styled = detail.style.format({
                column: lambda value: amount(value, currency)
                for column in ("Cost Before Credits", "Credits", "Reported Cost")
            }, na_rep="—").format({"Net DBUs": measurement_number}, na_rep="—")
            st.dataframe(styled, hide_index=True, width="stretch")
    with methodology:
        st.subheader("FinOps Applied to the Platform Itself")
        st.write("Monthly service aggregates describe the selected GCP project and the two project Databricks workspaces. They are not exact per-job allocations or a controlled Frankfurt–Belgium benchmark.")
        st.markdown("- **GCP Net Cost = Cost Before Credits + Signed Credits.** Credits normally reduce cost; corrections remain signed.\n- **Databricks List Cost Estimate = Σ (signed DBUs × applicable published price).** This is not an invoice or the amount paid after trial credits, discounts or taxes.\n- **No currency conversion or combined invoice total.** If Databricks charges also appear in GCP Marketplace billing, adding the two sources would count them twice.\n- **Partial months and missing values remain visible.** A real zero is displayed as zero; an absent source is unavailable.")
        st.write("The public page reads only a reviewed, bundled snapshot. It cannot query live billing tables, reveal resource identifiers, or widen access when a demonstration profile changes.")
        st.caption("Platform sustainability belongs in this project section. Databricks emissions are not estimated: DBUs alone do not provide energy consumption or a supported conversion to kgCO₂e.")
        st.markdown("Sources: [Google Cloud Billing export queries](https://docs.cloud.google.com/billing/docs/how-to/bq-examples) · [Databricks pricing system table](https://docs.databricks.com/gcp/en/admin/system-tables/pricing)")
