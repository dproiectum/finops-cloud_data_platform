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

- `operations/environment_check.ipynb`: verify selected catalogs, schemas, and
  source Volume before loading;
- `operations/archive_retry.ipynb`: reserved for a future archival policy.
  Automatic archival is currently disabled because RAW is consumed by DEV and
  PROD.

Catalog creation, DEV reset, and validations are deliberately kept as visible,
ordered SQL scripts under `sql/platform_setup`. Run them manually in a SQL
Warehouse by following `docs/manual_platform_rebuild.md`.
