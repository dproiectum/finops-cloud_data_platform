"""FinOps Control Center backed by certified PROD Databricks data products."""

from __future__ import annotations

import os
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from config import DashboardConfig
from charts import (
    charge_cost_chart, comparable_years, savings_cost_chart, service_cost_chart, year_history,
)
from data_access import DatabricksDataSource
from formatting import (
    SAVINGS_COMPONENTS, chart_layout, financial_table, integer, money, percent,
    savings_detail_table,
)
from knowledge import cost_formulas, focus_columns, glossary
import queries
from security import (
    BoundQuery, SecurityError, auth_mode, demo_identity, iap_identity, resolve_access,
)
from security.identity import DEMO_PERSONAS
from security.queries import ScopedQueries


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


# Authenticate before any business query or connection. Public is explicitly the
# existing synthetic portfolio; a broken protected mode never falls back to it.
access = None
try:
    mode = auth_mode()
    identity = None
    if mode == "demo":
        st.sidebar.warning("Local synthetic authorization test — not authentication")
        persona = st.sidebar.selectbox("Demo identity", DEMO_PERSONAS, key="demo_identity")
        identity = demo_identity(persona)
    elif mode == "iap":
        identity = iap_identity(st.context.headers, os.environ["FINOPS_IAP_AUDIENCE"].strip())
        st.sidebar.caption(f"Verified identity: {identity.subject}")
except SecurityError as exc:
    st.error(str(exc))
    st.stop()

try:
    config = DashboardConfig.from_environment()
    source = build_source()
    if identity is not None:
        access = resolve_access(source, config, identity)
        queries = ScopedQueries(access)
except SecurityError as exc:
    st.error(str(exc))
    st.stop()
except Exception:
    st.error("Unable to connect to Databricks SQL")
    st.stop()


@st.cache_data(ttl=300, show_spinner=False)
def load_public_frame(sql_text: str) -> pd.DataFrame:
    return source.query(sql_text)


def load_frame(statement: str | BoundQuery) -> pd.DataFrame:
    # Protected query results are NEVER shared through Streamlit's process cache.
    # SQL rechecks live grants on every call, including expiry and revocation.
    try:
        if access is not None:
            if not isinstance(statement, BoundQuery):
                raise SecurityError("Unscoped query refused.")
            return source.query(statement.text, statement.parameters)
        if not isinstance(statement, str):
            raise SecurityError("Invalid public query.")
        return load_public_frame(statement)
    except SecurityError as exc:
        st.error(str(exc))
        st.stop()
    except Exception:
        st.error("Data is unavailable or access was refused. No fallback data is shown.")
        st.stop()


def require_row(frame: pd.DataFrame, subject: str) -> pd.Series:
    if frame.empty:
        st.warning(f"No certified {subject} data is available for this selection.")
        st.stop()
    return frame.iloc[0]


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
            "valid FOCUS records. A negative net price benefit indicates that effective "
            "cost exceeds list cost; it is not hidden or forced to zero."
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
        delta = f"{percent(summary['month_change_rate'], signed=True)} MoM"

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
    monthly = year_history(load_frame(queries.monthly_trend(config)), month[:4])
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
        figure.update_xaxes(type="category")
        st.plotly_chart(chart_layout(figure), width="stretch")


