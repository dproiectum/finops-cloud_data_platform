"""FinOps Control Center backed by certified PROD Databricks data products."""

from __future__ import annotations

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from config import DashboardConfig
from data_access import DatabricksDataSource
from formatting import chart_layout, integer, money, percent
from knowledge import cost_formulas, focus_columns, glossary
import queries


st.set_page_config(
    page_title="FinOps Control Center",
    page_icon="◈",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
    <style>
    :root { --azure:#0078d4; --azure-dark:#005a9e; --surface:#ffffff; --canvas:#f5f5f5; }
    .stApp { background:#f5f5f5; }
    [data-testid="stSidebar"] { background:#ffffff; border-right:1px solid #e1dfdd; }
    [data-testid="stMetric"] {
      background:#ffffff; border:1px solid #e1dfdd; border-radius:6px;
      padding:15px 17px; box-shadow:0 1px 3px rgba(0,0,0,.08);
    }
    [data-testid="stMetricValue"] { color:#242424; }
    [data-testid="stMetricLabel"] { color:#605e5c; }
    h1, h2, h3 { color:#242424 !important; letter-spacing:-.02em; }
    .finops-kicker { color:#0078d4; font-weight:700; letter-spacing:.11em; font-size:.78rem; }
    .finops-subtitle { color:#605e5c; margin-top:-.7rem; margin-bottom:1.2rem; }
    .status-pill {
      display:inline-block; padding:.3rem .65rem; border-radius:999px;
      color:#005a9e; background:#eff6fc; border:1px solid #c7e0f4; font-size:.82rem;
    }
    .architecture-card {
      background:#ffffff; border:1px solid #e1dfdd; border-top:4px solid #0078d4;
      border-radius:6px; padding:18px; min-height:132px;
      box-shadow:0 1px 3px rgba(0,0,0,.06);
    }
    .architecture-card h4 { color:#242424; margin:0 0 8px 0; }
    .architecture-card p { color:#605e5c; margin:0; line-height:1.45; }
    div[data-testid="stPlotlyChart"], div[data-testid="stDataFrame"] {
      background:#ffffff; border:1px solid #e1dfdd; border-radius:6px;
      box-shadow:0 1px 3px rgba(0,0,0,.06); padding:4px;
    }
    </style>
    """,
    unsafe_allow_html=True,
)


@st.cache_resource
def build_source() -> DatabricksDataSource:
    result = DatabricksDataSource()
    result.healthcheck()
    return result


try:
    config = DashboardConfig.from_environment()
    source = build_source()
except Exception as exc:
    st.error("Unable to connect to Databricks SQL")
    st.code(str(exc))
    st.stop()


@st.cache_data(ttl=300, show_spinner=False)
def load_frame(sql_text: str) -> pd.DataFrame:
    return source.query(sql_text)


def require_row(frame: pd.DataFrame, subject: str) -> pd.Series:
    if frame.empty:
        st.warning(f"No certified {subject} data is available for this selection.")
        st.stop()
    return frame.iloc[0]


PAGES = [
    "Knowledge Base",
    "Executive Overview",
    "Cost Drivers",
    "Savings",
    "Allocation & Accountability",
    "Resources",
    "Operations & Quality",
    "Architecture",
]

with st.sidebar:
    st.markdown("### FinOps Control Center")
    st.caption("Certified cloud cost intelligence")
    st.markdown(
        f'<span class="status-pill">{source.label} · {config.environment.upper()}</span>',
        unsafe_allow_html=True,
    )
    st.divider()
    page = st.radio("Navigation", PAGES, label_visibility="collapsed")
    needs_month = page not in {"Knowledge Base", "Architecture"}
    selected_month = None
    if needs_month:
        try:
            month_frame = load_frame(queries.available_months(config))
            months = month_frame["billing_month"].astype(str).tolist()
        except Exception as exc:
            st.error("Certified datamarts are unavailable")
            st.code(str(exc))
            st.stop()
        if not months:
            st.warning("No billing month is available")
            st.stop()
        selected_month = st.selectbox("Billing month", months, index=0)
    st.divider()
    st.caption(f"Catalog: {config.data_catalog}")
    st.caption("Read-only · certified datamarts")


def page_title(kicker: str, title: str, subtitle: str | None = None) -> None:
    st.markdown(f'<div class="finops-kicker">{kicker}</div>', unsafe_allow_html=True)
    st.title(title)
    if subtitle:
        st.markdown(f'<div class="finops-subtitle">{subtitle}</div>', unsafe_allow_html=True)


def knowledge_page() -> None:
    page_title("FINOPS · FOCUS · GOVERNANCE", "Knowledge Base")
    st.write(
        "This section defines the columns, calculations and FinOps terminology used "
        "throughout the dashboard. The same definitions must be used in SQL, reports "
        "and project demonstrations."
    )
    formula_tab, columns_tab, glossary_tab, lifecycle_tab = st.tabs(
        ["Cost formulas", "FOCUS columns", "FinOps glossary", "Operating lifecycle"]
    )
    with formula_tab:
        st.subheader("Cost and KPI formulas")
        st.dataframe(cost_formulas(), hide_index=True, width="stretch")
        st.warning(
            "ListCost − EffectiveCost is a technical price comparison. It must not be "
            "presented as verified organizational or cash savings without eligibility "
            "rules, exclusions and an approved business baseline."
        )
        st.markdown(
            "Negative costs are retained because credits, refunds and adjustments are "
            "valid FOCUS records. A negative commitment difference is therefore shown, "
            "not hidden or forced to zero."
        )
    with columns_tab:
        st.subheader("FOCUS and platform column dictionary")
        dictionary = focus_columns()
        families = ["All", *sorted(dictionary["Family"].unique())]
        family = st.selectbox("Column family", families)
        if family != "All":
            dictionary = dictionary[dictionary["Family"] == family]
        st.dataframe(dictionary, hide_index=True, width="stretch")
        st.caption(
            "FOCUS columns retain their standard PascalCase names. Technical lineage "
            "columns begin with an underscore. Azure extensions begin with x_."
        )
    with glossary_tab:
        st.subheader("Terms used by the dashboard")
        st.dataframe(glossary(), hide_index=True, width="stretch")
    with lifecycle_tab:
        columns = st.columns(3)
        for column, title, description in zip(
            columns,
            ["Inform", "Optimize", "Operate"],
            [
                "Create visibility, allocation and a shared understanding of cloud cost.",
                "Identify and prioritize efficiency and value opportunities.",
                "Embed ownership, controls and monitoring into recurring processes.",
            ],
        ):
            column.markdown(
                f'<div class="architecture-card"><h4>{title}</h4><p>{description}</p></div>',
                unsafe_allow_html=True,
            )
        st.info(
            "The current application primarily demonstrates Inform. Savings indicators "
            "support investigation but do not yet prove realized business savings."
        )


def executive_page(month: str) -> None:
    page_title("AZURE FINOPS · EXECUTIVE", "Executive Overview", f"Selected period: {month}")
    summary = require_row(
        load_frame(queries.executive_summary(config, month)), "executive summary"
    )
    savings = require_row(load_frame(queries.savings_summary(config, month)), "savings")
    delta = None
    if not pd.isna(summary["month_change_rate"]):
        delta = f"{float(summary['month_change_rate']):+.2f}% MoM"

    primary = st.columns(4)
    primary[0].metric("Billed cost", money(summary["billed_cost"]), delta=delta)
    primary[1].metric("Effective cost", money(summary["effective_cost"]))
    primary[2].metric("Difference vs list", money(summary["savings_vs_list"]))
    primary[3].metric("Difference rate", percent(savings["savings_rate"]))

    secondary = st.columns(4)
    secondary[0].metric("Charge lines", integer(summary["charge_lines"]))
    secondary[1].metric("Active resources", integer(summary["resources"]))
    secondary[2].metric("Consumed services", integer(summary["services"]))
    secondary[3].metric(
        "Average / resource", money(summary["average_cost_per_resource"])
    )

    daily = load_frame(queries.daily_trend(config, month))
    monthly = load_frame(queries.monthly_trend(config))
    left, right = st.columns([1.25, 1])
    with left:
        figure = px.area(
            daily,
            x="date",
            y="daily_billed_cost",
            title="Daily billed cost",
            labels={"date": "Date", "daily_billed_cost": "Billed cost (€)"},
            color_discrete_sequence=["#0078d4"],
        )
        figure.update_traces(line=dict(width=2), fillcolor="rgba(0,120,212,.16)")
        st.plotly_chart(chart_layout(figure), width="stretch")
    with right:
        figure = px.bar(
            monthly,
            x="billing_month",
            y="monthly_billed_cost",
            title="Monthly billed-cost trend",
            labels={"billing_month": "Month", "monthly_billed_cost": "Billed cost (€)"},
            color_discrete_sequence=["#00a4ef"],
        )
        st.plotly_chart(chart_layout(figure), width="stretch")


def cost_drivers_page(month: str) -> None:
    page_title("FINOPS · COST DRIVERS", "Cost Drivers", f"Selected period: {month}")
    services = load_frame(queries.services(config, month, 20))
    charges = load_frame(queries.charge_types(config, month))
    summary = require_row(load_frame(queries.executive_summary(config, month)), "summary")
    service_total = pd.to_numeric(services["total_billed_cost"], errors="coerce").sum()
    leading_share = 0.0
    if not services.empty and float(summary["billed_cost"] or 0) != 0:
        leading_share = 100 * float(services.iloc[0]["total_billed_cost"]) / abs(
            float(summary["billed_cost"])
        )
    cards = st.columns(3)
    cards[0].metric("Services represented", integer(len(services)))
    cards[1].metric("Top-service share", percent(leading_share))
    cards[2].metric("Displayed service cost", money(service_total))

    left, right = st.columns(2)
    with left:
        figure = px.bar(
            services.sort_values("total_billed_cost"),
            x="total_billed_cost",
            y="service_name",
            orientation="h",
            color="service_category",
            title="Top services for the selected month",
            labels={"total_billed_cost": "Cost (€)", "service_name": "Service"},
        )
        st.plotly_chart(chart_layout(figure, 520), width="stretch")
    with right:
        charge_summary = (
            charges.groupby("charge_category", dropna=False)["total_billed_cost"]
            .sum()
            .reset_index()
        )
        figure = px.bar(
            charge_summary,
            x="charge_category",
            y="total_billed_cost",
            title="Cost by charge category",
            labels={"total_billed_cost": "Cost (€)", "charge_category": "Category"},
            color_discrete_sequence=["#0078d4"],
        )
        st.plotly_chart(chart_layout(figure, 520), width="stretch")

    service_tab, sku_tab, charge_tab = st.tabs(
        ["Portfolio services", "Portfolio SKUs", "Charge details"]
    )
    with service_tab:
        st.caption("Cumulative view across all loaded months")
        st.dataframe(
            load_frame(queries.portfolio_services(config)), hide_index=True, width="stretch"
        )
    with sku_tab:
        st.caption("The current SKU datamart is cumulative across all loaded months")
        st.dataframe(load_frame(queries.sku_costs(config)), hide_index=True, width="stretch")
    with charge_tab:
        st.dataframe(charges, hide_index=True, width="stretch")


def savings_page(month: str) -> None:
    page_title("FINOPS · OPTIMIZE", "Savings Analysis", f"Selected period: {month}")
    savings = require_row(load_frame(queries.savings_summary(config, month)), "savings")
    history = load_frame(queries.monthly_savings(config))
    cards = st.columns(4)
    cards[0].metric("Negotiated difference", money(savings["negotiated_savings"]))
    cards[1].metric("Commitment difference", money(savings["commitment_savings"]))
    cards[2].metric("Total difference vs list", money(savings["total_savings"]))
    cards[3].metric("Difference rate", percent(savings["savings_rate"]))
    long_frame = history.melt(
        id_vars="billing_month",
        value_vars=["negotiated_savings", "commitment_savings"],
        var_name="comparison",
        value_name="amount",
    )
    long_frame["comparison"] = long_frame["comparison"].map(
        {
            "negotiated_savings": "List − Contracted",
            "commitment_savings": "Contracted − Effective",
        }
    )
    figure = px.bar(
        long_frame,
        x="billing_month",
        y="amount",
        color="comparison",
        barmode="relative",
        title="Monthly cost differences",
        labels={"billing_month": "Month", "amount": "Difference (€)"},
        color_discrete_map={
            "List − Contracted": "#0078d4",
            "Contracted − Effective": "#50e6ff",
        },
    )
    st.plotly_chart(chart_layout(figure, 440), width="stretch")
    st.warning(
        "These are technical comparisons between FOCUS cost columns. Negative values "
        "remain visible, and none of these indicators should be described as realized "
        "cash savings without a validated business baseline."
    )


def allocation_page(month: str) -> None:
    page_title(
        "FINOPS · ACCOUNTABILITY",
        "Allocation & Accountability",
        f"Selected period: {month}",
    )
    centers = load_frame(queries.cost_centers(config, month))
    subscriptions = load_frame(queries.subscriptions(config, month))
    owners = load_frame(queries.application_owners(config, month))
    services = load_frame(queries.services(config, month, 30))

    center_cost = pd.to_numeric(centers["total_billed_cost"], errors="coerce")
    allocated = center_cost[
        ~centers["cost_center"].fillna("").str.lower().isin({"", "unknown", "unallocated"})
    ].sum()
    total = center_cost.sum()
    coverage = 0 if total == 0 else 100 * float(allocated) / abs(float(total))
    cards = st.columns(3)
    cards[0].metric("Cost-center coverage", percent(coverage))
    cards[1].metric("Subscriptions", integer(len(subscriptions)))
    cards[2].metric("Application-owner rows", integer(len(owners)))

    service_tab, center_tab, subscription_tab, owner_tab = st.tabs(
        ["Services", "Cost centers", "Subscriptions", "Application owners"]
    )
    with service_tab:
        figure = px.bar(
            services.sort_values("total_billed_cost"),
            x="total_billed_cost",
            y="service_name",
            orientation="h",
            color="service_category",
            title="Service allocation",
        )
        st.plotly_chart(chart_layout(figure, 540), width="stretch")
    with center_tab:
        figure = px.treemap(
            centers,
            path=["cost_center"],
            values="total_billed_cost",
            color="total_billed_cost",
            color_continuous_scale=["#deecf9", "#71afe5", "#0078d4", "#005a9e"],
            title="Cost-center allocation",
        )
        st.plotly_chart(chart_layout(figure, 520), width="stretch")
        st.dataframe(centers, hide_index=True, width="stretch")
    with subscription_tab:
        st.dataframe(subscriptions, hide_index=True, width="stretch")
    with owner_tab:
        st.dataframe(owners, hide_index=True, width="stretch")


def resources_page(month: str) -> None:
    page_title("FINOPS · RESOURCES", "Resource Analysis", f"Selected period: {month}")
    resources = load_frame(queries.resources(config, month))
    groups = load_frame(queries.resource_groups(config, month))
    resource_cost = pd.to_numeric(resources["total_billed_cost"], errors="coerce")
    total = resource_cost.sum()
    top_five = resource_cost.head(5).sum()
    concentration = 0 if total == 0 else 100 * float(top_five) / abs(float(total))
    cards = st.columns(3)
    cards[0].metric("Resources displayed", integer(len(resources)))
    cards[1].metric("Top-5 concentration", percent(concentration))
    cards[2].metric("Resource groups", integer(len(groups)))
    resource_tab, group_tab, portfolio_tab = st.tabs(
        ["Resources", "Resource groups", "Portfolio totals"]
    )
    with resource_tab:
        figure = px.bar(
            resources.head(15).sort_values("total_billed_cost"),
            x="total_billed_cost",
            y="resource_name",
            orientation="h",
            color="region",
            title="Top resources by cost",
        )
        st.plotly_chart(chart_layout(figure, 560), width="stretch")
        st.dataframe(resources, hide_index=True, width="stretch")
    with group_tab:
        figure = px.bar(
            groups.head(20).sort_values("total_billed_cost"),
            x="total_billed_cost",
            y="resource_group_name",
            orientation="h",
            title="Cost by resource group",
            color_discrete_sequence=["#0078d4"],
        )
        st.plotly_chart(chart_layout(figure, 560), width="stretch")
        st.dataframe(groups, hide_index=True, width="stretch")
    with portfolio_tab:
        st.caption("Cumulative view across all loaded months")
        st.dataframe(
            load_frame(queries.portfolio_resources(config)),
            hide_index=True,
            width="stretch",
        )


def operations_page(month: str) -> None:
    page_title(
        "DATA PLATFORM · OPERATE",
        "Operations & Data Quality",
        f"Environment: {config.environment.upper()} · period: {month}",
    )
    quality = require_row(load_frame(queries.data_quality(config, month)), "quality")
    runs = load_frame(queries.latest_pipeline_runs(config))
    reconciliations = load_frame(queries.latest_reconciliations(config))
    counts = load_frame(queries.environment_run_counts(config))
    latest_status = "Unavailable" if runs.empty else str(runs.iloc[0]["status"])
    latest_reconciliation = (
        "Unavailable" if reconciliations.empty else str(reconciliations.iloc[0]["status"])
    )
    cards = st.columns(4)
    cards[0].metric("Critical completeness", percent(quality["critical_completeness_rate"]))
    cards[1].metric("Latest pipeline", latest_status)
    cards[2].metric("Latest reconciliation", latest_reconciliation)
    cards[3].metric("Batches in month", integer(quality["batches"]))

    quality_tab, runs_tab, reconciliation_tab, environments_tab = st.tabs(
        ["Data quality", "Pipeline runs", "Reconciliation", "DEV / PROD separation"]
    )
    with quality_tab:
        controls = pd.DataFrame(
            [
                ("Rows checked", quality["total_rows"]),
                ("Missing BilledCost", quality["billed_cost_nulls"]),
                ("Missing currency", quality["currency_nulls"]),
                ("Missing service", quality["service_nulls"]),
            ],
            columns=["Control", "Value"],
        )
        st.dataframe(controls, hide_index=True, width="stretch")
        st.write(f"Latest Silver publication: **{quality['latest_silver_load']}**")
    with runs_tab:
        st.dataframe(runs, hide_index=True, width="stretch")
    with reconciliation_tab:
        st.dataframe(reconciliations, hide_index=True, width="stretch")
    with environments_tab:
        st.dataframe(counts, hide_index=True, width="stretch")
        st.caption(
            "DEV and PROD share finops_ops.audit but remain isolated by the environment column."
        )


def architecture_page() -> None:
    page_title("DATA PLATFORM · ARCHITECTURE", "Architecture & Lineage")
    lineage_tab, layers_tab, products_tab = st.tabs(
        ["Data lineage", "Medallion layers", "Certified products"]
    )
    with lineage_tab:
        labels = [
            "GCS Parquet",
            "RAW Volume",
            "Bronze",
            "FOCUS Contract",
            "Silver",
            "Gold",
            "Datamarts",
            "Streamlit",
            "OPS audit",
        ]
        links = [(0, 1), (1, 2), (2, 3), (3, 4), (4, 5), (5, 6), (6, 7), (2, 8), (4, 8), (5, 8)]
        figure = go.Figure(
            go.Sankey(
                arrangement="snap",
                node=dict(
                    label=labels,
                    color=[
                        "#0078d4",
                        "#2b88d8",
                        "#2b88d8",
                        "#71afe5",
                        "#71afe5",
                        "#00a4ef",
                        "#50e6ff",
                        "#deecf9",
                        "#8764b8",
                    ],
                    pad=24,
                    thickness=24,
                    line=dict(color="#005a9e", width=1),
                ),
                link=dict(
                    source=[item[0] for item in links],
                    target=[item[1] for item in links],
                    value=[1] * len(links),
                    color="rgba(0,120,212,.20)",
                ),
            )
        )
        st.plotly_chart(chart_layout(figure, 590), width="stretch")
    with layers_tab:
        columns = st.columns(6)
        for column, title, description in zip(
            columns,
            ["RAW", "Bronze", "Contract", "Silver", "Gold", "Datamarts"],
            [
                "Shared external Parquet evidence",
                "Immutable ingestion and lineage",
                "FOCUS types and blocking quality rules",
                "Canonical and conformed records",
                "Dimensional model and monthly fact",
                "Certified business-facing aggregates",
            ],
        ):
            column.markdown(
                f'<div class="architecture-card"><h4>{title}</h4><p>{description}</p></div>',
                unsafe_allow_html=True,
            )
    with products_tab:
        st.dataframe(
            pd.DataFrame(
                [
                    ("Executive", "dm_executive_summary_monthly", "KPIs and activity"),
                    ("Savings", "dm_savings_monthly", "Cost-column comparisons"),
                    ("Trends", "dm_daily_billing; dm_monthly_billing", "Time series"),
                    ("Drivers", "dm_cost_by_charge_type; dm_top_services; dm_sku_cost", "Cost drivers"),
                    ("Allocation", "dm_cost_by_scope_service_month", "Service and cost center"),
                    (
                        "Resources",
                        "dm_top_resources_monthly; dm_cost_by_resource_group_month",
                        "Resource consumption",
                    ),
                    (
                        "Ownership",
                        "dm_cost_by_subscription_month; dm_cost_by_application_owner_month",
                        "Accountability",
                    ),
                    ("Quality", "dm_data_quality_monthly", "Completeness and freshness"),
                    ("Operations", "finops_ops.audit.*", "Runs, snapshots and reconciliation"),
                ],
                columns=["Subject", "Certified source", "Purpose"],
            ),
            hide_index=True,
            width="stretch",
        )


if page == "Knowledge Base":
    knowledge_page()
elif page == "Executive Overview":
    executive_page(selected_month)
elif page == "Cost Drivers":
    cost_drivers_page(selected_month)
elif page == "Savings":
    savings_page(selected_month)
elif page == "Allocation & Accountability":
    allocation_page(selected_month)
elif page == "Resources":
    resources_page(selected_month)
elif page == "Operations & Quality":
    operations_page(selected_month)
else:
    architecture_page()
