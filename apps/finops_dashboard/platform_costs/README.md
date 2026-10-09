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

GCP amounts retain signed credits; net cost = cost + credits. Databricks cost is
a published-list **estimate**, not a paid invoice. Different currencies remain
separate; no total combines GCP bills with Databricks estimates. Marketplace
Databricks charges may overlap. All automatically collected months remain partial
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
GCP net costs stay on the left
axis (export currency, currently EUR), and Databricks list-price estimates stay
on the right (currently USD). Both remain visible; there is no global currency
filter hiding a provider. If a provider has multiple currencies, its own selector
chooses one before aggregation. Axis titles and tooltips retain the currency;
the axes use the theme's neutral text color and are titled `Cost in Euro` (left)
and `Cost in USD` (right, rotated 180° from its original orientation) for the current source currencies. Titles follow the
selected currency if it changes; provider names remain in the legend.
Databricks tooltips also show net DBUs. Column heights are not a direct cost
comparison: *Separate currency scales — no currency conversion. Column heights do
not directly compare costs.* This note uses 12 px; legends and axis titles use 14 px.
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

Daily publication uses snapshot version 3 with allowlisted `daily_records` and
derived monthly `records`. The reader validates their reconciliation before
display. Legacy monthly version 2 remains readable during rollout; Daily is not
offered until daily data is published. The daily and monthly datasets are never
added together. Both sources must be present. The GCS path and reader IAM stay
unchanged; no dashboard access to raw billing or new cloud key is required.

The Databricks query deliberately selects published prices in USD. An EUR label
would require actual EUR prices or a sourced, dated FX policy; no implicit
conversion is performed. GCP keeps the currency reported by its export.

## Implementation and manual rollout

Follow [the installation guide](../../../docs/platform_costs_setup.md). The source
SQL lives only in `platform/common/sql/monitoring/platform_costs`; the thin
notebook is in `platform/common/notebooks/monitoring`. No CSV download, Git commit
of cost data or recurring Cloud Build is required to refresh automatic-mode data.
None of the cloud resources, grants, SQL setup or schedules is installed by merely
pulling this code. Existing Azure pipelines must not be rerun for this feature.
