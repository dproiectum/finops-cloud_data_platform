# Platform Costs — approved aggregates only

This module renders **About the Project → Platform Costs**. It never queries raw
GCP billing or Databricks system tables. Business demo profiles do not change the
publication scope. Costs are separate from the synthetic Azure portfolio.

## Modes

- `FINOPS_PLATFORM_COSTS_MODE=bundled` (default): an explicitly offline snapshot.
  The repository snapshot is empty and unapproved, not invented expenditure.
- `FINOPS_PLATFORM_COSTS_MODE=gcs`: read the private object configured by
  `FINOPS_PLATFORM_COSTS_GCS_URI=gs://dtl_finops/platform_costs/published/latest.json`
  using the Cloud Run runtime service account (Application Default Credentials).
  There is no service-account key, public bucket or anonymous download.

Automatic mode caches successful downloads for five minutes, checks extraction
freshness on every page run (48 hours by default), enforces a 4 MiB size limit and
the exact publication contract. An access failure, invalid or stale object remains
unavailable; there is no silent bundled fallback. Refresh the page after an update.

The single validation/publication contract is `model.py` plus `snapshot.py`.
The collector notebook imports it from this directory so serving and collection
cannot silently disagree. The Docker app remains self-contained.

Billing exports retain signed credits; net cost = cost + credits. The BigQuery
export explicitly includes native services in `global-repeater-355412` and the
Databricks service in the Marketplace project `pr-5193ad409e7b591`. Marketplace
rows are categorized as `provider=Databricks, cost_basis=billing_export`; DBU
reference rows use `provider=Databricks, cost_basis=list_estimate` instead.
The monthly/daily key already includes `cost_basis`: no new Delta column or
duplicate-source file is needed. Project identities never enter the public JSON.

`Total Platform Cost` adds only the two billing-export components in the same
currency, currently EUR. It is a recorded export total, not a final invoice or
proof of payment; taxes/charges outside the explicit project scope can be absent.
Missing components or incompatible currencies yield an unavailable total, not
an invented zero or FX conversion. The separate Databricks published-list USD
estimate is **never** added to this total. All automatically collected months remain partial
until independently reconciled; extraction freshness does not prove source coverage.
DBUs are not energy or a supported carbon conversion.

## Yearly, monthly and daily views

`View by` offers **Daily**, **Monthly**, then **Yearly**. Shared `Year` and `Month` filters
select `All Years` or one year (starting at 2025), and `All Months` or a calendar
month. The chosen filters persist across views. A month selected across all
years selects that calendar month in each year. Yearly sums the filtered monthly
records; Daily shows UTC start-day costs across the selected period, not only one
month. Chart, tiles, breakdowns and details use the same scope. A year with no
published records keeps the calendar axes and an italic `No published record`
annotation, with no columns or invented zero costs. Source availability may lag.

One grouped-column chart switches grain with `View by`. Columns are side by
side, never stacked or overlaid, with a distinct offset group per provider.
The current billing chart places GCP services and Databricks Marketplace net
costs on the same EUR axis. Three tiles show GCP Services Net Cost, Databricks
Marketplace Net Cost and Total Platform Cost. USD list-price estimates and DBUs
appear in a separate, initially collapsed reference section, with their own chart
and table but the same date filters. Billing details do not show meaningless DBUs.
If billing currencies differ, the combined chart/total is unavailable and the
provider panels remain separate. No currency conversion is performed.

Legacy snapshots retain the former EUR/USD dual-axis view and display a warning:
the GCP component does not include Marketplace billing and no complete platform
total is available. The separate-axis note still applies to this legacy view.
In both views, the italic chart note uses 12 px; legends and axis titles use 14 px.
The note is inside the chart below the legend, with the same left anchor, and
wraps on narrow screens. The legend names `Google Cloud (GCP)` explicitly.
Hover shows only the pointed column. A scoped Streamlit v2 component uses the
installed Plotly bundle (no CDN) to retain that column's opacity and fade all
other columns to 22%; leaving restores the original colors. The interaction is
browser-only: it neither reruns collection nor changes published costs. It
tracks the native light/dark theme and cleans up listeners when unmounted.
Both providers use the same light neutral tooltip background and dark text;
the provider name stays inside that bubble, without a blue/coral secondary box.

Provider colors are Google Ecosystem Blue `#4285F4`
([Google reference](https://firebase.google.com/brand-guidelines)) and a user-selected
coral `#FF543D` sampled exactly from the user's supplied swatch for Databricks.
This is not presented as an official Databricks brand color. These
colors apply only to Platform Costs. Service breakdowns use separate provider
panels, never a shared EUR/USD ranking, and detail amounts carry their row currency.

Marketplace publication uses snapshot version 4 with allowlisted `daily_records`
and derived monthly `records`. All three components are required: native GCP,
Marketplace billing, and Databricks USD usage estimates. The reader validates
their reconciliation before display. Source dates for both billing components
are checked against the BigQuery extraction, not the DBU extraction.
The GCP COMPLETE manifest is version 3 with `billing_scope=finops_and_databricks_marketplace`.
Legacy monthly version 2 and daily version 3 remain readable during rollout; Daily is not
offered until daily data is published. The daily and monthly datasets are never
added together. Both sources must be present. The GCS path and reader IAM stay
unchanged; no dashboard access to raw billing or new cloud key is required.
The upgraded collector may preview a legacy export but cannot publish it:
Marketplace billing must be present before replacing `latest.json`.

The DBU query deliberately selects published prices in USD. Marketplace EUR
comes directly from Cloud Billing, not an estimated USD-to-EUR conversion.
The USD estimate is not expected to match a legacy Databricks Usage screen that
has different refresh times, date filters or product coverage.

## Implementation and manual rollout

Follow [the installation guide](../../../docs/platform_costs_setup.md). The source
SQL lives only in `platform/common/sql/monitoring/platform_costs`; the thin
notebook is in `platform/common/notebooks/monitoring`. No CSV download, Git commit
of cost data or recurring Cloud Build is required to refresh automatic-mode data.
None of the cloud resources, grants, SQL setup or schedules is installed by merely
pulling this code. Existing Azure pipelines must not be rerun for this feature.
