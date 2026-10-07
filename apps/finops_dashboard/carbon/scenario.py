"""A small what-if model over ALREADY AUTHORIZED synthetic consumption rows.

One eligible billing Hour is hypothetically one equivalent VM-hour. All eligible
SKUs get the same user-assumed IT power; this is NOT a provider energy coefficient
or a resolved physical VM mapping. Power and PUE defaults are teaching examples.
The published grid references are annual 2025 values applied unchanged to every
loaded billing period. Results cover electricity only, without lifecycle emissions
or clean-energy procurement. No DBU, currency or storage-to-energy conversion.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import math
from pathlib import Path

import pandas as pd


VM_SERVICES = frozenset({'Virtual Machines', 'Virtual Machine Scale Sets'})
MODELLED = 'Modelled — hypothetical VM-hour equivalence'


def load_grid_references() -> dict:
    """Pinned, sourced metadata; no runtime HTTP lookup or silent fallback."""
    data = json.loads(Path(__file__).with_name('grid_references.json').read_text())
    if data.get('unit') != 'gCO2e/kWh' or not isinstance(data.get('reference_year'), int):
        raise ValueError('Invalid grid reference provenance or units.')
    rows = data.get('references', [])
    if not rows or len({row['region'] for row in rows}) != len(rows):
        raise ValueError('Grid references must have unique regions.')
    for row in rows:
        value = row['grid_gco2e_per_kwh']
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
            raise ValueError('Invalid grid carbon intensity.')
    return data


@dataclass(frozen=True)
class Scenario:
    # Editable assumptions, NOT values supplied by Azure, Google or Databricks.
    power_watts: float = 50.0
    pue: float = 1.2
    primary_region: str = 'europe-west1'
    comparison_region: str = 'europe-west3'

    def __post_init__(self):
        for name, value, minimum in [('power_watts', self.power_watts, 0), ('pue', self.pue, 1)]:
            if (isinstance(value, bool) or not isinstance(value, (int, float))
                    or not math.isfinite(value) or value < minimum
                    or (name == 'power_watts' and value == 0)):
                raise ValueError(f'Invalid scenario {name}.')
        regions = {row['region'] for row in load_grid_references()['references']}
        if self.primary_region not in regions or self.comparison_region not in regions:
            raise ValueError('Unknown scenario grid reference.')


def estimate_scenario(frame: pd.DataFrame, scenario: Scenario) -> pd.DataFrame:
    """Conservative coverage: exclude ambiguous, incomplete or corrected groups.

    The input query has already scoped by application then grouped by month,
    service, SKU and unit. A group's single invalid/negative measurement therefore
    excludes the whole group; do not reconstruct gross positive usage from its net
    sum or clip negatives. This conservative scope is not a whole-cloud inventory.
    """
    result = frame.copy(deep=True)
    if result.duplicated(['billing_month', 'service_name', 'sku_id', 'consumed_unit']).any():
        raise ValueError('Authorize and aggregate consumption groups before scenario calculation.')
    quantity = pd.to_numeric(result['consumed_quantity'], errors='coerce')
    counters = result[['usage_rows', 'measured_usage_rows', 'missing_measurement_rows',
                       'negative_quantity_rows']].apply(pd.to_numeric, errors='coerce')
    finite_quantity = quantity.map(lambda value: pd.notna(value) and math.isfinite(float(value)))
    valid_counters = (
        counters.notna().all(axis=1)
        & counters.map(lambda value: pd.notna(value) and math.isfinite(float(value))).all(axis=1)
        & counters.ge(0).all(axis=1)
        & counters.mod(1).eq(0).all(axis=1)
        & counters['usage_rows'].gt(0)
        & (counters['measured_usage_rows'] + counters['missing_measurement_rows']).eq(counters['usage_rows'])
        & counters['negative_quantity_rows'].le(counters['measured_usage_rows'])
    )
    known_sku = result['sku_id'].notna() & ~result['sku_id'].fillna('').astype(str).str.strip().str.lower().isin({'', 'unknown'})
    status = pd.Series('Modelled', index=result.index, dtype='object')
    # Earlier conditions take priority and classify exclusions transparently.
    checks = [
        (~result['service_name'].isin(VM_SERVICES), 'Not Estimated — unsupported service'),
        (~result['consumed_unit'].eq('Hours'), 'Not Estimated — unsupported unit'),
        (~known_sku, 'Not Estimated — missing SKU'),
        (~valid_counters, 'Not Estimated — invalid measurement counters'),
        (counters['negative_quantity_rows'].gt(0) | quantity.lt(0),
         'Not Estimated — signed correction group'),
        (counters['missing_measurement_rows'].gt(0) | ~finite_quantity,
         'Not Estimated — incomplete measurements'),
    ]
    for mask, label in checks:
        status.loc[status.eq('Modelled') & mask] = label
    result['scenario_status'] = status.replace('Modelled', MODELLED)
    eligible = result['scenario_status'].eq(MODELLED)
    result['modelled_usage_rows'] = counters['usage_rows'].where(eligible, 0)
    result['scenario_vm_hours'] = quantity.where(eligible)
    result['scenario_energy_kwh'] = result['scenario_vm_hours'] * scenario.power_watts / 1000 * scenario.pue
    references = {row['region']: row['grid_gco2e_per_kwh'] for row in load_grid_references()['references']}
    result['scenario_kgco2e'] = result['scenario_energy_kwh'] * references[scenario.primary_region] / 1000
    result['comparison_kgco2e'] = result['scenario_energy_kwh'] * references[scenario.comparison_region] / 1000
    measures = ['scenario_vm_hours', 'scenario_energy_kwh', 'scenario_kgco2e', 'comparison_kgco2e']
    if not result[measures].map(lambda value: pd.isna(value) or math.isfinite(float(value))).all().all():
        raise ValueError('Scenario parameters produce non-finite results.')
    return result


def monthly_scenarios(frame: pd.DataFrame) -> pd.DataFrame:
    """No missing-month fill, no fabricated zero for an unmodelled month."""
    rows = []
    for month, source in frame.groupby('billing_month', sort=True):
        first = pd.to_datetime(source['first_loaded_charge_date']).min()
        last = pd.to_datetime(source['last_loaded_charge_date']).max()
        period = pd.Period(str(month), freq='M')
        if pd.isna(first) or pd.isna(last):
            status = 'Loaded dates unavailable'
        elif first.normalize() != period.start_time.normalize() or last.normalize() != period.end_time.normalize():
            status = 'Partial loaded dates — not a full-month comparison'
        else:
            status = 'Calendar date window present — completeness not certified'
        row = {
            'billing_month': month,
            'usage_rows': source['usage_rows'].sum(min_count=1),
            'modelled_usage_rows': source['modelled_usage_rows'].sum(min_count=1),
            'first_loaded_charge_date': first,
            'last_loaded_charge_date': last,
            'period_status': status,
        }
        for column in ['scenario_vm_hours', 'scenario_energy_kwh', 'scenario_kgco2e', 'comparison_kgco2e']:
            row[column] = source[column].sum(min_count=1)
        rows.append(row)
    return pd.DataFrame(rows)
