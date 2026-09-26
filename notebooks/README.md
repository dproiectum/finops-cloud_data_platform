# Databricks notebooks

The notebooks expose parameters and call the maintained code under
`src/finops_cloud`. They intentionally contain no duplicated transformation
logic.

## Pipelines

- `pipelines/01_daily_incremental.ipynb`: one provisional daily file;
- `pipelines/02_monthly_close.ipynb`: one authoritative billing month;
- `pipelines/03_billing_backfill.ipynb`: an inclusive monthly range. Use this
  notebook for the initial/full monthly load instead of maintaining a duplicate
  full-load notebook.

## Operations

- `operations/discover_daily_files.ipynb`: inventory daily Parquets, exclude
  closed months, and select the oldest source not yet loaded in Silver;
- `operations/validate_daily_load.ipynb`: reconcile one daily source through
  Bronze, Silver, Gold, datamarts, OPS, and DEV/PROD when validating PROD;
- `operations/environment_check.ipynb`: verify selected catalogs, schemas, and
  source Volume before loading.
- `operations/initialize_empty_data_tables.ipynb`: manually create all 30 empty
  business tables in DEV or PROD after a complete reset.

Automatic archival has no active notebook or Job because RAW is consumed by
both DEV and PROD.

Catalog creation, the four-catalog reset, and validations are deliberately kept
as visible, ordered SQL scripts under either `sql/platform_setup_serverless`
or `sql/platform_setup_classic_be`. Select one scenario for the workspace and
run it manually by following `docs/manual_platform_rebuild.md`.
