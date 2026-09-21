# SQL scripts

- `platform_setup/`: the complete manual platform reconstruction sequence,
  numbered from the four-catalog reset through DEV post-load validation;
- `gold/table_creation/`: Gold dimensions, bridge, and fact DDL;
- `gold/data_loading/`: month-scoped dimension, tag, and fact loading;
- `datamarts/table_refresh/`: fourteen certified analytical tables.

The transformation SQL is loaded by `src/finops_cloud/sql/runner.py`. Platform
setup scripts remain directly visible for manual execution and are not silently
run by a setup notebook.