def executive_annual_page(year: str, other_year: str | None = None) -> None:
    history = load_frame(queries.executive_history(config))
    annual = year_history(history, year)
    if annual.empty:
        st.warning("No executive data is available for this year.")
        return
    page_title("FINOPS · EXECUTIVE", "Executive Overview", f"Selected year: {year}")
    comparable = None
    common = []
    if other_year is not None:
        annual, comparable, common = comparable_years(history, year, other_year)
        if not common:
            st.warning("The two years have no loaded month in common; no comparison is calculated.")
            return
        st.info(
            f"Comparable months only: {', '.join(common)}. "
            f"Both {year} and {other_year} use exactly these months; missing months are not zero."
        )
    else:
        st.caption(
            f"Loaded months: {', '.join(annual['billing_month'].astype(str))}. "
            "This is not a full-year total unless all 12 months are loaded."
        )
    billed = annual["billed_cost"].sum()
    effective = annual["effective_cost"].sum()
    list_cost = annual["list_cost"].sum()
    difference = list_cost - effective
    rate = 0 if list_cost == 0 else 100 * difference / list_cost
    change = None
    if comparable is not None:
        baseline = comparable["billed_cost"].sum()
        if baseline != 0:
            change = f"{percent(100 * (billed - baseline) / abs(baseline), signed=True)} YoY"
        else:
            st.caption("YoY percentage is unavailable because the comparison-year billed cost is zero.")
    cards = st.columns(4)
    cards[0].metric("Billed cost", money(billed), delta=change)
    cards[1].metric("Effective cost", money(effective))
    cards[2].metric("Difference vs list", money(difference))
    cards[3].metric("Difference rate", percent(rate))
    st.caption(
        f"Charge lines: {integer(annual['charge_lines'].sum())} · Loaded months: {len(annual)}. "
        "Monthly resource and service counts are not summed into annual distinct counts."
    )
    if comparable is not None:
        chart_frame = pd.concat([
            annual.assign(year=year), comparable.assign(year=other_year)
        ], ignore_index=True)
        figure = px.bar(
            chart_frame, x="month_number", y="billed_cost", color="year", barmode="group",
            title="Billed cost: same months, two years",
            labels={"month_number": "Month number", "billed_cost": "Billed cost (€)", "year": "Year"},
            color_discrete_sequence=["#0078d4", "#8a8886"],
        )
        figure.update_xaxes(type="category", categoryorder="array", categoryarray=common)
        st.dataframe(financial_table(chart_frame.drop(columns="month_number")),
                     hide_index=True, width="stretch")
    else:
        figure = px.bar(
            annual, x="billing_month", y="billed_cost", title="Billed cost by loaded month",
            labels={"billing_month": "Month", "billed_cost": "Billed cost (€)"},
            color_discrete_sequence=["#0078d4"],
        )
        figure.update_xaxes(type="category")
        st.dataframe(financial_table(annual), hide_index=True, width="stretch")
    st.plotly_chart(chart_layout(figure, 420), width="stretch")


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
        st.plotly_chart(service_cost_chart(services, "Which services drive the bill?"),
                        width="stretch")
        st.caption("One bar per service; highest billed cost first. Only the top 20 are shown.")
    with right:
        st.plotly_chart(charge_cost_chart(charges), width="stretch")
        st.caption(
            "Usage: consumption charges; Purchase: purchases; Tax: taxes; "
            "Credit: credit records; Adjustment: corrections. "
            "Bars left of zero reduce the net bill; bars right of zero increase it."
        )

    service_tab, sku_tab, charge_tab = st.tabs(
        ["Portfolio services", "Portfolio SKUs", "Charge details"]
    )
    with service_tab:
        st.caption("Cumulative view across all loaded months")
        st.dataframe(
            financial_table(load_frame(queries.portfolio_services(config))),
            hide_index=True,
            width="stretch",
        )
    with sku_tab:
        st.caption("The current SKU datamart is cumulative across all loaded months")
        st.dataframe(
            financial_table(load_frame(queries.sku_costs(config))),
            hide_index=True,
            width="stretch",
        )
    with charge_tab:
        st.dataframe(financial_table(charges), hide_index=True, width="stretch")


