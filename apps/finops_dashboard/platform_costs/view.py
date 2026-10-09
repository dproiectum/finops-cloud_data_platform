"""Platform costs are approved aggregates, not selectable-profile telemetry."""

import os
from decimal import localcontext
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from formatting import chart_layout, measurement_number
from .model import amount, billing_total, provider_total, validate_records
from .reader import load_snapshot
from .interactive_chart import render_cost_chart

# Provider references, scoped to Platform Costs (not the synthetic portfolio).
# https://firebase.google.com/brand-guidelines — Google Ecosystem Blue
GCP_BLUE = '#4285F4'
# Exact RGB from the user's swatch, not an official brand-color claim.
DATABRICKS_CORAL = '#FF543D'
AXIS_TITLE_SIZE = 14
CURRENCY_SCALE_NOTE = ('Separate currency scales — no currency conversion. '
                       'Column heights do not directly compare costs.')
MONTHS = ('January', 'February', 'March', 'April', 'May', 'June',
          'July', 'August', 'September', 'October', 'November', 'December')
PROVIDERS = (
    ('GCP', 'Net Cost', GCP_BLUE, 'EUR'),
    ('Databricks', 'List Cost Estimate', DATABRICKS_CORAL, 'USD'),
)


def provider_currency(frame, provider):
    if frame.loc[frame['provider'] == provider, 'cost_basis'].nunique() > 1:
        raise ValueError('Separate billing exports and estimates before charting.')
    currencies = frame.loc[frame['provider'] == provider, 'currency'].unique()
    if len(currencies) > 1:
        raise ValueError('Select one currency per provider before aggregating costs')
    return currencies[0] if len(currencies) else None


def grouped_costs(frame, columns):
    with localcontext() as context:
        context.prec = 80
        return frame.groupby(columns, as_index=False)['reported_cost'].sum()


