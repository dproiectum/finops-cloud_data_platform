# Documentation by FinOps scope

This project supports Azure cost analytics and applies FinOps to its own cloud
operation. The guides below distinguish those scopes without duplicating shared
infrastructure or changing deployed pipeline paths.

## Azure FinOps analytics

- [Data model](data_model.md): charge grain, Gold dimensions and datamarts.
- [Monthly orchestration](databricks_jobs_manual_setup.md): billing backfill Jobs.
- [PROD publication](databricks_prod_promotion.md): loading and promotion controls.
- [Daily DEV-to-PROD](databricks_daily_dev_to_prod.md): incremental orchestration.
- [Azure consumption SQL](../platform/common/sql/consumption): existing synthetic
  usage views and validation; no new ingestion or measured carbon inventory.

## Platform FinOps

- [Platform Costs installation](platform_costs_setup.md): BigQuery export,
  Databricks collection, restricted GCS publication and Cloud Run reading.
- [Private Databricks telemetry](../platform/common/sql/monitoring/databricks):
  availability, monthly DBUs and reconciliation; not a public dashboard source.
- [Job-run attribution](../platform/common/sql/monitoring/01_job_run_dbu_and_list_cost.sql):
  DBUs and list-price attribution, with Classic cluster-sharing limitations.
- [Belgium completion plan](databricks_belgium_completion_plan.md): migration
  acceptance tasks and the evidence still needed for comparisons.

Workspace consumption, attributed workload estimates and invoices are different
measures. Keep currencies, credits, covered dates and price bases explicit. A
regional or Photon comparison is valid only with comparable inputs and outputs.
No conversion from DBU or currency to measured emissions is implemented.

## Shared architecture, security and operation

- [Architecture decisions](architecture.md).
- [GCS and Unity Catalog access](databricks_gcs_setup.md).
- [Manual platform setup](manual_platform_rebuild.md): choose Classic or
  Serverless; catalog deletion is for an approved reset only.
- [Dashboard and deployment](../apps/finops_dashboard/README.md).
- [Authorization modes](../apps/finops_dashboard/security/README.md): public
  synthetic profiles, application predicates and separate private IAP mode.
- [Privacy rebuild](privacy_rebuild.md): guarded recovery, not routine ingestion.
- [Local and integration validation](../tests/integration/README.md).

Shared code remains under `platform/common`; compute-specific setup and Job
bindings remain under `platform/serverless` or `platform/classic_compute`.
The three private Databricks consumption SQL files moved from `consumption/` to
`monitoring/databricks/`. Their filenames, view names and query logic are retained.
No catalog reset or business pipeline rerun follows from this reorganization.