def savings_page(month: str) -> None:
    page_title("FINOPS · OPTIMIZE", "Savings Analysis", f"Selected period: {month}")
    savings = require_row(load_frame(queries.savings_summary(config, month)), "savings")
    history = year_history(load_frame(queries.monthly_savings(config)), month[:4])
    benefit = savings["list_cost"] - savings["effective_cost"]
    cards = st.columns(4)
    cards[0].metric("List Cost", money(savings["list_cost"]))
    cards[1].metric("Contract Cost", money(savings["contracted_cost"]))
    cards[2].metric("Effective Cost", money(savings["effective_cost"]))
    cards[3].metric("Realized Savings", money(benefit))
    st.caption(
        "Realized Savings = List Cost − Effective Cost. "
        f"Saving rate: {percent(savings['savings_rate'])}."
    )
    figure, stacked = savings_cost_chart(history)
    st.plotly_chart(figure, width="stretch")
    if not stacked:
        st.info(
            "Some months have a negative or missing cost, or effective cost above list cost. "
            "Effective Cost and Realized Savings are shown side by side to retain these values."
        )
    st.subheader("Detailed Table")
    st.caption(
        "Reservation and Savings Plan show allocated effective usage costs, not full "
        "contract purchase amounts. The cost components add up to Effective Cost."
    )
    if not set(SAVINGS_COMPONENTS).issubset(history.columns):
        st.info(
            "The effective-cost breakdown is not available yet (—). Refresh "
            "dm_savings_monthly with the updated 08_dm_savings_monthly.sql template; "
            "a full ingestion reload is not required."
        )
    detail = savings_detail_table(history)
    if "Other Charges" in detail.data:
        st.caption(
            "Other Charges includes effective costs outside the five named categories, "
            "so the breakdown still reconciles with Effective Cost."
        )
    st.dataframe(detail, hide_index=True, width="stretch")
    figure = px.bar(
        history,
        x="billing_month",
        y="total_savings",
        title="Realized Savings by Month",
        labels={"billing_month": "Month", "total_savings": "Realized Savings (€)"},
        color_discrete_sequence=["#8fd5a6"],
    )
    figure.update_traces(
        customdata=[
            [money(value) if pd.notna(value) else "Unavailable",
             money(list_cost) if pd.notna(list_cost) else "Unavailable"]
            for value, list_cost in zip(history["total_savings"], history["list_cost"])
        ],
        hovertemplate=(
            "%{x}<br>List Cost: %{customdata[1]}"
            "<br>Realized Savings: %{customdata[0]}<extra></extra>"
        ),
    )
    figure.update_xaxes(type="category")
    st.plotly_chart(chart_layout(figure, 440), width="stretch")
    st.warning(
        "Realized Savings is the dashboard label for List Cost minus Effective Cost. "
        "This synthetic cost comparison does not establish realized organizational "
        "or cash savings without a validated business baseline. Negative values remain visible."
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
        order = st.selectbox(
            "Service order", ["Highest cost first", "Lowest cost first", "Name A–Z"],
            key="service_order",
        )
        st.plotly_chart(service_cost_chart(services, "Billed cost by service", order),
                        width="stretch")
        st.caption("One color and one bar per service; this view shows the top 30 services by cost.")
    with center_tab:
        if (center_cost < 0).any() or not (center_cost > 0).any():
            # A scoped perimeter can have net credits. Treemap areas cannot
            # represent negative values; retain them as signed bars instead.
            figure = px.bar(
                centers.sort_values("total_billed_cost"), x="total_billed_cost", y="cost_center",
                orientation="h", title="Cost-center allocation",
                labels={"total_billed_cost": "Billed cost (€)", "cost_center": "Cost center"},
                color_discrete_sequence=["#0078d4"],
            )
            st.caption("Signed bars retain credits and non-positive cost-center totals.")
        else:
            figure = px.treemap(
                centers,
                path=["cost_center"],
                values="total_billed_cost",
                color="total_billed_cost",
                color_continuous_scale=["#deecf9", "#71afe5", "#0078d4", "#005a9e"],
                title="Cost-center allocation",
                labels={"total_billed_cost": "Billed cost (€)", "cost_center": "Cost center"},
            )
            figure.update_traces(
                customdata=[[money(value)] for value in figure.data[0].values],
                hovertemplate="%{label}<br>Billed cost: %{customdata[0]}<extra></extra>",
            )
            figure.update_coloraxes(colorbar_tickformat=",.0f")
        st.plotly_chart(chart_layout(figure, 520), width="stretch")
        st.dataframe(financial_table(centers), hide_index=True, width="stretch")
    with subscription_tab:
        st.dataframe(financial_table(subscriptions), hide_index=True, width="stretch")
    with owner_tab:
        st.dataframe(financial_table(owners), hide_index=True, width="stretch")


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
            labels={"total_billed_cost": "Cost (€)", "resource_name": "Resource"},
        )
        st.plotly_chart(chart_layout(figure, 560), width="stretch")
        st.dataframe(financial_table(resources), hide_index=True, width="stretch")
    with group_tab:
        figure = px.bar(
            groups.head(20).sort_values("total_billed_cost"),
            x="total_billed_cost",
            y="resource_group_name",
            orientation="h",
            title="Cost by resource group",
            labels={"total_billed_cost": "Cost (€)", "resource_group_name": "Resource group"},
            color_discrete_sequence=["#0078d4"],
        )
        st.plotly_chart(chart_layout(figure, 560), width="stretch")
        st.dataframe(financial_table(groups), hide_index=True, width="stretch")
    with portfolio_tab:
        st.caption("Cumulative view across all loaded months")
        st.dataframe(
            financial_table(load_frame(queries.portfolio_resources(config))),
            hide_index=True,
            width="stretch",
        )


