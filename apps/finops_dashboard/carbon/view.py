"""Read-only scenario UI. Input must already have passed live scope authorization."""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from formatting import COST_BLUE, chart_layout, consumption_table, integer, measurement_number, percent
from .scenario import MODELLED, Scenario, estimate_scenario, load_grid_references, monthly_scenarios


def monthly_chart(monthly: pd.DataFrame, location: str) -> go.Figure:
    """Only modelled loaded months; partial date windows remain visibly marked."""
    plotted = monthly.dropna(subset=['scenario_kgco2e'])
    figure = go.Figure(go.Bar(
        x=plotted['billing_month'], y=plotted['scenario_kgco2e'],
        name='Illustrative Emissions', marker_color=COST_BLUE,
        marker_pattern_shape=[
            '/' if status.startswith('Partial') else '' for status in plotted['period_status']
        ],
        customdata=[
            [measurement_number(row.scenario_kgco2e), measurement_number(row.scenario_energy_kwh),
             row.period_status]
            for row in plotted.itertuples()
        ],
        hovertemplate=(
            'Billing Month: %{x}<br>Illustrative Emissions: %{customdata[0]} kgCO₂e'
            '<br>Scenario Energy: %{customdata[1]} kWh<br>%{customdata[2]}<extra></extra>'
        ),
    ))
    figure.update_layout(title=f'Monthly Electricity-Emissions Scenario — {location}',
                         xaxis_title='Loaded Billing Month',
                         yaxis_title='Illustrative Emissions (kgCO₂e)', showlegend=False)
    figure.update_xaxes(type='category')
    figure.update_yaxes(tickformat=',.2f', rangemode='tozero')
    return chart_layout(figure, 350)


def comparison_chart(row: pd.Series, primary: dict, comparison: dict) -> go.Figure:
    """Hold energy constant. These are alternatives, not two actual workloads."""
    values = [row['scenario_kgco2e'], row['comparison_kgco2e']]
    references = [primary, comparison]
    figure = go.Figure(go.Bar(
        x=[reference['location'] for reference in references], y=values,
        marker_color=[COST_BLUE, '#50b5ad'],
        customdata=[
            [measurement_number(value), measurement_number(row['scenario_energy_kwh']),
             measurement_number(reference['grid_gco2e_per_kwh'])]
            for value, reference in zip(values, references)
        ],
        hovertemplate=(
            '%{x} — Hypothetical Grid<br>Illustrative Emissions: %{customdata[0]} kgCO₂e'
            '<br>Same Scenario Energy: %{customdata[1]} kWh'
            '<br>2025 Grid Intensity: %{customdata[2]} gCO₂e/kWh<extra></extra>'
        ),
    ))
    figure.update_layout(title=f'Same-Energy Location Scenario — {row["billing_month"]}',
                         yaxis_title='Illustrative Emissions (kgCO₂e)', showlegend=False)
    figure.update_yaxes(tickformat=',.2f', rangemode='tozero')
    return chart_layout(figure, 350)


def render_scenario_controls() -> Scenario:
    """Render one shared set of assumptions before either consumption tab runs."""
    metadata = load_grid_references()
    references = {row['region']: row for row in metadata['references']}
    label = lambda code: f"{references[code]['location']} · {code} · 2025 grid reference"
    controls = st.columns(2)
    power = controls[0].number_input(
        'Assumed IT Power per Equivalent VM (W)', min_value=1.0, max_value=10000.0,
        value=50.0, step=10.0, format='%.2f', key='carbon_power_watts',
        help='Teaching assumption, not a provider coefficient or a measured value.',
    )
    pue = controls[1].number_input(
        'Assumed Power Usage Effectiveness (PUE)', min_value=1.0, max_value=5.0,
        value=1.2, step=0.1, format='%.2f', key='carbon_pue',
        help='Facility energy / IT energy. Teaching assumption; not the measured PUE of a provider.',
    )
    grids = st.columns(2)
    primary_code = grids[0].selectbox('Hypothetical Grid Location', list(references),
                                     format_func=label, key='carbon_primary_region')
    alternatives = [code for code in references if code != primary_code]
    comparison_code = grids[1].selectbox('Compare with Hypothetical Grid', alternatives,
                                        format_func=label, key='carbon_comparison_region')
    scenario = Scenario(power, pue, primary_code, comparison_code)
    primary, comparison = references[primary_code], references[comparison_code]
    st.caption(
        'Defaults of 50,00 W and PUE 1,20 are editable teaching assumptions. '
        'The grid choices do not identify the source Azure region or a real Databricks workspace. '
        'Annual 2025 grid intensities are applied unchanged to every loaded period, including 2026.'
    )
    st.caption(
        f"Google-published grid references: {primary['location']} "
        f"{measurement_number(primary['grid_gco2e_per_kwh'])} and {comparison['location']} "
        f"{measurement_number(comparison['grid_gco2e_per_kwh'])} gCO₂e/kWh. "
        'No carbon-free-energy percentage or offset is applied.'
    )
    st.markdown(f"Grid reference source: [{metadata['source_title']}]({metadata['source_url']})")
    return scenario


