-- STEP 04 - Start DEV with no previous operational history.
-- Run only after 03_create_ops.sql. PROD rows remain untouched.

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
