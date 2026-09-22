"""Shared presentation helpers."""

from __future__ import annotations

import pandas as pd


def money(value: object) -> str:
    if value is None or pd.isna(value):
        value = 0
    return f"{float(value):,.2f} €"


def integer(value: object) -> str:
    if value is None or pd.isna(value):
        value = 0
    return f"{int(value):,}"


def percent(value: object) -> str:
    if value is None or pd.isna(value):
        value = 0
    return f"{float(value):,.2f}%"


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
    )
    return figure
