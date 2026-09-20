# SQL scripts

This directory is the source of truth for all project SQL:

- `infrastructure/`: Unity Catalog and GCS administrative objects, executed
  manually before the first deployment
- `gold/table_creation/`: idempotent DDL for dimensions, the fact table, and
  the bridge table
- `gold/data_loading/`: dimension, tag, and fact loading
- `datamarts/table_refresh/`: transformation followed by creation or
  replacement of the fourteen analytical tables

`src/finops_cloud/sql_runner.py` loads these files dynamically and executes
them through `spark.sql()`. The packaging configuration also embeds them in the
Databricks wheel as data files. There is no duplicate SQL copy under `src/`.

During development, the runner automatically finds this root-level directory.
`FINOPS_SQL_ROOT` can select another controlled path for testing without
changing Python code.

The model and execution order are documented in `../docs/data_model.md`.
