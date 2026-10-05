"""Viewer authorization, separate from the backend Databricks identity."""

from .identity import Identity, SecurityError, auth_mode, demo_identity, iap_identity
from .authorization import AccessContext, BoundQuery, resolve_access

__all__ = [
    "AccessContext", "BoundQuery", "Identity", "SecurityError", "auth_mode",
    "demo_identity", "iap_identity", "resolve_access",
]
