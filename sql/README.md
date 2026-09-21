# SQL scripts

- `infrastructure/`: numbered scripts run manually in a SQL Warehouse to
  verify RAW, register `finops_raw`, create DEV schemas, and create OPS tables;
- `maintenance/`: explicit DEV reset and read-only validation scripts;
- `gold/table_creation/`: Gold dimensions, bridge, and fact DDL;
- `gold/data_loading/`: month-scoped dimension, tag, and fact loading;
- `datamarts/table_refresh/`: fourteen certified analytical tables.

The transformation SQL is loaded by `src/finops_cloud/sql/runner.py`. The
administration scripts remain directly visible for manual execution and are not
silently run by a setup notebook.
