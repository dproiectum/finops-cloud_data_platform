-- Read-only METADATA checks, not proof of dashboard authorization.
-- Run statements in order; stop on any error.

SELECT assert_true(
    COUNT(DISTINCT application_code) = 2,
    'SECURITY CONTROL FAILED: selected applications are missing from current PROD resources'
)
FROM finops_prod.gold.dim_resource
WHERE is_current = TRUE
  AND application_code IN ('APP00013057', 'BSN0003965');

SELECT assert_true(
    COUNT(*) = 2 AND COUNT(DISTINCT application_code) = 2
        AND SUM(CASE WHEN is_active = TRUE THEN 1 ELSE 0 END) = 2,
    'SECURITY CONTROL FAILED: expected exactly two active selected PROD scopes'
)
FROM finops_ops.security.business_scope
WHERE environment = 'prod'
  AND application_code IN ('APP00013057', 'BSN0003965');

WITH expected AS (
    SELECT * FROM VALUES
        ('demo-finops-admin', 'FINOPS_ADMIN', 'ALL', '*'),
        ('demo-app-owner-a', 'APPLICATION_OWNER', 'APPLICATION', 'APP00013057'),
        ('demo-app-owner-b', 'APPLICATION_OWNER', 'APPLICATION', 'BSN0003965')
    AS assignments(principal_id, role, scope_type, scope_id)
), actual AS (
    SELECT *
    FROM finops_ops.security.user_entitlement
    WHERE identity_provider = 'demo'
      AND environment = 'prod'
      AND principal_id IN ('demo-finops-admin', 'demo-app-owner-a', 'demo-app-owner-b')
), coverage AS (
    SELECT expected.principal_id, COUNT(actual.principal_id) AS matches,
           SUM(CASE WHEN actual.is_active = TRUE
                     AND (actual.valid_from IS NULL OR actual.valid_from <= CURRENT_TIMESTAMP())
                     AND (actual.valid_to IS NULL OR actual.valid_to > CURRENT_TIMESTAMP())
                    THEN 1 ELSE 0 END) AS valid_matches
    FROM expected
    LEFT JOIN actual
      ON actual.principal_id = expected.principal_id
     AND actual.role = expected.role
     AND actual.scope_type = expected.scope_type
     AND actual.scope_id = expected.scope_id
    GROUP BY expected.principal_id
)
SELECT assert_true(
    COUNT(*) = 3 AND SUM(CASE WHEN matches = 1 AND valid_matches = 1 THEN 1 ELSE 0 END) = 3,
    'SECURITY CONTROL FAILED: demo permissions are missing, duplicated, inactive or expired'
)
FROM coverage;

-- Include ALL environments to detect unexpected cross-environment test grants.
-- Unrelated real identities or demo personas are not counted.
SELECT assert_true(
    COUNT(*) = 3,
    'SECURITY CONTROL FAILED: unexpected permissions for the three demo identities'
)
FROM finops_ops.security.user_entitlement
WHERE identity_provider = 'demo'
  AND principal_id IN ('demo-finops-admin', 'demo-app-owner-a', 'demo-app-owner-b');

SELECT assert_true(
    COUNT(*) = 0,
    'SECURITY CONTROL FAILED: demo-no-access must have no entitlement'
)
FROM finops_ops.security.user_entitlement
WHERE identity_provider = 'demo'
  AND principal_id = 'demo-no-access';

SELECT environment, application_code, application_name,
       domain_id, subdomain_id, is_active
FROM finops_ops.security.business_scope
WHERE environment = 'prod'
  AND application_code IN ('APP00013057', 'BSN0003965')
ORDER BY application_code;

SELECT identity_provider, principal_id, environment,
       role, scope_type, scope_id, is_active, valid_from, valid_to
FROM finops_ops.security.user_entitlement
WHERE identity_provider = 'demo'
  AND principal_id IN ('demo-finops-admin', 'demo-app-owner-a', 'demo-app-owner-b')
ORDER BY principal_id;

SELECT 'PASS: demo metadata valid; validate dashboard enforcement separately' AS result;
