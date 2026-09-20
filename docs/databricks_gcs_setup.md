# Databricks and GCS setup checklist

This procedure requires Unity Catalog and GCP administration privileges. It is
not executed automatically by the data pipelines.

1. Create or select the `dtl_finops` bucket in the same region as Databricks.
2. Keep hierarchical namespace disabled for the bucket.
3. Create a Unity Catalog **Storage Credential** for GCS.
4. Grant its generated service account the required bucket read/write roles.
5. Create one External Location covering `gs://dtl_finops`.
6. In DEV, execute `sql/infrastructure/01_dev_unity_catalog_storage.sql` after
   creating the `finops_gcs_storage_dev` Storage Credential. Keep
   `00_unity_catalog_storage_template.sql` as the reusable environment template.
7. Grant the pipeline identity read/write access to both External Volumes.
8. Create the **Service Credentials** `finops-gcs-dev` and
   `finops-gcs-prod` for direct Google SDK access during verified archival.
9. Grant the job identity `ACCESS` on the corresponding Service Credential.
10. Replace `CHANGE_ME_GCP_PROJECT` in `config/dev.toml` and `config/prod.toml`.
11. Test the External Location and both Volumes in Catalog Explorer.

Storage Credentials govern external storage locations and Volumes. Service
Credentials are separate Unity Catalog objects used by the Python GCS client.
No service-account JSON key is stored in this repository.

The first integration run must use `finops_dev`, a small copied month and a
dedicated GCS prefix. Production deployment is allowed only after Daily,
Monthly, audit, replacement, rollback and archive-retry tests pass in DEV.
