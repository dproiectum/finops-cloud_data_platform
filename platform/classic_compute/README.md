# Classic Compute scenario

This folder contains only artifacts specific to the Belgian All-Purpose
Classic Compute scenario. Shared notebooks and SQL live under
`platform/common`.

## Prerequisites

1. Create `gs://dtl_finops-unitycatalog-euw1` in `europe-west1`.
2. Create Storage Credential `finops_uc_storage_be`.
3. Grant its generated GCP service account object read/write/delete access.
4. Stop every FinOps Job before a destructive reset.

## Manual platform creation

1. Run `sql/00_validate_managed_storage.sql` and inspect every result.
2. Run `../common/sql/controls/00_drop_all_project_catalogs.sql` only for a full reset.
3. Run `sql/01_create_raw.sql`.
4. Run `sql/02_create_dev.sql`.
5. Run `sql/03_create_prod.sql`.
6. Run `sql/04_create_ops.sql`.
7. Run `../common/notebooks/operations/initialize_empty_data_tables.ipynb`
   once with `environment=dev` and once with `environment=prod`.
8. Run `../common/sql/controls/01_validate_empty_platform.sql`.

Managed Delta data is written below catalog-specific roots in
`gs://dtl_finops-unitycatalog-euw1/catalogs`. The source bucket
`gs://dtl_finops` remains external and unchanged.

For a multi-task Job, use
`notebooks/validate_loaded_environment_classic.ipynb` on the same All-Purpose
Classic cluster as the loading tasks. It executes the common blocking controls
with Spark because a Job that uses a Classic SQL Warehouse is limited to one
task. `jobs/billing-dev-full_load_by_month-no_photon.yml` records the DEV
benchmark template and `jobs/billing-prod-full_load_by_month-with_photon.yml`
records the separate PROD benchmark template. Their `existing_cluster_id`
belongs to the current Belgian workspace and must be updated if the All-Purpose
cluster is recreated. Photon itself is a cluster setting; the filename only
documents the configuration used for that benchmark run.

`jobs/daily_dev_to_prod.yml` is the unscheduled Classic daily workflow. It
discovers the oldest RAW daily file still missing from PROD, validates it in
DEV, and promotes it automatically after the DEV controls. Optional date and
source overrides remain available for recovery only.
