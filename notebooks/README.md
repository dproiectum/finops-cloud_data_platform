# Databricks notebooks

These notebooks are interactive pipeline entry points. They define parameters,
call maintained functions from `src/finops_cloud`, and display results. They do
not duplicate Python business logic or SQL scripts.

- `00_environment_check.ipynb`: catalog and volume checks
- `01_daily_incremental.ipynb`: daily ingestion
- `02_monthly_close.ipynb`: monthly replacement and close
- `03_billing_backfill.ipynb`: initial load for a range of billing months
- `04_archive_retry.ipynb`: retry a pending GCS archive operation

Databricks widgets expose runtime parameters. Bundle Jobs populate them
automatically, while an engineer can edit them and execute one cell at a time
during a demonstration or investigation. Notebook outputs must not be stored
in Git.
