-- ENVIRONNEMENT : DEV GCP
-- Prerequis : le Storage Credential `finops_gcs_storage_dev` existe et son
-- compte de service possede les droits IAM sur gs://dtl_finops.

CREATE EXTERNAL LOCATION IF NOT EXISTS `finops_gcs`
URL 'gs://dtl_finops'
WITH (STORAGE CREDENTIAL `finops_gcs_storage_dev`)
COMMENT 'Emplacement GCS DEV de la plateforme FinOps';

CREATE CATALOG IF NOT EXISTS `finops_dev`
COMMENT 'Catalogue DEV de la plateforme FinOps';

CREATE SCHEMA IF NOT EXISTS `finops_dev`.`raw`
COMMENT 'Volumes externes contenant les fichiers FOCUS source';

CREATE SCHEMA IF NOT EXISTS `finops_dev`.`bronze`
COMMENT 'Raw FOCUS data ingested in Delta format';

CREATE SCHEMA IF NOT EXISTS `finops_dev`.`silver`
COMMENT 'Data conforming to the Data Contract and the central table';

CREATE SCHEMA IF NOT EXISTS `finops_dev`.`gold`
COMMENT 'Modele dimensionnel FinOps';

CREATE SCHEMA IF NOT EXISTS `finops_dev`.`datamart`
COMMENT 'Tables et vues destinees aux usages BI';

CREATE SCHEMA IF NOT EXISTS `finops_dev`.`ops`
COMMENT 'Audit, controle, reconciliation et suivi des pipelines';

CREATE EXTERNAL VOLUME IF NOT EXISTS `finops_dev`.`raw`.`focus`
LOCATION 'gs://dtl_finops/focus'
COMMENT 'Fichiers FOCUS actifs : daily et monthly';

CREATE EXTERNAL VOLUME IF NOT EXISTS `finops_dev`.`raw`.`focus_archive`
LOCATION 'gs://dtl_finops/focus_archive'
COMMENT 'Archives des fichiers FOCUS deja traites';
