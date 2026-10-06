"""Deny-by-default entitlements and live, parameterized SQL predicates."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from config import DashboardConfig
from .identity import Identity, SecurityError


@dataclass(frozen=True)
class BoundQuery:
    text: str
    bindings: tuple[tuple[str, Any], ...]

    @property
    def parameters(self) -> dict[str, Any]:
        return dict(self.bindings)


@dataclass(frozen=True)
class AccessContext:
    identity: Identity
    environment: str
    is_admin: bool


ROLE_SCOPES = {
    "FINOPS_ADMIN": "ALL",
    "APPLICATION_OWNER": "APPLICATION",
    "DOMAIN_MANAGER": "DOMAIN",
    "SUBDOMAIN_MANAGER": "SUBDOMAIN",
}


def security_table(config: DashboardConfig, table: str) -> str:
    if table not in {"user_entitlement", "business_scope"}:
        raise SecurityError("Unsupported security object.")
    return f"`{config.operations_catalog}`.`security`.`{table}`"


def live_entitlement_predicate(alias: str = "e") -> str:
    return f"""
        {alias}.identity_provider = :viewer_provider
        AND {alias}.principal_id = :viewer_subject
        AND {alias}.environment = :viewer_environment
        AND {alias}.is_active = TRUE
        AND ({alias}.valid_from IS NULL OR {alias}.valid_from <= CURRENT_TIMESTAMP())
        AND ({alias}.valid_to IS NULL OR {alias}.valid_to > CURRENT_TIMESTAMP())
    """


def viewer_parameters(context: AccessContext) -> dict[str, str]:
    return {
        "viewer_provider": context.identity.provider,
        "viewer_subject": context.identity.subject,
        "viewer_environment": context.environment,
    }


def admin_predicate(config: DashboardConfig) -> str:
    return f"""EXISTS (
        SELECT 1 FROM {security_table(config, 'user_entitlement')} e
        WHERE {live_entitlement_predicate()}
          AND e.role = 'FINOPS_ADMIN' AND e.scope_type = 'ALL' AND e.scope_id = '*'
    )"""


def charge_predicate(config: DashboardConfig, alias: str = "c") -> str:
    # Keep the admin check independent of application scopes. The former nested
    # correlated EXISTS/LEFT JOIN/IN plan lost application_code during Databricks
    # SQL optimization. This uncorrelated application set avoids that plan while
    # IN/EXISTS still prevent multiple permissions from multiplying charges.
    return f"""
        {alias}.environment = :viewer_environment
        AND (
          {admin_predicate(config)}
          OR {alias}.application_code IN (
            SELECT b.application_code
            FROM (
              SELECT environment, application_code,
                     MAX(domain_id) AS domain_id, MAX(subdomain_id) AS subdomain_id
              FROM {security_table(config, 'business_scope')}
              WHERE environment = :viewer_environment AND is_active = TRUE
                AND application_code IS NOT NULL AND trim(application_code) <> ''
                AND lower(trim(application_code)) <> 'unknown'
              GROUP BY environment, application_code HAVING COUNT(*) = 1
            ) b
            JOIN {security_table(config, 'user_entitlement')} e
              ON e.environment = b.environment
            WHERE {live_entitlement_predicate()}
              AND (
                (e.role = 'APPLICATION_OWNER' AND e.scope_type = 'APPLICATION'
                  AND e.scope_id = b.application_code)
                OR (e.role = 'DOMAIN_MANAGER' AND e.scope_type = 'DOMAIN'
                  AND e.scope_id = b.domain_id)
                OR (e.role = 'SUBDOMAIN_MANAGER' AND e.scope_type = 'SUBDOMAIN'
                  AND e.scope_id = b.subdomain_id)
              )
          )
        )
    """


def resolve_access(source, config: DashboardConfig, identity: Identity) -> AccessContext:
    """Read permissions afresh for every rerun; no permission cache/fallback."""
    if identity.provider not in {"demo", "iap"} or not identity.subject:
        raise SecurityError("Unsupported identity. Access refused.")
    if config.data_catalog != f"finops_{config.environment}":
        raise SecurityError("Catalog and execution environment do not match. Access refused.")
    provisional = AccessContext(identity, config.environment, False)
    statement = f"""
        SELECT role, scope_type, scope_id
        FROM {security_table(config, 'user_entitlement')} e
        WHERE {live_entitlement_predicate()}
    """
    rows = source.query(statement, viewer_parameters(provisional)).to_dict("records")
    if not rows:
        raise SecurityError("No active permission for this identity and environment.")
    seen = set()
    is_admin = False
    for row in rows:
        role, scope_type, scope_id = row["role"], row["scope_type"], row["scope_id"]
        if (
            role not in ROLE_SCOPES or ROLE_SCOPES[role] != scope_type
            or not isinstance(scope_id, str) or not scope_id.strip()
            or scope_id != scope_id.strip() or scope_id.lower() == "unknown"
            or (role == "FINOPS_ADMIN" and scope_id != "*")
            or (role != "FINOPS_ADMIN" and scope_id == "*")
        ):
            raise SecurityError("Invalid permission configuration. Access refused.")
        key = (role, scope_type, scope_id)
        if key in seen:
            raise SecurityError("Duplicate permission configuration. Access refused.")
        seen.add(key)
        is_admin = is_admin or role == "FINOPS_ADMIN"
    context = AccessContext(identity, config.environment, is_admin)
    if not is_admin:
        mappings = source.query(f"""
            SELECT b.application_code
            FROM {security_table(config, 'business_scope')} b
            WHERE b.environment = :viewer_environment AND b.is_active = TRUE
              AND b.application_code IS NOT NULL AND trim(b.application_code) <> ''
              AND lower(trim(b.application_code)) <> 'unknown'
              AND EXISTS (
                SELECT 1 FROM {security_table(config, 'user_entitlement')} e
                WHERE {live_entitlement_predicate()}
                  AND (
                    (e.role = 'APPLICATION_OWNER' AND e.scope_type = 'APPLICATION'
                      AND e.scope_id = b.application_code)
                    OR (e.role = 'DOMAIN_MANAGER' AND e.scope_type = 'DOMAIN'
                      AND e.scope_id = b.domain_id)
                    OR (e.role = 'SUBDOMAIN_MANAGER' AND e.scope_type = 'SUBDOMAIN'
                      AND e.scope_id = b.subdomain_id)
                  )
              )
        """, viewer_parameters(context))["application_code"].tolist()
        if not mappings or len(mappings) != len(set(mappings)):
            raise SecurityError("Business scope is missing or ambiguous. Access refused.")
    return context
