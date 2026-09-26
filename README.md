# FinOps Cloud Data Platform

Databricks/GCP implementation of a FOCUS cost platform. Monthly Parquet files
are read from one RAW source, transformed through Bronze and Silver, loaded into
the Gold star schema, then published as certified datamarts.

## Catalogs

- `finops_raw.landing`: source External Volumes used by DEV and PROD;
- `finops_dev`: DEV Bronze, Silver, Gold, and datamart schemas;
- `finops_prod`: PROD Bronze, Silver, Gold, and datamart schemas;
- `finops_ops.audit`: operational history for both environments. Every row has
  an `environment` column.

RAW files are not moved after DEV processing. Automatic archival is disabled so
PROD can independently consume exactly the same source files.

## Repository layout

```text
platform/serverless/            Default Storage setup and Serverless Jobs
platform/classic_compute/       Managed GCS setup and Classic Job adapter
platform/common/notebooks/      Pipeline and operational notebooks shared by both
platform/common/sql/            Controls, Gold, and datamart SQL shared by both
config/                         Environment and common RAW/OPS configuration
contracts/                      Versioned FOCUS Data Contract
src/finops_cloud/audit/         Runs, snapshots, and reconciliation
src/finops_cloud/medallion/     Bronze, Silver, Gold, contract, and Delta logic
src/finops_cloud/storage/       Daily discovery and optional GCS archival
src/finops_cloud/sql/           SQL loader and renderer
src/finops_cloud/pipelines/     End-to-end orchestration
apps/finops_dashboard/          Read-only Streamlit Databricks App
```

## Manual rebuild and load

Follow [docs/manual_platform_rebuild.md](docs/manual_platform_rebuild.md).
The structure-only notebook is
`platform/common/notebooks/operations/initialize_empty_data_tables.ipynb`; run
it once for DEV and once for PROD before loading. The important entry point for
a historical monthly load is
`platform/common/notebooks/pipelines/03_billing_backfill.ipynb`: choose `environment`,
`start_month`, and `end_month`, then run each cell. RAW archival is disabled by
the common configuration.

After the manual DEV load and controls, follow
[docs/databricks_jobs_manual_setup.md](docs/databricks_jobs_manual_setup.md) to
build and capture the three-task DAG in the Databricks UI.

After that DEV Job succeeds, follow
[docs/databricks_prod_promotion.md](docs/databricks_prod_promotion.md) for the
separate PROD preflight, canary, historical load, and post-load controls.

For provisional daily files in an open month, follow
[docs/databricks_daily_dev_to_prod.md](docs/databricks_daily_dev_to_prod.md) to
test discovery, DEV loading, validation, and controlled PROD promotion before
adding the daily schedule.

After PROD validation, the read-only Streamlit application in
[`apps/finops_dashboard`](apps/finops_dashboard) exposes the certified datamarts,
cost definitions, FOCUS column dictionary, data quality and pipeline operations.
Follow [docs/databricks_streamlit_app.md](docs/databricks_streamlit_app.md) to
deploy and verify it manually in Databricks Apps.

## Processing flow

```text
gs://dtl_finops/focus/monthly/billing-YYYY-MM.parquet
                         ↓
finops_raw.landing.focus External Volume
                         ↓
Bronze → Data Contract → canonical Silver
                         ↓
Gold dimensions + fact → certified datamarts
                         ↓
SQL Warehouse / dashboard

All run/snapshot/reconciliation evidence → finops_ops.audit
```

Monthly billing is authoritative. For each selected month, the pipeline records
`BEFORE`, `SOURCE`, and `AFTER`, replaces that month atomically in Silver and
Gold, refreshes the datamarts, and stores the reconciliation in OPS.

## Main notebooks

- `01_daily_incremental.ipynb`: ingest a daily provisional file;
- `02_monthly_close.ipynb`: close one month from billing;
- `03_billing_backfill.ipynb`: load an inclusive range of billing months;
- `discover_daily_files.ipynb`: inventory and select the oldest new daily file;
- `validate_daily_load.ipynb`: block promotion when daily reconciliation fails;
- `environment_check.ipynb`: validate configuration and required namespaces;
- `initialize_empty_data_tables.ipynb`: create the 30 empty business tables for
  one selected environment.

## Local validation

```bash
PYTHONPATH=src python3 -m unittest discover -s tests/unit -v
```

No token, service-account key, or Databricks secret belongs in Git.
