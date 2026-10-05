-- STEP 6 ONLY: insert synthetic test identities and two application scopes.
-- Target: workspace-belgium, existing synthetic PROD business data.
-- No authenticated user is granted access by this script. identity_provider=demo
-- must never be accepted as an IAP identity by the future private dashboard.
-- Run statements in order and STOP on any error. Do not run concurrently.
-- MERGE inserts missing keys only; it never restores revoked permissions,
-- changes existing assignments, or guesses domains from application names.

SELECT assert_true(
    COUNT(DISTINCT application_code) = 2,
    'SECURITY SETUP FAILED: both selected applications must exist in current PROD resources'
)
FROM finops_prod.gold.dim_resource
WHERE is_current = TRUE
  AND application_code IN ('APP00013057', 'BSN0003965');

SELECT assert_true(
    COUNT(*) = 0,
    'SECURITY SETUP FAILED: duplicate selected business scopes; inspect before seeding'
)
FROM (
    SELECT environment, application_code
    FROM finops_ops.security.business_scope
    WHERE environment = 'prod'
      AND application_code IN ('APP00013057', 'BSN0003965')
    GROUP BY environment, application_code
    HAVING COUNT(*) > 1
) AS duplicates;

SELECT assert_true(
    COUNT(*) = 0,
    'SECURITY SETUP FAILED: duplicate demo entitlement keys; inspect before seeding'
)
FROM (
    SELECT identity_provider, principal_id, environment, role, scope_type, scope_id
    FROM finops_ops.security.user_entitlement
    WHERE identity_provider = 'demo'
      AND principal_id IN ('demo-finops-admin', 'demo-app-owner-a', 'demo-app-owner-b')
    GROUP BY identity_provider, principal_id, environment, role, scope_type, scope_id
    HAVING COUNT(*) > 1
) AS duplicates;

MERGE INTO finops_ops.security.business_scope AS target
USING (
    SELECT
        'prod' AS environment,
        application_code,
        MAX(application_name) AS application_name
    FROM finops_prod.gold.dim_resource
    WHERE is_current = TRUE
      AND application_code IN ('APP00013057', 'BSN0003965')
    GROUP BY application_code
) AS source
ON target.environment = source.environment
   AND target.application_code = source.application_code
WHEN NOT MATCHED THEN INSERT (
    environment, application_code, application_name, domain_id,
    subdomain_id, is_active, updated_at
)
VALUES (
    source.environment, source.application_code, source.application_name,
    NULL, NULL, TRUE, CURRENT_TIMESTAMP()
);

MERGE INTO finops_ops.security.user_entitlement AS target
USING (
    SELECT
        'demo' AS identity_provider,
        principal_id,
        principal_email,
        'prod' AS environment,
        role,
        scope_type,
        scope_id
    FROM VALUES
        ('demo-finops-admin', 'admin@example.invalid',
         'FINOPS_ADMIN', 'ALL', '*'),
        ('demo-app-owner-a', 'owner-a@example.invalid',
         'APPLICATION_OWNER', 'APPLICATION', 'APP00013057'),
        ('demo-app-owner-b', 'owner-b@example.invalid',
         'APPLICATION_OWNER', 'APPLICATION', 'BSN0003965')
    AS demo_assignments(principal_id, principal_email, role, scope_type, scope_id)
) AS source
ON target.identity_provider = source.identity_provider
   AND target.principal_id = source.principal_id
   AND target.environment = source.environment
   AND target.role = source.role
   AND target.scope_type = source.scope_type
   AND target.scope_id = source.scope_id
WHEN NOT MATCHED THEN INSERT (
    identity_provider, principal_id, principal_email, environment,
    role, scope_type, scope_id, valid_from, valid_to, is_active, updated_at
)
VALUES (
    source.identity_provider, source.principal_id, source.principal_email,
    source.environment, source.role, source.scope_type, source.scope_id,
    CURRENT_TIMESTAMP(), NULL, TRUE, CURRENT_TIMESTAMP()
);

-- No row is inserted for demo-no-access: default-deny test identity.
