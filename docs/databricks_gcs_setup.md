# Databricks and GCS setup

This setup is manual and requires Unity Catalog administration privileges.

1. Confirm that the `dtl_finops` bucket and the `finops_gcs_storage_dev`
   Storage Credential exist.
2. Grant the Storage Credential access to `gs://dtl_finops`.
3. For a classic workspace, create the regional managed-data bucket
   `gs://dtl_finops-unitycatalog-euw1`, a dedicated Storage Credential, and an
   External Location that covers this bucket. Grant `CREATE MANAGED STORAGE`
   on that External Location to the platform administrator.
4. Choose exactly one catalog-creation scenario:
   `platform/serverless` for Default Storage, or
   `platform/classic_compute` for the Belgian Classic workspace.
5. Run its creation scripts and the shared controls under `platform/common` in
   the order explained in `manual_platform_rebuild.md`. Do not mix creation
   scripts between scenarios.
6. Grant the pipeline identity `USE CATALOG`, `USE SCHEMA`, `READ VOLUME`, and
   the table creation/write permissions required in the selected environment.

The registered source path is
`/Volumes/finops_raw/landing/focus`. The monthly files are expected at
`monthly/billing-YYYY-MM.parquet` below that Volume.

Storage Credentials govern External Locations and Volumes. Service Credentials
are only needed by the optional Python GCS archival module. No JSON key is
stored in this repository.
