# Technical decisions

## Two FinOps scopes

Azure business analytics consumes synthetic FOCUS files and publishes governed
cost products. Platform FinOps consumes real provider billing and Databricks
usage to assess the resources used to produce those products. The workflows
share infrastructure, but not their source datasets or financial meaning.
See the [documentation index](README.md) for the two scopes and shared guides.

## Source authority

- `finops_raw.landing.focus` is the shared external source volume for DEV and
  PROD. Retention does not itself enforce object immutability.
- Daily files are provisional while a month is open.
- Monthly billing is detailed and authoritative for a closed month.
- Daily and monthly sources are never added together in the fact table.
- Billing replaces the same month in Silver and Gold through separate table
  writes, not one cross-table transaction; replay and reconciliation remain necessary.

## Catalog isolation

Business tables stay isolated in `finops_dev` and `finops_prod`. The
environment-independent `finops_ops.audit` schema stores pipeline evidence.
Its five tables have an explicit `environment` column, and all lookups and
writes are scoped to it.

```text
finops_raw.landing
        ├── DEV → finops_dev.{bronze,silver,gold,datamart}
        └── PROD → finops_prod.{bronze,silver,gold,datamart}

DEV + PROD audits → finops_ops.audit
```

## Retention

RAW files stay in `gs://dtl_finops/focus`. Automatic archival is disabled in
`config/common.toml`; otherwise a DEV close could remove the source before PROD
processes it. The archival module remains available for a later retention policy
that coordinates all consuming environments.

## Analytical model

Gold contains ten dimensions, one resource/tag bridge, and
`fact_finops_cost_usage`. Fourteen datamarts reproduce the analytical outputs.
SQL owns physical structures and transformations; Python controls execution and
passes validated identifiers.

## Platform monitoring and public serving

Private Databricks monthly DBU views and their controls live under
`platform/common/sql/monitoring/databricks`. Job attribution is a separate
monitoring query; workspace totals are not exact workload costs.

The prepared Platform Costs workflow aggregates GCP billing in BigQuery,
exports completed private GCS batches, and combines them with Databricks usage
and historical list prices. It publishes a validated OPS snapshot and an
approved private JSON object. Cloud Run reads only the public-approved aggregate,
not the raw billing source, workspace telemetry or collection audit. Separate
export and runtime identities preserve that boundary; effective inherited IAM
grants must be reviewed. Cloud setup and scheduled acceptance are still manual.

Azure carbon scenarios illustrate hypothetical emissions over synthetic VM-hours.
They are not the measured footprint of the platform; DBUs and currency have no
direct conversion to energy in this implementation.
