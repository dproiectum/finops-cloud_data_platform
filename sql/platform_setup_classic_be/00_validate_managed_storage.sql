-- STEP 00 - Register and inspect the dedicated Belgian managed-data location.
-- Prerequisite: create the GCS bucket in europe-west1, create the Storage
-- Credential finops_uc_storage_be, and grant its generated service account
-- read/write/delete object access on the bucket.

CREATE EXTERNAL LOCATION IF NOT EXISTS `finops_uc_managed_be`
URL 'gs://dtl_finops-unitycatalog-euw1'
WITH (STORAGE CREDENTIAL `finops_uc_storage_be`)
COMMENT 'Managed Unity Catalog storage for the Belgian classic workspace';

DESCRIBE STORAGE CREDENTIAL `finops_uc_storage_be`;
DESCRIBE EXTERNAL LOCATION `finops_uc_managed_be`;
SHOW GRANTS ON EXTERNAL LOCATION `finops_uc_managed_be`;
LIST 'gs://dtl_finops-unitycatalog-euw1';

