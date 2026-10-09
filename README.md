# FinOps Cloud Data Platform

**Live dashboard: [https://finops.allops.cloud](https://finops.allops.cloud)**

A Databricks/GCP data platform for cloud-cost reporting, showback, and cost
analysis. It processes synthetic Azure cost-and-usage data in FOCUS format,
publishes analytical datamarts, and serves a read-only Streamlit dashboard.
The portfolio data does not represent actual company expenditure.

This repository contains the cloud implementation. The independent data
generator and local proof of concept are separate projects.

## Two complementary FinOps scopes

| Scope | Inputs | Products and evidence |
| --- | --- | --- |
| Azure FinOps analytics | Synthetic Azure FOCUS cost-and-usage files | Governed datamarts, showback, pricing analysis, allocation and illustrative consumption/carbon scenarios. These are not actual company costs or measured emissions. |
| Platform FinOps | Real GCP billing exports and Databricks usage records | Private operational telemetry, approved Platform Costs aggregates, and evidence for cost/performance comparisons. List-price estimates are not paid invoices. |

The second scope measures the resources used to produce the first. It has a
separate collection workflow: it does not reload or modify the synthetic FOCUS
history. Both scopes reuse one dashboard and common operational components.
Platform Costs code is prepared; cloud installation and end-to-end acceptance
remain manual. See the [documentation index](docs/README.md) for each scope.

## Architecture

```text
Independent generator -> GCS source Parquet files
                              |
                 finops_raw.landing.focus (External Volume)
                              |
                 +------------+------------+
                 |                         |
             finops_dev                finops_prod
                 |                         |
        Each: Bronze -> Data Contract -> Silver -> Gold -> datamarts
                                                           |
                                              PROD -> SQL Warehouse
                                                           |
                                                 Streamlit / Cloud Run
                                                           |
                                                  finops.allops.cloud

DEV and PROD run/snapshot/reconciliation history -> finops_ops.audit
Classic managed Delta tables -> separate Unity Catalog GCS bucket
```

| Catalog | Purpose |
| --- | --- |
| `finops_raw` | Shared source files through the `landing.focus` External Volume. |
| `finops_dev` | DEV Bronze, Silver, Gold, and datamart schemas. |
| `finops_prod` | PROD Bronze, Silver, Gold, and datamart schemas. |
| `finops_ops` | Environment-aware audit history, security metadata, and monitoring views. |

Source files remain in `gs://dtl_finops/focus/`. Automatic archival after DEV
processing is disabled so PROD can independently consume the same files.
The Classic setup stores managed Delta tables separately in
`gs://dtl_finops-unitycatalog-euw1/`; this is not the source Parquet bucket.

See the [architecture](docs/architecture.md) and [data model](docs/data_model.md)
for the detailed responsibilities, tables, and analytical grain.

The independent Platform Costs path is:

```text
GCP billing -> BigQuery aggregation -> private GCS completed export
Databricks system.billing ----------> collector notebook
                                      |
                         finops_ops.monitoring snapshot and audit
                                      |
                         private approved GCS JSON summary
                                      |
                         About the Project -> Platform Costs
```

Only approved aggregates are served publicly. Detailed billing and workspace
telemetry are not exposed by selecting a portfolio profile. A future estimate
of this platform's emissions would need its own method and evidence; the Azure
carbon illustration does not measure the platform's footprint.

## Processing workflows

| Workflow | Entry point | Purpose |
| --- | --- | --- |
| Daily incremental | [`01_daily_incremental.ipynb`](platform/common/notebooks/pipelines/01_daily_incremental.ipynb) | Process provisional usage in an open month. |
| Monthly close | [`02_monthly_close.ipynb`](platform/common/notebooks/pipelines/02_monthly_close.ipynb) | Replace the selected month's provisional data with authoritative billing. |
| Historical backfill | [`03_billing_backfill.ipynb`](platform/common/notebooks/pipelines/03_billing_backfill.ipynb) | Load an inclusive range using `environment`, `start_month`, and `end_month`. |

Expected source paths:

```text
gs://dtl_finops/focus/daily/YYYY/MM/YYYY-MM-DD.parquet
gs://dtl_finops/focus/monthly/billing-YYYY-MM.parquet
```

Monthly billing is authoritative: it replaces the selected month rather than
being added to its provisional daily data. The pipelines record `BEFORE`,
`SOURCE`, and `AFTER` snapshots, refresh the datamarts, and store reconciliation
evidence in OPS. Discovery and validation tasks support controlled daily
promotion from DEV to PROD.

For orchestration, follow the [monthly Job setup](docs/databricks_jobs_manual_setup.md),
[PROD loading guide](docs/databricks_prod_promotion.md), and
[daily DEV-to-PROD guide](docs/databricks_daily_dev_to_prod.md).

## Dashboard

Visit **[https://finops.allops.cloud](https://finops.allops.cloud)**.

| Page | Scope |
| --- | --- |
| Executive Overview | Monthly and annual cost indicators, with year-to-year comparisons. |
| Savings | List, contracted, and effective costs; pricing benefits and effective-cost components. |
| Allocation & Accountability | Cost allocation by service, cost center, subscription, and application owner. |
| Cost Drivers | Service, charge-category, and SKU analysis. |
| Resources | Resource-level and resource-group analysis. |
| Consumption & Emission | Synthetic Azure usage and explicitly illustrative carbon scenarios. |
| Knowledge Base | Cost formulas, FOCUS column definitions, and terminology. |
| Operations & Quality | Data coverage and, where authorized, pipeline audit and reconciliation. |
| Architecture | Processing layers and data lineage. |
| About the Project | Project presentation, stack and approved Platform Costs aggregates. |
| About Me | Engineering profile and contact. |

The dashboard uses European number formatting and responsive navigation.
Its **Realized Savings** indicator is `List Cost - Effective Cost`, a pricing
comparison rather than evidence of cash savings achieved by an optimization.

The Consumption code and [manual rollout](apps/finops_dashboard/README.md#consumption-rollout-no-ingestion-reload)
are available; validate the serving views and deployment before treating this
feature as operational. Azure quantities are grouped by compatible SKU and unit,
not summed across different units. The Consumption page does not query real
Databricks billing. Carbon emissions are not measured by this project.
Approved GCP cost/Databricks list-cost aggregates belong to **About the Project →
Platform Costs**; the [manual installation guide](docs/platform_costs_setup.md)
prepares a separate scheduled monitoring workflow and private GCS serving object.
These scripts do not deploy resources or enable schedules automatically.

## Data quality and access control

The [versioned FOCUS Data Contract](contracts/focus_cost_usage/v1.0.0/focus_cost_usage_contract.yaml)
checks data before the Silver load. Source lineage, run history, snapshots, and
reconciliation support troubleshooting and post-load controls.

The dashboard's [security module](apps/finops_dashboard/security/README.md)
defines application-owner, domain-manager, subdomain-manager, and FinOps
administrator scopes. Active entitlements are checked and SQL predicates are
applied before aggregation. These are application-level controls, not Unity
Catalog row-filter policies.

Public portfolio profiles demonstrate scope behavior on approved synthetic
data; selecting a profile is **not user authentication**. The separate private
mode verifies IAP identity and requires its own deployment and access tests.
Public profiles cannot expose raw OPS audit records or real DBU telemetry.

Keep backend credentials separate from viewer identity. No token,
service-account key, or Databricks secret belongs in Git.

## Deployment options

| Scenario | Repository configuration |
| --- | --- |
| Databricks Serverless | [`platform/serverless`](platform/serverless): Default Storage setup and Serverless Jobs. |
| Databricks Classic compute | [`platform/classic_compute`](platform/classic_compute): explicit managed GCS locations and Classic Job configuration. |
| Shared processing | [`platform/common`](platform/common): reusable notebooks, transformations, and controls. |
| Public dashboard | Streamlit container deployed on Cloud Run, with the `finops.allops.cloud` domain. |
| Databricks Apps alternative | [Manual App deployment](docs/databricks_streamlit_app.md). |

The two compute scenarios share transformation code. Their catalog setup and
Job compute bindings differ. Use the selected scenario's setup files, not both.

The documented Cloud Build trigger watches `main`, builds the dashboard image,
and deploys Cloud Run. A push can therefore initiate a billable build/deployment,
including a documentation-only push. See the
[deployment and verification instructions](apps/finops_dashboard/README.md#cloud-run-deployment-current-dashboard).

## Getting started

Cloud execution requires a Databricks workspace with Unity Catalog, configured
GCS access, the selected compute, and a SQL Warehouse for dashboard queries.
Local package development requires Python **3.11 or 3.12**.

1. Configure storage using the [GCS setup guide](docs/databricks_gcs_setup.md).
2. Choose the Serverless or Classic setup and follow the
   [manual installation guide](docs/manual_platform_rebuild.md). Catalog deletion
   is only for an explicitly approved reset, not a routine installation step.
3. Create empty business tables with
   [`initialize_empty_data_tables.ipynb`](platform/common/notebooks/operations/initialize_empty_data_tables.ipynb)
   for the target environment, then load the selected billing range.
4. Execute post-load controls, configure the Jobs, and validate PROD before
   connecting the dashboard.
5. Follow the [dashboard manual](apps/finops_dashboard/README.md) for serving
   configuration, security modes, deployment, and smoke tests.

## Repository layout

```text
platform/serverless/           Default Storage SQL and Serverless Job definitions
platform/classic_compute/      Managed GCS SQL and Classic Job definitions
platform/common/notebooks/     Shared pipeline and operational notebooks
platform/common/sql/           Gold, datamarts, controls, security, Azure consumption
platform/common/sql/monitoring/ Private Databricks telemetry and Platform Costs
config/                       Environment and shared RAW/OPS configuration
contracts/                    Versioned FOCUS Data Contract
src/finops_cloud/audit/        Runs, snapshots, reconciliation
src/finops_cloud/medallion/    Bronze, Silver, Gold, contract, Delta operations
src/finops_cloud/storage/      Discovery and optional archival
src/finops_cloud/sql/          SQL loading and rendering
src/finops_cloud/pipelines/    Processing orchestration
src/finops_cloud/monitoring/   Independent platform-cost collection and publication
apps/finops_dashboard/         Streamlit application and deployment configuration
tests/                        Unit tests and integration-test guidance
docs/                         Architecture and operational manuals
```

## Validation and maintenance

After installing the project and dashboard dependencies in a local virtual
environment, run the unit tests:

```bash
PYTHONPATH=src python3 -m unittest discover -s tests/unit -v
```

Local tests do not replace Databricks execution checks. See the
[integration-test guidance](tests/integration/README.md) and
[post-load controls](platform/common/sql/controls).

For historical privacy cleanup, follow the [guarded rebuild guide](docs/privacy_rebuild.md).
After a validated DEV rebuild, the guarded
[`promote_clean_dev_to_prod.ipynb`](platform/common/notebooks/operations/promote_clean_dev_to_prod.ipynb)
provides an independent DEEP CLONE alternative to a second full replay. It
preserves OPS history and validates the PROD copies. Do not run both recovery
procedures in PROD; neither is a routine daily-load step.

Remaining migration acceptance checks are recorded in the
[Belgium completion plan](docs/databricks_belgium_completion_plan.md).
