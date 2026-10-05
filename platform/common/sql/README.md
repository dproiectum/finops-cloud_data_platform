# Common SQL

- `controls/`: destructive reset plus blocking empty, DEV, and PROD controls;
- `gold/table_creation/`: Gold dimensions, bridge, and fact DDL;
- `gold/data_loading/`: month-scoped dimension, tag, and fact loading;
- `datamarts/table_refresh/`: fourteen certified analytical tables.
- `monitoring/`: reusable DBU, list-cost, and Job-run observability queries.
- `security/`: additive manual dashboard metadata setup and synthetic entitlement
  checks; viewer authorization is not implemented by these scripts.

`src/finops_cloud/sql/runner.py` uses this directory as its source SQL root.
The setup SQL that differs by compute scenario is intentionally stored under
`platform/serverless/sql` and `platform/classic_compute/sql`.