def cost_trend(frame, *, daily=False, month=None, yearly=False, month_number=None,
               year=None, provider_currencies=None, cost_basis=None):
    figure = go.Figure()
    frame = frame.copy()
    if cost_basis is not None:
        if cost_basis not in {'billing_export', 'list_estimate'}:
            raise ValueError('Unsupported chart cost basis.')
        frame = frame[frame['cost_basis'] == cost_basis]
    single_scale = cost_basis is not None
    specifications = PROVIDERS
    if cost_basis == 'billing_export':
        specifications = (PROVIDERS[0], ('Databricks', 'Marketplace Net Cost', DATABRICKS_CORAL, 'EUR'))
    elif cost_basis == 'list_estimate':
        specifications = (PROVIDERS[1],)
    if yearly:
        frame['year'] = frame['month'].str[:4]
    time_column = 'usage_date' if daily else 'year' if yearly else 'month'
    if daily:
        if month:
            frame = frame[frame['month'] == month]
        if frame.empty:
            dates = []
        else:
            start = pd.Timestamp((month or frame['month'].min()) + '-01')
            end = min(pd.Timestamp((month or frame['month'].max()) + '-01') + pd.offsets.MonthEnd(0),
                      pd.Timestamp.now(tz='UTC').tz_localize(None).normalize())
            calendar = pd.date_range(start, end)
            if month_number:
                calendar = calendar[calendar.month == int(month_number)]
            dates = list(calendar.strftime('%Y-%m-%d'))
    elif yearly:
        dates = [str(year) for year in range(int(frame['year'].min()), int(frame['year'].max()) + 1)] if not frame.empty else []
    else:
        dates = list(pd.period_range(frame['month'].min(), frame['month'].max(), freq='M').astype(str)) if not frame.empty else []
        if month_number:
            dates = [date for date in dates if date[5:7] == month_number]
    if frame.empty:
        # Calendar labels describe the selected scope; they are not cost records.
        years = [int(year)] if year and year != 'All Years' else list(range(2025, max(2025, pd.Timestamp.now(tz='UTC').year) + 1))
        months = [int(month_number)] if month_number else range(1, 13)
        periods = [f'{value:04}-{number:02}' for value in years for number in months]
        if month:
            periods = [month]
        dates = [str(value) for value in years] if yearly else periods
        if daily:
            dates = [day.strftime('%Y-%m-%d') for period in periods
                     for day in pd.date_range(period + '-01', pd.Timestamp(period + '-01') + pd.offsets.MonthEnd(0))]
    currencies = {}
    for provider, label, color, default_currency in specifications:
        display_provider = 'Google Cloud (GCP)' if provider == 'GCP' else provider
        currency = provider_currency(frame, provider)
        currencies[provider] = currency or (provider_currencies or {}).get(provider, default_currency)
        rows = frame[frame["provider"] == provider]
        if rows.empty:
            if frame.empty:
                # Null-only traces retain axes and legends, without fabricated zeros.
                figure.add_trace(go.Bar(x=dates, y=[None] * len(dates),
                    name=f'{display_provider} · {label} ({currencies[provider]})', marker_color=color,
                    yaxis='y2' if provider == 'Databricks' and not single_scale else 'y',
                    offsetgroup=provider, alignmentgroup='platform_costs', hoverinfo='skip'))
            continue
        totals = grouped_costs(rows, time_column).sort_values(time_column)
        # Missing dates stay gaps, never invented zero costs.
        totals = totals.set_index(time_column).reindex(dates).rename_axis(time_column).reset_index()
        values = [None if pd.isna(value) else float(value) for value in totals['reported_cost']]
        # Keep the provider in the main neutral bubble. Plotly's secondary
        # <extra> name box otherwise retains the bar's blue/coral background.
        hover = "<b>%{fullData.name}</b><br>%{x}<br>%{customdata[0]}"
        customdata = [[amount(value, currency)] for value in totals['reported_cost']]
        if provider == 'Databricks' and (rows['cost_basis'] == 'list_estimate').all():
            with localcontext() as context:
                context.prec = 80
                dbus = rows.groupby(time_column)['usage_quantity'].sum().reindex(dates)
            customdata = [[cost[0], '—' if pd.isna(dbu) else measurement_number(dbu)]
                          for cost, dbu in zip(customdata, dbus)]
            hover += '<br>Net DBUs: %{customdata[1]}'
        figure.add_trace(go.Bar(
            x=totals[time_column], y=values,
            name=f'{display_provider} · {label} ({currency})', marker_color=color,
            marker_line=dict(width=0),
            yaxis='y2' if provider == 'Databricks' and not single_scale else 'y',
            offsetgroup=provider, alignmentgroup='platform_costs',
            customdata=customdata, hovertemplate=hover + '<extra></extra>',
        ))
    primary_currency = currencies[specifications[0][0]]
    if single_scale and len(set(currencies.values())) != 1:
        raise ValueError('A single cost axis requires one billing currency; no implicit FX.')
    figure.update_layout(
        title=(f"Daily Platform Costs · {month}" if month else "Daily Platform Costs") if daily else
              "Yearly Platform Costs" if yearly else "Monthly Platform Costs",
        barmode='group', bargap=0.2, bargroupgap=0.08,
        yaxis=dict(title=f"Cost in {'Euro' if primary_currency == 'EUR' else primary_currency}",
                   tickformat=',.2f', hoverformat=',.2f', rangemode='tozero'),
        yaxis2=dict(title='',
                    tickformat=',.2f', hoverformat=',.2f',
                    overlaying='y', side='right', showgrid=False, rangemode='tozero'),
        legend=dict(orientation='h', y=-0.28, x=0, xanchor='left', font=dict(size=AXIS_TITLE_SIZE)),
        hovermode='closest',
        hoverlabel=dict(namelength=-1, bgcolor='#F8FAFC', bordercolor='#CBD5E1',
                        font=dict(color='#1F2937')),
    )
    # The native right-axis title is rotated -90°. +90° reverses it by 180°.
    if not single_scale:
        figure.add_annotation(text=f"Cost in {'Euro' if currencies['Databricks'] == 'EUR' else currencies['Databricks']}",
                          xref='paper', yref='paper', x=1, y=0.5, xshift=65,
                          textangle=90, xanchor='center', yanchor='middle', showarrow=False,
                          font=dict(size=AXIS_TITLE_SIZE), name='right_cost_axis_title')
    note = CURRENCY_SCALE_NOTE
    if cost_basis == 'billing_export':
        note = 'Billing export costs after signed credits. USD usage estimates are excluded from the platform total.'
    elif cost_basis == 'list_estimate':
        note = 'Published-price usage estimate in USD. Not an invoice; excluded from the platform total.'
        figure.update_layout(title=('Daily' if daily else 'Yearly' if yearly else 'Monthly') + ' Databricks Usage Estimate')
    figure.add_annotation(text=f'<i>{note}</i>',
                          xref='paper', yref='paper', x=0, y=-0.43,
                          xanchor='left', yanchor='top', align='left', showarrow=False,
                          font=dict(size=12), name='currency_scale_note')
    figure.update_xaxes(type="category", title="Usage Date (UTC)" if daily else "Usage Year" if yearly else "Usage Month",
                        categoryorder='array', categoryarray=dates)
    if daily and figure.data:
        step = max(3, (len(dates) + 11) // 12)
        ticks = dates[::step]
        multiple_years = len({date[:4] for date in dates}) > 1
        figure.update_xaxes(tickmode='array', tickvals=ticks,
                           ticktext=[pd.Timestamp(day).strftime('%d/%m/%Y' if multiple_years else '%d/%m') for day in ticks])
    chart_layout(figure, 510)
    figure.update_xaxes(title_font=dict(size=AXIS_TITLE_SIZE))
    figure.update_yaxes(title_font=dict(size=AXIS_TITLE_SIZE))
    if frame.empty:
        figure.add_annotation(text='<i>No published record</i>', xref='paper', yref='paper',
                              x=0.5, y=0.5, showarrow=False, name='no_published_record')
        figure.update_yaxes(visible=True, showline=True, showticklabels=False)
        figure.update_xaxes(tickmode='array', tickvals=list(figure.layout.xaxis.tickvals or dates),
                            range=[-0.5, max(0.5, len(dates) - 0.5)])
    figure.update_layout(margin=dict(l=75, r=95, t=48, b=160))
    if single_scale:
        figure.update_layout(yaxis2=dict(visible=False))
    return figure


def render_cost_detail(frame, *, daily=False, estimate=False, marketplace=False):
    st.subheader('Detailed Usage Estimate Table' if estimate else 'Detailed Daily Cost Table' if daily else 'Detailed Cost Table')
    detail = frame.rename(columns={
        'usage_date': 'Usage Date', 'month': 'Usage Month', 'provider': 'Provider',
        'service': 'Service / SKU', 'currency': 'Currency',
        'cost_before_credits': 'Cost Before Credits', 'credits': 'Credits',
        'usage_quantity': 'Net DBUs', 'cost_basis': 'Cost Basis',
        'period_status': 'Period Status', 'reported_cost': 'Reported Cost',
    }).drop(columns='usage_unit')
    detail['Cost Basis'] = detail['Cost Basis'].map({'billing_export': 'Cloud Billing Export', 'list_estimate': 'Databricks List Estimate'})
    detail['Period Status'] = detail['Period Status'].str.title()
    for column in ('Cost Before Credits', 'Credits', 'Reported Cost'):
        detail[column] = [amount(value, currency) for value, currency in zip(detail[column], detail['Currency'])]
    if marketplace and not estimate:
        detail['Provider'] = detail['Provider'].map({'GCP': 'Google Cloud (GCP)', 'Databricks': 'Databricks Marketplace'})
        detail = detail.drop(columns='Net DBUs')
    st.dataframe(detail.style.format({'Net DBUs': measurement_number}, na_rep='—'), hide_index=True, width='stretch')


def render_platform_costs(*, embedded=False):
    if embedded:
        st.subheader("Platform Costs")
    else:
        st.markdown('<div class="finops-kicker">FINOPS · PLATFORM OPERATIONS</div>', unsafe_allow_html=True)
        st.title("Platform Costs")
    st.write("The cost of operating this FinOps platform, separate from its synthetic Azure portfolio.")
    overview, methodology = st.tabs(["Cost Overview", "Scope & Method"])
    with overview:
        try:
            as_of, frame = load_snapshot()
        except (ValueError, OSError):
            # No raw values, filesystem paths or rejected records in the public UI.
            st.error("The platform cost snapshot is unavailable or failed validation.")
            frame = pd.DataFrame()
            as_of = None
        if frame.empty:
            st.info("No approved cost snapshot is published yet. Unavailable costs are not zero.")
            st.write("This page will show monthly GCP costs, credits and Databricks DBU estimates once the aggregated exports have been reviewed.")
        else:
            mode = "Scheduled aggregate" if os.getenv("FINOPS_PLATFORM_COSTS_MODE") == "gcs" else "Bundled snapshot"
            st.caption(f"{mode} · extracted {as_of} · billing availability may lag behind extraction")
            daily_records = frame.attrs.get('daily_records')
            marketplace = frame.attrs.get('marketplace_billing', False)
            if marketplace:
                source_times = frame.attrs['source_as_of']
                billing_time = pd.Timestamp(source_times['GCP']).tz_convert('UTC').strftime('%Y-%m-%d %H:%M UTC')
                st.caption(f'Billing export extracted: {billing_time}. This timestamp does not prove complete usage coverage.')
            controls = st.columns(3)
            view = controls[0].selectbox("View by", ['Daily', 'Monthly', 'Yearly'] if daily_records else ['Monthly', 'Yearly'], key='platform_cost_view')
            is_daily = view == 'Daily'
            if is_daily:
                frame = validate_records(daily_records, daily=True)
            elif not daily_records:
                st.caption('Daily costs are not yet published. Monthly totals cannot be split into daily costs.')
            estimates = frame[frame['cost_basis'] == 'list_estimate'].copy()
            if marketplace:
                frame = frame[frame['cost_basis'] == 'billing_export'].copy()
            else:
                st.warning('Legacy snapshot: Databricks Marketplace billing is not included in GCP Net Cost. A complete platform total is unavailable until a new billing export is published.')
            currencies = {}
            specifications = PROVIDERS if not marketplace else (
                PROVIDERS[0], ('Databricks', 'Marketplace Net Cost', DATABRICKS_CORAL, 'EUR'))
            for provider, _, _, default in specifications:
                available = sorted(frame.loc[frame['provider'] == provider, 'currency'].unique())
                currency = available[0] if available else default
                if len(available) > 1:
                    currency = st.selectbox(f'{provider} Currency', available,
                                            index=available.index(default) if default in available else 0,
                                            key=f'platform_cost_currency_{provider}')
                currencies[provider] = currency
                frame = frame[(frame['provider'] != provider) | (frame['currency'] == currency)]
            last_year = max(2025, pd.Timestamp.now(tz='UTC').year, int(frame['month'].str[:4].max()))
            year = controls[1].selectbox("Year", ["All Years", *map(str, range(2025, last_year + 1))], key="platform_cost_year")
            if year != "All Years":
                frame = frame[frame["month"].str.startswith(year + "-")]
                estimates = estimates[estimates['month'].str.startswith(year + '-')]
            month = controls[2].selectbox("Month", ["All Months", *[f'{number:02} · {name}' for number, name in enumerate(MONTHS, 1)]],
                                         key='platform_cost_month')
            month_number = None if month == 'All Months' else month[:2]
            selected = frame if not month_number else frame[frame['month'].str[5:7] == month_number]
            estimates = estimates if not month_number else estimates[estimates['month'].str[5:7] == month_number]
            metrics = st.columns(3 if marketplace else 4)
            if marketplace:
                metrics[0].metric('GCP Services Net Cost', amount(provider_total(selected, 'GCP', 'reported_cost'), currencies['GCP']))
                metrics[1].metric('Databricks Marketplace Net Cost', amount(provider_total(selected, 'Databricks', 'reported_cost'), currencies['Databricks']))
                metrics[2].metric('Total Platform Cost', amount(billing_total(selected), currencies['GCP']))
                st.caption('Recorded billing-export costs after credits, not a final invoice or proof of payment. The total excludes DBU estimates and is unavailable if a component is missing or currencies differ.')
            else:
                metrics[0].metric("GCP Cost Before Credits", amount(provider_total(selected, "GCP", "cost_before_credits"), currencies['GCP']))
                metrics[1].metric("GCP Net Cost", amount(provider_total(selected, "GCP", "reported_cost"), currencies['GCP']))
                dbus = provider_total(selected, "Databricks", "usage_quantity")
                metrics[2].metric("Databricks Net DBUs", "—" if dbus is None else measurement_number(dbus))
                metrics[3].metric("Databricks List Cost Estimate", amount(provider_total(selected, "Databricks", "reported_cost"), currencies['Databricks']))
            if (selected["period_status"] == "partial").any():
                st.caption("Partial periods are included. A shorter month must not be interpreted as an efficiency gain.")
            if is_daily and not selected.empty:
                first, last = selected['usage_date'].min(), selected['usage_date'].max()
                st.caption(f'Recorded usage dates: {first} to {last} (UTC). Days without records are unavailable, not zero; the last reported day may be incomplete.')
            if marketplace and len(set(currencies.values())) != 1:
                st.info('The billing components use different currencies. No combined chart or total is shown; review the separate provider panels below.')
            else:
                render_cost_chart(cost_trend(selected, daily=is_daily, yearly=view == 'Yearly',
                                          month_number=month_number, year=year,
                                          provider_currencies=currencies, cost_basis='billing_export' if marketplace else None))
            if not marketplace:
                st.caption("GCP billing-export costs and Databricks list-price estimates use different cost bases. They are not added into a billed total.")
            st.subheader("Service Breakdown")
            # Separate breakdown scales: never sort EUR and USD as comparable amounts.
            panels = st.columns(2)
            for panel, (provider, label, color, _) in zip(panels, specifications):
                with panel:
                    st.markdown(f'**{provider} · {label} ({currencies[provider]})**')
                    rows = selected[selected['provider'] == provider]
                    if rows.empty:
                        st.info('No records for this provider in the selected period. Unavailable is not zero.')
                        continue
                    breakdown = grouped_costs(rows, 'service').sort_values('reported_cost', ascending=False)
                    figure = go.Figure(go.Bar(
                        x=[float(value) for value in breakdown['reported_cost']],
                        y=breakdown['service'], orientation='h', marker_color=color,
                        marker_line=dict(width=0),
                        customdata=[[amount(value, currencies[provider])] for value in breakdown['reported_cost']],
                        hovertemplate='%{y}<br>%{customdata[0]}<extra></extra>',
                    ))
                    figure.update_yaxes(autorange='reversed')
                    figure.update_xaxes(title=f'{label} ({currencies[provider]})', tickformat=',.2f')
                    st.plotly_chart(chart_layout(figure, max(350, 28 * len(breakdown) + 90)), width='stretch')
            render_cost_detail(selected, daily=is_daily, marketplace=marketplace)
            if marketplace:
                with st.expander('Databricks Usage Estimate (USD) · Separate Reference', expanded=False):
                    st.write('DBU consumption at published USD prices. This is not the Marketplace billing amount and is never added to Total Platform Cost. The same Year and Month filters apply.')
                    estimate_metrics = st.columns(2)
                    estimate_metrics[0].metric('Databricks Net DBUs', measurement_number(provider_total(estimates, 'Databricks', 'usage_quantity')) if not estimates.empty else '—')
                    estimate_metrics[1].metric('Databricks List Cost Estimate', amount(provider_total(estimates, 'Databricks', 'reported_cost'), 'USD'))
                    render_cost_chart(cost_trend(estimates, daily=is_daily, yearly=view == 'Yearly',
                                      month_number=month_number, year=year, cost_basis='list_estimate'),
                                      key='platform_cost_estimate_chart')
                    render_cost_detail(estimates, daily=is_daily, estimate=True)
    with methodology:
        st.subheader("FinOps Applied to the Platform Itself")
        st.write("Billing aggregates cover the FinOps GCP project and its explicitly allowlisted Databricks Marketplace billing project. DBU estimates cover the two project Databricks workspaces and remain separate. Monthly totals derive from daily records; the two grains are never added together. These are not exact per-job allocations or a controlled Frankfurt–Belgium benchmark.")
        st.write("A day is defined by usage_start_time in UTC. An interval crossing midnight is attributed to its start day, without prorating. Source reporting delays and corrections apply; no missing day is treated as a measured zero.")
        st.markdown("- **Net Cost = Cost Before Credits + Signed Credits**, separately for GCP services and Databricks Marketplace. Credits normally reduce cost; corrections remain signed.\n- **Total Platform Cost = GCP Services Net Cost + Databricks Marketplace Net Cost**, only when both components are present in the same currency. This is the recorded export total, not a final invoice or proof of payment.\n- **Databricks List Cost Estimate = Σ (signed DBUs × applicable published USD price).** It is a separate reference, never added to billing-export costs. No implicit currency conversion is performed.\n- **Partial months and missing values remain visible.** A real zero is displayed as zero; an absent component makes the total unavailable. Legacy snapshots do not provide a complete platform total.")
        st.write("The public page reads only approved aggregates, either from a private GCS object or an explicitly bundled snapshot. It cannot query billing source tables, reveal resource identifiers, or widen access when a demonstration profile changes. In automatic mode, stale or invalid output is unavailable, not replaced by an old bundled snapshot.")
        st.caption("Platform sustainability belongs in this project section. Databricks emissions are not estimated: DBUs alone do not provide energy consumption or a supported conversion to kgCO₂e.")
        st.markdown("Sources: [Google Cloud Billing export queries](https://docs.cloud.google.com/billing/docs/how-to/bq-examples) · [Databricks pricing system table](https://docs.databricks.com/gcp/en/admin/system-tables/pricing)")