def operations_page(month: str) -> None:
    if access is not None and not access.is_admin:
        st.error("Operations access is restricted to FinOps administrators.")
        st.stop()
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
        st.dataframe(financial_table(controls), hide_index=True, width="stretch")
        st.write(f"Latest Silver publication: **{quality['latest_silver_load']}**")
    with runs_tab:
        st.dataframe(runs, hide_index=True, width="stretch")
    with reconciliation_tab:
        st.dataframe(financial_table(reconciliations), hide_index=True, width="stretch")
    with environments_tab:
        st.dataframe(financial_table(counts), hide_index=True, width="stretch")
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
        if access is not None:
            st.info(
                "Protected pages use v_dashboard_charge_scoped, a charge-grain view of Silver, "
                "with live viewer permissions applied before aggregation. Public pages keep "
                "the existing global datamarts."
            )
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


def executive_entry() -> None:
    if overview_view == "Monthly":
        executive_page(selected_month)
    else:
        executive_annual_page(selected_year, comparison_year)


# Native top navigation: protected OPS is absent for restricted viewers. The
# page body and SQL also enforce this rule; hiding navigation alone is not enough.
pages = [
    st.Page(executive_entry, title="Executive Overview", url_path="overview", default=True),
    st.Page(lambda: cost_drivers_page(selected_month), title="Cost Drivers", url_path="drivers"),
    st.Page(lambda: savings_page(selected_month), title="Savings", url_path="savings"),
    st.Page(lambda: allocation_page(selected_month), title="Allocation & Accountability",
            url_path="allocation"),
    st.Page(lambda: resources_page(selected_month), title="Resources", url_path="resources"),
    st.Page(knowledge_page, title="Knowledge Base", url_path="knowledge"),
    st.Page(architecture_page, title="Architecture", url_path="architecture"),
]
if access is None or access.is_admin:
    pages.insert(5, st.Page(lambda: operations_page(selected_month), title="Operations & Quality",
                            url_path="operations"))
navigation = st.navigation(pages, position="top")

with st.sidebar:
    st.markdown("### FinOps Control Center")
    st.caption("Certified cloud cost intelligence")
    if access is not None:
        st.caption(f"Identity: {access.identity.subject}")
        st.caption("Authorized scope only · no shared query-result cache")
    st.markdown(
        f'<span class="status-pill">{source.label} · {config.environment.upper()}</span>',
        unsafe_allow_html=True,
    )
    st.divider()
    needs_month = navigation.title not in {"Knowledge Base", "Architecture"}
    selected_month = None
    overview_view = "Monthly"
    selected_year = None
    comparison_year = None
    if needs_month:
        try:
            month_frame = load_frame(queries.available_months(config))
            months = sorted(month_frame["billing_month"].astype(str).unique(), reverse=True)
        except Exception:
            st.error("Certified datamarts are unavailable")
            st.stop()
        if not months:
            st.warning("No billing month is available")
            st.stop()
        years = sorted({month[:4] for month in months}, reverse=True)
        selected_year = st.selectbox("Billing year", years, key="billing_year")
        if navigation.title == "Executive Overview":
            views = ["Monthly", "Annual"]
            if len(years) > 1:
                views.append("Year-over-year")
            overview_view = st.selectbox("Overview view", views, key="overview_view")
        if overview_view == "Monthly":
            year_months = [month for month in months if month.startswith(f"{selected_year}-")]
            selected_month = st.selectbox("Billing month", year_months, key="billing_month")
        elif overview_view == "Year-over-year":
            comparison_year = st.selectbox(
                "Compare with year", [year for year in years if year != selected_year],
                key="comparison_year",
            )
    st.divider()
    st.caption(f"Catalog: {config.data_catalog}")
    st.caption("Read-only · authorized charge view" if access is not None
               else "Read-only · certified datamarts")

navigation.run()
