"""Explicit public/local-demo/portfolio-demo/IAP modes; no auth fallback."""

from __future__ import annotations

from dataclasses import dataclass
import os
import time
from typing import Callable, Mapping


class SecurityError(ValueError):
    """Safe, non-sensitive message which may be displayed to a viewer."""


@dataclass(frozen=True)
class Identity:
    provider: str
    subject: str


DEMO_PERSONAS = (
    "demo-app-owner-a", "demo-app-owner-b", "demo-finops-admin", "demo-no-access",
)

# This public sandbox cannot acquire a different role or application merely by
# changing the live demo assignments. Those assignments are still checked.
PORTFOLIO_PROFILES = {
    "demo-finops-admin": ("FINOPS_ADMIN", "ALL", "*"),
    "demo-app-owner-a": ("APPLICATION_OWNER", "APPLICATION", "APP00013057"),
    "demo-app-owner-b": ("APPLICATION_OWNER", "APPLICATION", "BSN0003965"),
}
PORTFOLIO_PERSONAS = (*PORTFOLIO_PROFILES, "demo-no-access")
PORTFOLIO_LABELS = {
    "demo-finops-admin": "FinOps Admin · all synthetic PROD data",
    "demo-app-owner-a": "Owner A · Data Platform",
    "demo-app-owner-b": "Owner B · ServiceNow",
    "demo-no-access": "No Access · access refused",
}


def auth_mode(environ: Mapping[str, str] | None = None) -> str:
    values = os.environ if environ is None else environ
    mode = values.get("FINOPS_AUTH_MODE", "public").strip().lower()
    if mode not in {"public", "demo", "portfolio_demo", "iap"}:
        raise SecurityError("Invalid authentication mode. Access refused.")
    if mode == "public" and values.get("K_SERVICE") not in {None, "", "finops-center"}:
        raise SecurityError("Public mode is allowed only for the existing synthetic portfolio service.")
    if mode == "demo" and values.get("K_SERVICE"):
        raise SecurityError("Demo personas are local-only; they cannot run on Cloud Run.")
    if mode == "portfolio_demo":
        if values.get("K_SERVICE") not in {None, "", "finops-center"}:
            raise SecurityError("Portfolio demonstration is allowed only on the synthetic portfolio service.")
        if values.get("FINOPS_PORTFOLIO_DATA_APPROVED", "").strip().lower() != "true":
            raise SecurityError("Portfolio data publication has not been approved. Access refused.")
    if mode == "iap" and not values.get("FINOPS_IAP_AUDIENCE", "").strip():
        raise SecurityError("IAP audience is not configured. Access refused.")
    return mode


def demo_identity(subject: str) -> Identity:
    if subject not in DEMO_PERSONAS:
        raise SecurityError("Unknown demonstration identity. Access refused.")
    return Identity("demo", subject)


def _decode_iap(assertion: str, audience: str) -> Mapping:
    # Imported only for authenticated mode; public/local tests need no Google SDK.
    from google.auth.transport.requests import Request
    from google.oauth2 import id_token

    return id_token.verify_token(
        assertion,
        Request(),
        audience=audience,
        certs_url="https://www.gstatic.com/iap/verify/public_key",
    )


def iap_identity(
    headers: Mapping[str, str], audience: str, *,
    decoder: Callable = _decode_iap, now: float | None = None,
) -> Identity:
    """Verify signed assertion; never trust unsigned email/id headers.

    `decoder` is an injection seam for tests, not a request-controlled option.
    In the app the default verifies Google's signature, time and audience.
    """
    assertion = {key.lower(): value for key, value in headers.items()}.get(
        "x-goog-iap-jwt-assertion", ""
    )
    if not assertion or not audience:
        raise SecurityError("Authenticated identity is missing. Access refused.")
    try:
        claims = decoder(assertion, audience)
        timestamp = time.time() if now is None else now
        if (
            claims.get("iss") != "https://cloud.google.com/iap"
            or claims.get("aud") != audience
            or not isinstance(claims.get("exp"), (int, float))
            or not isinstance(claims.get("iat"), (int, float))
            or claims["exp"] <= timestamp
            or claims["iat"] > timestamp + 30
            or not isinstance(claims.get("sub"), str)
            or not claims["sub"].strip()
        ):
            raise ValueError("Invalid signed identity")
        return Identity("iap", claims["sub"])
    except Exception:
        # Never put headers, assertion contents or verification exceptions in UI.
        raise SecurityError("Identity verification failed. Reload or request access.") from None