def service_emissions_chart(estimated: pd.DataFrame) -> go.Figure:
    """One selected month, eligible groups only, summed before display rounding."""
    if estimated['billing_month'].nunique() != 1:
        raise ValueError('Service emissions chart requires one loaded billing month.')
    modelled = estimated.loc[estimated['scenario_status'].eq(MODELLED)]
    services = modelled.groupby('service_name', as_index=False)[[
        'scenario_vm_hours', 'scenario_energy_kwh', 'scenario_kgco2e'
    ]].sum(min_count=1).dropna(subset=['scenario_kgco2e'])
    services = services.sort_values('scenario_kgco2e', ascending=False)
    figure = go.Figure(go.Bar(
        x=services['scenario_kgco2e'], y=services['service_name'], orientation='h',
        marker_color=COST_BLUE,
        customdata=[
            [measurement_number(row.scenario_kgco2e), measurement_number(row.scenario_vm_hours),
             measurement_number(row.scenario_energy_kwh)]
            for row in services.itertuples()
        ],
        hovertemplate=(
            '%{y}<br>Illustrative Emissions: %{customdata[0]} kgCO₂e'
            '<br>Modelled VM Billing Hours: %{customdata[1]}'
            '<br>Scenario Energy: %{customdata[2]} kWh<extra></extra>'
        ),
    ))
    figure.update_layout(title='Illustrative Emissions by Service', showlegend=False)
    figure.update_yaxes(autorange='reversed', title=None)
    figure.update_xaxes(title='Illustrative Emissions (kgCO₂e)', tickformat=',.2f', rangemode='tozero')
    return chart_layout(figure, max(300, 40 * len(services) + 140))


def render_azure_emissions(monthly: pd.DataFrame, scenario: Scenario) -> pd.DataFrame:
    """Enrich authorized consumption for display only; never overwrite usage."""
    estimated = estimate_scenario(monthly, scenario)
    detail = monthly.copy(deep=True)
    detail['scenario_kgco2e'] = estimated['scenario_kgco2e']
    detail['estimation_status'] = estimated['scenario_status']
    references = {row['region']: row for row in load_grid_references()['references']}
    primary = references[scenario.primary_region]
    st.subheader('Illustrative Emissions by Service')
    st.caption(
        'Illustrative electricity-emissions scenario, not measured Azure emissions. '
        'Only eligible Virtual Machines and Virtual Machine Scale Sets groups billed in Hours '
        'are modelled; missing, unsupported and signed-correction groups are not estimated. '
        'This is not the total carbon footprint of the Azure portfolio.'
    )
    st.caption(
        f"Shared assumptions: {measurement_number(scenario.power_watts)} W per equivalent VM · "
        f"PUE {measurement_number(scenario.pue)} · {primary['location']} hypothetical grid · "
        f"2025 intensity {measurement_number(primary['grid_gco2e_per_kwh'])} gCO₂e/kWh. "
        'Uses the assumptions configured in the Illustrative Carbon tab. '
        'The graph covers the detailed table for the selected month, not the service/SKU filter above.'
    )
    coverage = monthly_scenarios(estimated).iloc[0]
    st.caption(
        f"{integer(coverage['modelled_usage_rows'])} modelled / "
        f"{integer(coverage['usage_rows'])} loaded Usage rows · {coverage['period_status']}. "
        'Row coverage is not emissions coverage.'
    )
    if estimated['scenario_kgco2e'].notna().any():
        st.plotly_chart(service_emissions_chart(estimated), width='stretch')
    else:
        st.info('Not Estimated — no eligible VM-hour groups for this month. No zero is fabricated.')
    return detail


