# Serverless scenario

This folder contains only Databricks artifacts whose implementation depends on
Serverless compute or Default Storage. Shared notebooks, controls, Gold SQL,
and datamart SQL live under `platform/common`.

## Manual platform creation

1. Stop every FinOps Job.
2. Run `../common/sql/controls/00_drop_all_project_catalogs.sql` only for a full reset.
3. Run `sql/01_create_raw.sql`.
4. Run `sql/02_create_dev.sql`.
5. Run `sql/03_create_prod.sql`.
6. Run `sql/04_create_ops.sql`.
7. Run `../common/notebooks/operations/initialize_empty_data_tables.ipynb`
   once with `environment=dev` and once with `environment=prod`.
8. Run `../common/sql/controls/01_validate_empty_platform.sql`.

Catalog creation intentionally omits `MANAGED LOCATION` and relies on
Databricks Default Storage. The source Parquets remain external under
`gs://dtl_finops/focus`.

`jobs/pipeline_jobs.yml` contains the Databricks Asset Bundle Serverless Jobs.
`jobs/billing_full_load_by_month.yml` is the manual three-task DEV Job template.
Its Warehouse ID belongs to the current Frankfurt workspace and must be checked
before reuse in another workspace.
