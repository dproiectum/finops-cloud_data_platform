-- Additive metadata setup, shared by Classic and Serverless compute.
-- Matches the DDL already executed manually in workspace-belgium.
-- Existing tables are not replaced or migrated by this script.
-- These tables do not enforce dashboard access by themselves.

CREATE SCHEMA IF NOT EXISTS finops_ops.security
COMMENT 'Dashboard identity entitlements and business scope mappings';

CREATE TABLE IF NOT EXISTS finops_ops.security.user_entitlement (
    identity_provider STRING NOT NULL,
    principal_id      STRING NOT NULL,
    principal_email   STRING,
    environment       STRING NOT NULL,
    role              STRING NOT NULL,
    scope_type        STRING NOT NULL,
    scope_id          STRING NOT NULL,
    valid_from        TIMESTAMP,
    valid_to          TIMESTAMP,
    is_active         BOOLEAN NOT NULL,
    updated_at        TIMESTAMP
)
USING DELTA
COMMENT 'Explicit dashboard permissions; enforcement requires application code';

CREATE TABLE IF NOT EXISTS finops_ops.security.business_scope (
    environment       STRING NOT NULL,
    application_code  STRING NOT NULL,
    application_name  STRING,
    domain_id         STRING,
    subdomain_id      STRING,
    is_active         BOOLEAN NOT NULL,
    updated_at        TIMESTAMP
)
USING DELTA
COMMENT 'Application membership in business domains and subdomains';
