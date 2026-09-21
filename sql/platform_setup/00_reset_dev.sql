-- STEP 00 - DESTRUCTIVE: remove the complete DEV catalog before a clean reload.
-- This script has no dependency on finops_ops. It never deletes GCS files and
-- never modifies finops_raw or finops_prod.

DROP CATALOG IF EXISTS `finops_dev` CASCADE;
