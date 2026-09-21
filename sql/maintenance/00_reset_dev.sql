-- DESTRUCTIVE FOR DEV DELTA TABLES. Run manually only when restarting DEV.
-- This script never deletes GCS files and never modifies finops_prod.

DROP SCHEMA IF EXISTS `finops_dev`.`datamart` CASCADE;
DROP SCHEMA IF EXISTS `finops_dev`.`gold` CASCADE;
DROP SCHEMA IF EXISTS `finops_dev`.`silver` CASCADE;
DROP SCHEMA IF EXISTS `finops_dev`.`bronze` CASCADE;
DROP SCHEMA IF EXISTS `finops_dev`.`ops` CASCADE;

DELETE FROM `finops_ops`.`audit`.`file_archive`
WHERE environment = 'dev';

DELETE FROM `finops_ops`.`audit`.`monthly_reconciliation`
WHERE environment = 'dev';

DELETE FROM `finops_ops`.`audit`.`month_snapshot`
WHERE environment = 'dev';

DELETE FROM `finops_ops`.`audit`.`month_status`
WHERE environment = 'dev';

DELETE FROM `finops_ops`.`audit`.`pipeline_run`
WHERE environment = 'dev';

