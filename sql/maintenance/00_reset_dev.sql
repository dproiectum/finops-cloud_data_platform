-- DESTRUCTIVE: remove the complete DEV catalog before a clean reload.
-- This script never deletes GCS files and never modifies finops_raw or finops_prod.

DROP CATALOG IF EXISTS `finops_dev` CASCADE;

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
