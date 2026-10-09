# Databricks platform artifacts

The repository is organized first by execution scenario:

- `serverless/`: Default Storage and Serverless-specific Jobs;
- `classic_compute/`: explicit GCS managed locations and Classic Job adapters;
- `common/`: notebooks and SQL shared by both scenarios.

Choose exactly one scenario for catalog creation. Both scenarios reuse the same
pipeline notebooks, blocking controls, Gold model, and datamarts from `common`.

Platform Costs adds a separate monitoring workflow. Its manual Job templates in
each compute scenario reference one common notebook and start with a paused
schedule. They are not included in the business bundle. See
[the installation guide](../docs/platform_costs_setup.md).

Within `common`, `pipelines`/Gold/datamarts and Azure `consumption` support the
business analytics scope; `monitoring` supports Platform FinOps. Controls,
security, setup and deployment are shared. Private Databricks consumption SQL
now lives in `common/sql/monitoring/databricks`, without changing view names or
deployed business notebook paths. See the [scope index](../docs/README.md).
