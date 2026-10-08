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

## Implementation and manual rollout

Follow [the installation guide](../../../docs/platform_costs_setup.md). The source
SQL lives only in `platform/common/sql/monitoring/platform_costs`; the thin
notebook is in `platform/common/notebooks/monitoring`. No CSV download, Git commit
of cost data or recurring Cloud Build is required to refresh automatic-mode data.
None of the cloud resources, grants, SQL setup or schedules is installed by merely
pulling this code. Existing Azure pipelines must not be rerun for this feature.
