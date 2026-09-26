# Belgian classic-compute platform setup

Use this complete sequence for the classic workspace in europe-west1.

Prerequisites:

1. Create the regional bucket gs://dtl_finops-unitycatalog-euw1 in europe-west1.
2. Create the Databricks Storage Credential finops_uc_storage_be.
3. Grant its generated GCP service account read/write/delete object access on the bucket.
4. Stop all FinOps jobs before running the destructive reset.

Run 00 first and inspect its output. Then run 01 only when a full reset is
intended. Continue with 02 through 06 to recreate and validate the empty
platform. Run 07 after loading DEV, 08 before promoting PROD, and 09 after
loading PROD.

The source bucket gs://dtl_finops remains external and contains only focus and
focus_archive. Managed Delta data is written below the catalog-specific roots
in gs://dtl_finops-unitycatalog-euw1/catalogs.

This folder is self-contained. Do not use creation scripts from
`platform_setup_serverless` in the same workspace.
