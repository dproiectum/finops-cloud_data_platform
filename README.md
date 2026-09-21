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
config/                         Environment and common RAW/OPS configuration
contracts/                      Versioned FOCUS Data Contract
notebooks/pipelines/            Manual pipeline entry points
notebooks/operations/           Environment check and optional archive retry
sql/platform_setup/             Ordered manual rebuild and validation scripts
sql/gold/                       Gold DDL and loading SQL
sql/datamarts/                  Certified datamart SQL
src/finops_cloud/audit/         Runs, snapshots, and reconciliation
src/finops_cloud/medallion/     Bronze, Silver, Gold, contract, and Delta logic
src/finops_cloud/storage/       Optional GCS archival
src/finops_cloud/sql/           SQL loader and renderer
src/finops_cloud/pipelines/     End-to-end orchestration
```

## Manual rebuild and load

Follow [docs/manual_platform_rebuild.md](docs/manual_platform_rebuild.md).
The important entry point for a historical monthly load is
`notebooks/pipelines/03_billing_backfill.ipynb`: choose `environment`,
`start_month`, and `end_month`, keep `archive=false`, then run each cell.

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
- `environment_check.ipynb`: validate configuration and required namespaces.

## Local validation

```bash
PYTHONPATH=src python3 -m unittest discover -s tests/unit -v
```

No token, service-account key, or Databricks secret belongs in Git.
