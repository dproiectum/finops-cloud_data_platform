-- STEP 04 - Recreate PROD structures only. Do not load PROD during the DEV rebuild.

CREATE CATALOG IF NOT EXISTS `finops_prod`
MANAGED LOCATION 'gs://dtl_finops-unitycatalog-euw1/catalogs/finops_prod'
COMMENT 'PROD business data for the FinOps platform';

CREATE SCHEMA IF NOT EXISTS `finops_prod`.`bronze`
COMMENT 'Source data ingested into Delta with technical metadata';

CREATE SCHEMA IF NOT EXISTS `finops_prod`.`silver`
COMMENT 'FOCUS data conforming to the Data Contract';

CREATE SCHEMA IF NOT EXISTS `finops_prod`.`gold`
COMMENT 'FinOps dimensional model';

CREATE SCHEMA IF NOT EXISTS `finops_prod`.`datamart`
COMMENT 'Certified analytical tables';

