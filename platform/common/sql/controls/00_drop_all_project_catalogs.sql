-- COMMON CONTROL 00 - DESTRUCTIVE: remove every FinOps Unity Catalog object.
-- Execute each DROP manually in this exact order only after stopping all jobs.
-- The external Parquets under gs://dtl_finops/focus are NOT deleted when the
-- finops_raw external Volume is dropped. Managed DEV/PROD/OPS objects are deleted.
-- Never add main, system, samples, or another non-project catalog to this file.

DROP CATALOG IF EXISTS `finops_dev` CASCADE;
DROP CATALOG IF EXISTS `finops_prod` CASCADE;
DROP CATALOG IF EXISTS `finops_ops` CASCADE;
DROP CATALOG IF EXISTS `finops_raw` CASCADE;
