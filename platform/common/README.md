# Common Databricks artifacts

This folder is the single source of truth for artifacts shared by Serverless
and Classic Compute:

- `notebooks/pipelines`: daily, monthly-close, and monthly-backfill entry points;
- `notebooks/operations`: environment, initialization, discovery, and daily controls;
- `sql/controls`: reset and blocking DEV/PROD controls;
- `sql/gold`: Gold table creation and month loading;
- `sql/datamarts`: certified analytical table refreshes.
- `sql/monitoring`: Job-run duration, DBU, and list-cost analysis.

Do not copy these files into a scenario folder. Scenario Jobs must reference
the common paths directly.