def render_carbon_scenario(
    history: pd.DataFrame, month: str, *, scenario: Scenario | None = None,
) -> None:
    st.warning(
        'Illustrative scenario based on synthetic usage and assumed energy consumption. '
        'These are not measured Azure, Google Cloud or Databricks emissions.'
    )
    st.write(
        'Scope: Virtual Machines and Virtual Machine Scale Sets billed in Hours only. '
        'One eligible billing hour is assumed to represent one equivalent VM-hour. '
        'All included SKUs use the same assumed power; actual machine size and utilization are unknown.'
    )
    if scenario is None:
        scenario = render_scenario_controls()
    else:
        st.caption('These assumptions also apply to the consumption table and emissions chart in the Azure tab.')
    metadata = load_grid_references()
    references = {row['region']: row for row in metadata['references']}
    primary, comparison = references[scenario.primary_region], references[scenario.comparison_region]

    with st.expander('Method and Interpretation Limits'):
        st.code(
            'Scenario Energy (kWh) = Eligible Billing Hours × Assumed IT Power (W) / 1000 × Assumed PUE\n'
            'Illustrative Emissions (kgCO2e) = Scenario Energy (kWh) × Grid Intensity (gCO2e/kWh) / 1000',
            language='text',
        )
        st.write(
            'This estimates operational electricity emissions for a hypothetical deployment, '
            'not a whole-cloud carbon inventory or a lifecycle assessment. It excludes embodied '
            'emissions and provider renewable procurement. Cost and DBUs are not converted to energy. '
            'Real Databricks carbon reporting remains unavailable.'
        )
        st.write(
            'An entire month/service/SKU/unit group is excluded if any measurement is missing '
            'or negative, the SKU is unknown, or counters are inconsistent. Negative corrections '
            'remain unchanged on the Azure tab. Row coverage is not energy or '
            'emissions coverage. No uncertainty interval is claimed: physical VM mapping, '
            'actual energy and region are not known.'
        )

    if history.empty:
        st.info('Not Estimated — no authorized Usage records are available for this year.')
        return
    estimated = estimate_scenario(history, scenario)
    monthly = monthly_scenarios(estimated)
    selected = monthly.loc[monthly['billing_month'].eq(month)]
    if selected.empty:
        st.info('Not Estimated — no loaded Usage records for the selected month. Missing is not zero.')
    else:
        row = selected.iloc[0]
        cards = st.columns(4)
        cards[0].metric('Modelled VM Billing Hours', measurement_number(row['scenario_vm_hours']))
        cards[1].metric('Scenario Energy (kWh)', measurement_number(row['scenario_energy_kwh']))
        cards[2].metric('Illustrative Emissions (kgCO₂e)', measurement_number(row['scenario_kgco2e']),
                        help=f"{month} · {primary['location']} hypothetical grid · not measured emissions")
        coverage = None if not row['usage_rows'] else row['modelled_usage_rows'] / row['usage_rows'] * 100
        cards[3].metric('Modelled Usage Row Coverage', '—' if coverage is None else percent(coverage))
        st.caption(f"{month}: {integer(row['modelled_usage_rows'])} modelled / "
                   f"{integer(row['usage_rows'])} loaded Usage rows. Row coverage only.")
        st.info(row['period_status'])
        if pd.notna(row['scenario_kgco2e']):
            st.plotly_chart(comparison_chart(row, primary, comparison), width='stretch')
            st.caption('Same energy and assumptions in both locations. This is not measured migration savings.')
        else:
            st.info('Not Estimated — no eligible VM-hour groups for the selected month. No zero is fabricated.')

    if monthly['scenario_kgco2e'].notna().any():
        st.plotly_chart(monthly_chart(monthly, primary['location']), width='stretch')
        st.caption('Hatched bars: partial loaded dates. Missing/unmodelled months are not plotted as zero. '
                   'Even a calendar-spanning date window does not certify a complete month.')
        st.subheader('Monthly Scenario Table')
        st.dataframe(consumption_table(monthly), hide_index=True, width='stretch')

    st.subheader('Scope and Exclusions — Selected Month')
    scope = estimated.loc[estimated['billing_month'].eq(month)]
    if not scope.empty:
        coverage = scope.groupby('scenario_status', as_index=False)['usage_rows'].sum()
        st.dataframe(consumption_table(coverage), hide_index=True, width='stretch')
        modelled = scope.loc[scope['scenario_status'].eq(MODELLED)]
        if not modelled.empty:
            st.subheader('Modelled Services — Selected Month')
            columns = ['scenario_vm_hours', 'scenario_energy_kwh', 'scenario_kgco2e']
            services = modelled.groupby('service_name', as_index=False)[columns].sum(min_count=1)
            st.dataframe(consumption_table(services), hide_index=True, width='stretch')
    st.caption('Read-only scenario: no source update, Databricks pipeline run or extra billing-telemetry query.')
    st.caption('Displayed measures are rounded to two decimals; calculations retain full precision. '
               'Small non-zero values may display as 0,00. Missing values remain unavailable (—).')
