-- Read-only checks after reset and schema recreation.

SHOW TABLES IN `finops_dev`.`bronze`;
SHOW TABLES IN `finops_dev`.`silver`;
SHOW TABLES IN `finops_dev`.`gold`;
SHOW TABLES IN `finops_dev`.`datamart`;

SELECT 'pipeline_run' AS table_name, count(*) AS dev_rows
FROM `finops_ops`.`audit`.`pipeline_run` WHERE environment = 'dev'
UNION ALL
SELECT 'month_snapshot', count(*)
FROM `finops_ops`.`audit`.`month_snapshot` WHERE environment = 'dev'
UNION ALL
SELECT 'monthly_reconciliation', count(*)
FROM `finops_ops`.`audit`.`monthly_reconciliation` WHERE environment = 'dev'
UNION ALL
SELECT 'month_status', count(*)
FROM `finops_ops`.`audit`.`month_status` WHERE environment = 'dev'
UNION ALL
SELECT 'file_archive', count(*)
FROM `finops_ops`.`audit`.`file_archive` WHERE environment = 'dev';

LIST '/Volumes/finops_raw/landing/focus/monthly';

