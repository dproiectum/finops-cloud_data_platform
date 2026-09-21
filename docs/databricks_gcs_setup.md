# Databricks and GCS setup

This setup is manual and requires Unity Catalog administration privileges.

1. Confirm that the `dtl_finops` bucket and the `finops_gcs_storage_dev`
   Storage Credential exist.
2. Grant the Storage Credential access to `gs://dtl_finops`.
3. Open a Databricks SQL Warehouse.
4. Follow the ordered procedure in `manual_platform_rebuild.md`.
5. Grant the pipeline identity `USE CATALOG`, `USE SCHEMA`, `READ VOLUME`, and
   the table creation/write permissions required in the selected environment.

The registered source path is
`/Volumes/finops_raw/landing/focus`. The monthly files are expected at
`monthly/billing-YYYY-MM.parquet` below that Volume.

Storage Credentials govern External Locations and Volumes. Service Credentials
are only needed by the optional Python GCS archival module. No JSON key is
stored in this repository.
