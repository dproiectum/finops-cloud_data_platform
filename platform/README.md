# Databricks platform artifacts

The repository is organized first by execution scenario:

- `serverless/`: Default Storage and Serverless-specific Jobs;
- `classic_compute/`: explicit GCS managed locations and Classic Job adapters;
- `common/`: notebooks and SQL shared by both scenarios.

Choose exactly one scenario for catalog creation. Both scenarios reuse the same
pipeline notebooks, blocking controls, Gold model, and datamarts from `common`.
