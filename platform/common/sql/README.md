# Common SQL

- `controls/`: destructive reset plus blocking empty, DEV, and PROD controls;
- `gold/table_creation/`: Gold dimensions, bridge, and fact DDL;
- `gold/data_loading/`: month-scoped dimension, tag, and fact loading;
- `datamarts/table_refresh/`: fourteen certified analytical tables.
- `monitoring/`: reusable DBU, list-cost, and Job-run observability queries.
- `consumption/`: manual source checks, additive ordinary consumption views and
  read-only reconciliation controls; no ingestion, source rewrite or carbon estimate.
- `security/`: additive manual dashboard metadata setup and synthetic entitlement
  checks; viewer authorization is not implemented by these scripts.

`src/finops_cloud/sql/runner.py` uses this directory as its source SQL root.
The setup SQL that differs by compute scenario is intentionally stored under
`platform/serverless/sql` and `platform/classic_compute/sql`.

## Consumption setup (manual, existing warehouse)

Run `consumption/00_check_azure_consumption.sql` and
`consumption/01_check_databricks_consumption.sql` first with your own identity.
Then execute these files in order in workspace-belgium SQL Editor:

1. `consumption/02_create_azure_consumption_view.sql`: creates only
   `finops_prod.datamart.v_consumption_monthly`, from the existing Gold allocation
   view. Application, service, SKU and unit remain separate. Missing measurements
   stay NULL; corrections keep their sign. Other charge categories are excluded.
2. `consumption/03_create_databricks_consumption_view.sql`: creates the metadata
   schema `finops_ops.monitoring` if absent and its
   `v_databricks_consumption_monthly` view over existing system billing records.
   It includes only the two project workspaces, GCP DBUs, since September 2026.
3. `consumption/04_validate_azure_consumption_view.sql`: two assertions plus a
   monthly measurement-coverage result. A successful assertion returns NULL.
4. `consumption/05_validate_databricks_consumption_view.sql`: one assertion plus
   monthly net DBUs by workspace/SKU/origin, including a Genie-free indicator.

Setup DDL can return **No rows returned** on success. Run every validation
statement and stop on an error. Coverage is measurement availability, not evidence
that a billing month is complete. Ordinary views store no duplicate dataset and
follow available source data; they need no reload or scheduled refresh. Querying
them still uses warehouse compute. These files are not added to ingestion Jobs.

No script changes current dashboard-serving views, grants permissions, or adds a
public page. Azure application dimensions allow later reuse of the live dashboard
authorization predicate, but the view itself is not a row-level security policy.
Real DBU telemetry is kept outside `datamart` and `audit`; a separate schema does
not override inherited privileges. Review access before granting any backend
permission. The selectable portfolio Admin persona is not authentication and
must not unlock real operational billing data. DBUs are neither monetary cost nor
energy/carbon; do not convert them without separately verified inputs.
