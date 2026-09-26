# SQL scripts

- `platform_setup_serverless/`: the complete workflow for a Serverless
  workspace using Databricks Default Storage;
- `platform_setup_classic_be/`: the complete workflow for the Belgian Classic
  workspace using the dedicated managed-data bucket
  `gs://dtl_finops-unitycatalog-euw1`;
- `gold/table_creation/`: Gold dimensions, bridge, and fact DDL;
- `gold/data_loading/`: month-scoped dimension, tag, and fact loading;
- `datamarts/table_refresh/`: fourteen certified analytical tables.

The transformation SQL is loaded by `src/finops_cloud/sql/runner.py`. Platform
setup scripts remain directly visible for manual execution and are not silently
run by a setup notebook. Choose one platform setup folder for a workspace and
do not mix creation scripts from both scenarios.
