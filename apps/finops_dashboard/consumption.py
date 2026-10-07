"""Consumption query shape and interpretation, without invented conversions."""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go

from formatting import chart_layout, measurement_number


def azure_history_body(period_predicate: str) -> str:
    # The caller authorizes application-grain rows before this aggregate.
    # period_predicate is built by trusted query code, not supplied by the UI.
    return f"""SELECT billing_month, service_name, sku_id, consumed_unit,
        SUM(consumed_quantity) AS consumed_quantity,
        SUM(usage_rows) AS usage_rows,
        SUM(measured_usage_rows) AS measured_usage_rows,
        SUM(missing_measurement_rows) AS missing_measurement_rows,
        SUM(negative_quantity_rows) AS negative_quantity_rows,
        MIN(first_loaded_charge_date) AS first_loaded_charge_date,
        MAX(last_loaded_charge_date) AS last_loaded_charge_date
        FROM authorized_rows WHERE {period_predicate}
        GROUP BY billing_month, service_name, sku_id, consumed_unit
        ORDER BY billing_month, service_name, sku_id, consumed_unit"""


def measurement_summary(frame: pd.DataFrame) -> dict:
    """Count measurements across units, but never sum their quantities."""
    counts = {column: int(frame[column].sum()) for column in (
        'usage_rows', 'measured_usage_rows', 'missing_measurement_rows',
        'negative_quantity_rows',
    )}
    total = counts['usage_rows']
    return {
        **counts,
        'coverage_pct': 100 * counts['measured_usage_rows'] / total if total else None,
        'first_date': pd.to_datetime(frame['first_loaded_charge_date']).min(),
        'last_date': pd.to_datetime(frame['last_loaded_charge_date']).max(),
    }


def dimension_options(frame: pd.DataFrame, column: str) -> list:
    return sorted(frame[column].dropna().astype(str).unique().tolist())


def consumption_series(frame: pd.DataFrame, service: str, sku: str, unit: str) -> pd.DataFrame:
    """A comparison has exactly one service/SKU/unit; missing months stay absent."""
    return frame.loc[
        frame['service_name'].eq(service)
        & frame['sku_id'].eq(sku)
        & frame['consumed_unit'].eq(unit)
    ].copy().sort_values('billing_month')


def azure_consumption_chart(series: pd.DataFrame):
    keys = ['service_name', 'sku_id', 'consumed_unit']
    if series.empty or series[keys].isna().any().any() or len(series[keys].drop_duplicates()) != 1:
        raise ValueError('A consumption chart requires one known service, SKU and unit.')
    if series['billing_month'].duplicated().any():
        raise ValueError('Authorize and aggregate application rows before charting.')
    rows = series.sort_values('billing_month').copy()
    unit = str(rows['consumed_unit'].iloc[0])
    figure = go.Figure(go.Bar(
        x=rows['billing_month'],
        y=pd.to_numeric(rows['consumed_quantity'], errors='coerce'),
        marker_color='#0078d4',
        customdata=[
            [measurement_number(quantity), str(first)[:10], str(last)[:10], int(missing)]
            for quantity, first, last, missing in zip(
                rows['consumed_quantity'], rows['first_loaded_charge_date'],
                rows['last_loaded_charge_date'], rows['missing_measurement_rows'],
            )
        ],
        hovertemplate=(
            '%{x}<br>Consumed Quantity: %{customdata[0]}'
            '<br>Loaded Dates: %{customdata[1]} to %{customdata[2]}'
            '<br>Missing Measurements: %{customdata[3]}<extra></extra>'
        ),
    ))
    figure.update_layout(title='Monthly Consumption — Loaded Data Only', showlegend=False)
    figure.update_xaxes(title='Billing Month', type='category')
    figure.update_yaxes(title=f'Consumed Quantity ({unit})', tickformat=',.2f', zeroline=True)
    return chart_layout(figure, 420)


def databricks_consumption_enabled(mode: str, context, flag: str | None) -> bool:
    """Public/demo profiles never unlock real billing, even with the flag set."""
    return bool(
        str(flag).strip().lower() == 'true'
        and mode == 'iap'
        and context is not None
        and context.identity.provider == 'iap'
        and context.is_admin
        and not context.portfolio_demo
        and context.environment == 'prod'
    )
