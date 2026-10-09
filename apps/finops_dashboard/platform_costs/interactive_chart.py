"""Local Plotly hover interaction, confined to approved Platform Costs aggregates."""

from functools import lru_cache
import json
from pathlib import Path

from plotly.offline import get_plotlyjs
import streamlit.components.v2 as components


SCRIPT = Path(__file__).with_name('interaction.js')


@lru_cache(maxsize=1)
def plotly_bundle():
    # Ship the installed Plotly bundle: no CDN, extra key, or external data request.
    bundle = 'const CostPlotly = (() => { const module = {exports: {}};\n' + get_plotlyjs() + '\nreturn module.exports; })();\n'
    return bundle


def chart_component():
    # Register in the active runtime (including independent AppTest runtimes).
    return components.component('platform_cost_hover_chart',
        html='<div class="platform-cost-interactive-chart" aria-label="Platform costs chart"></div>',
        css='.platform-cost-interactive-chart {width:100%;color:var(--st-text-color);font-family:var(--st-font);}',
        js=plotly_bundle() + SCRIPT.read_text(), isolate_styles=False)


def render_cost_chart(figure):
    # Pass records as structured data, never interpolate source strings into JS/HTML.
    chart_component()(data={'figure': json.loads(figure.to_json())},
                      key='platform_cost_hover_chart', width='stretch', height=510)
