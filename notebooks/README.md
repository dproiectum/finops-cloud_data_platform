# Databricks notebooks

These notebooks are interactive pipeline entry points. They define parameters,
call maintained functions from `src/finops_cloud`, and display results. They do
not duplicate Python business logic or SQL scripts.

### Pipelines

- `pipelines/01_daily_incremental.ipynb`: daily ingestion
- `pipelines/02_monthly_close.ipynb`: monthly replacement and close
- `pipelines/03_billing_backfill.ipynb`: initial load for a range of billing months
- `pipelines/00_all_monthly_to_gold.ipynb`: discover and process every uploaded monthly billing

### Operations

- `operations/environment_check.ipynb`: catalog and volume checks
- `operations/archive_retry.ipynb`: retry a pending GCS archive operation
- `operations/check_tables_empty.ipynb`: publish the table empty/non-empty task value
- `operations/reset_all_tables.ipynb`: protected reset without deleting GCS sources

Databricks widgets expose runtime parameters for manual execution. Production
Jobs use the corresponding Python entry points under `scripts/`. An engineer
can edit notebook parameters and execute one cell at a time during a
demonstration or investigation. Notebook outputs must not be stored in Git.
