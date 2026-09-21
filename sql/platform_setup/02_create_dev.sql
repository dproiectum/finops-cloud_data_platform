-- STEP 02 - Recreate the empty DEV catalog and its four processing schemas.

CREATE CATALOG IF NOT EXISTS `finops_dev`
COMMENT 'DEV business data for the FinOps platform';

CREATE SCHEMA IF NOT EXISTS `finops_dev`.`bronze`
COMMENT 'Source data ingested into Delta with technical metadata';

CREATE SCHEMA IF NOT EXISTS `finops_dev`.`silver`
COMMENT 'FOCUS data conforming to the Data Contract';

CREATE SCHEMA IF NOT EXISTS `finops_dev`.`gold`
COMMENT 'FinOps dimensional model';

CREATE SCHEMA IF NOT EXISTS `finops_dev`.`datamart`
COMMENT 'Certified analytical tables';
