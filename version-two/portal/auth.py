"""
version-two/portal/auth.py
Ticket: V2-3.2 — Thin Web Portal Decoupled API Gateway (ADR-0003 & ADR-0004)

Responsibilities:
1. Extracts verified corporate user identity from the Google Cloud IAP header
   `X-Goog-Authenticated-User-Email` (e.g. `accounts.google.com:user@domain.com`),
   rejecting unauthenticated or malformed headers with HTTP 401.
2. Resolves server-side RBAC role and POPIA PII permissions from `role_assignments.json`
   (falling back to least-privileged `ROLE_FINANCE_MEMBER` with `can_view_pii: False`),
   ignoring any client-supplied role parameters.
3. Mints RFC 7518 compliant HS256 JWT tokens (`mint_cube_jwt`) signed with
   `CUBEJS_API_SECRET` (>= 32 bytes) for downstream Cube.js 1.7.x REST API calls.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ROSTER_PATH = PROJECT_ROOT / "thin-web-app" / "role_assignments.json"
DEFAULT_API_SECRET = "local-dev-hs256-secret-key-minimum-32-bytes!!"
MIN_SECRET_BYTES = 32
LEAST_PRIVILEGED_ROLE = "ROLE_FINANCE_MEMBER"

# Authoritative role capability matrix aligned with version-two/cube/security.js
ROLE_CAPABILITIES: dict[str, dict[str, Any]] = {
    "ROLE_EXECUTIVE_ALL": {"can_view_pii": True},
    "ROLE_INVESTMENT_ANALYST": {"can_view_pii": False},
    "ROLE_ANNUITY_ANALYST": {"can_view_pii": False},
    "ROLE_MEMBER_OPERATIONS": {"can_view_pii": True},
    "ROLE_AUDIT_COMPLIANCE": {"can_view_pii": False},
    "ROLE_FINANCE_MEMBER": {"can_view_pii": False},
    "ROLE_INVESTMENTS": {"can_view_pii": False},
    "ROLE_ANNUITY": {"can_view_pii": False},
    "ROLE_DIGITAL_OPERATIONS": {"can_view_pii": False},
}


class PortalAuthError(Exception):
    """Raised when IAP authentication or JWT secret validation fails."""

    def __init__(self, message: str, status_code: int = 401) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


@dataclass(frozen=True)
class VerifiedIdentity:
    """Immutable server-verified caller identity resolved from IAP + roster."""

    email: str
    role: str
    can_view_pii: bool
    groups: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "email": self.email,
            "role": self.role,
            "can_view_pii": self.can_view_pii,
            "canViewPii": self.can_view_pii,
            "groups": list(self.groups),
        }


def _b64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64url_decode(encoded: str) -> bytes:
    padding = "=" * ((4 - (len(encoded) % 4)) % 4)
    return base64.urlsafe_b64decode((encoded + padding).encode("ascii"))


def extract_iap_email(headers: Mapping[str, str]) -> str:
    """
    Extracts and normalizes the authenticated user email from the Google Cloud IAP
    `X-Goog-Authenticated-User-Email` header.
    Rejects missing, empty, or malformed values with HTTP 401 (`PortalAuthError`).
    """
    # Perform case-insensitive header lookup
    raw_value: str | None = None
    for k, v in headers.items():
        if k.lower() == "x-goog-authenticated-user-email":
            raw_value = v
            break

    if not raw_value or not isinstance(raw_value, str) or not raw_value.strip():
        raise PortalAuthError(
            "Missing required IAP header 'X-Goog-Authenticated-User-Email'.",
            status_code=401,
        )

    cleaned = raw_value.strip()
    # Strip Google IAP identity provider prefix if present (e.g. 'accounts.google.com:user@domain.com')
    if ":" in cleaned:
        _, cleaned = cleaned.split(":", 1)
    cleaned = cleaned.strip().lower()

    if "@" not in cleaned or cleaned.startswith("@") or cleaned.endswith("@"):
        raise PortalAuthError(
            f"Malformed email in 'X-Goog-Authenticated-User-Email': '{raw_value}'.",
            status_code=401,
        )

    return cleaned


def load_role_assignments(roster_path: Path | str | None = None) -> dict[str, Any]:
    """Loads `thin-web-app/role_assignments.json` (or override path)."""
    path = Path(roster_path or os.environ.get("SCBI_ROLE_ASSIGNMENTS", DEFAULT_ROSTER_PATH))
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def resolve_verified_identity(
    headers: Mapping[str, str],
    roster_path: Path | str | None = None,
) -> VerifiedIdentity:
    """
    Verifies caller identity strictly from IAP headers and resolves RBAC role + PII
    permissions from `role_assignments.json`. Never reads client query/body parameters.
    """
    email = extract_iap_email(headers)
    roster = load_role_assignments(roster_path)
    normalized_roster = {str(k).strip().lower(): v for k, v in roster.items() if isinstance(v, dict)}
    entry = normalized_roster.get(email)

    if not entry:
        return VerifiedIdentity(
            email=email,
            role=LEAST_PRIVILEGED_ROLE,
            can_view_pii=False,
            groups=(),
        )

    candidate_role = str(entry.get("role", LEAST_PRIVILEGED_ROLE)).strip()
    role = candidate_role if candidate_role in ROLE_CAPABILITIES else LEAST_PRIVILEGED_ROLE
    role_allows_pii = bool(ROLE_CAPABILITIES[role]["can_view_pii"])
    requested_pii = bool(entry.get("can_view_pii") is True or entry.get("canViewPii") is True)
    can_view_pii = bool(role_allows_pii and requested_pii)
    raw_groups = entry.get("groups", [])
    groups = tuple(str(g) for g in raw_groups) if isinstance(raw_groups, list) else ()

    return VerifiedIdentity(
        email=email,
        role=role,
        can_view_pii=can_view_pii,
        groups=groups,
    )


def mint_cube_jwt(
    identity: VerifiedIdentity,
    secret: str | None = None,
    ttl_seconds: int = 3600,
) -> str:
    """
    Mints an RFC 7518 HS256 JWT token containing the verified caller's `role` and
    `canViewPii` permissions for downstream Cube.js 1.7.x authentication.
    """
    signing_secret = (
        secret
        if secret is not None
        else os.environ.get("CUBEJS_API_SECRET", DEFAULT_API_SECRET)
    )
    if not signing_secret or len(signing_secret.encode("utf-8")) < MIN_SECRET_BYTES:
        raise PortalAuthError(
            f"CUBEJS_API_SECRET must be at least {MIN_SECRET_BYTES} bytes for HS256.",
            status_code=500,
        )

    now = int(time.time())
    header = {"alg": "HS256", "typ": "JWT"}
    payload = {
        "sub": identity.email,
        "email": identity.email,
        "u": identity.email,
        "role": identity.role,
        "canViewPii": identity.can_view_pii,
        "can_view_pii": identity.can_view_pii,
        "groups": list(identity.groups),
        "iat": now,
        "exp": now + ttl_seconds,
    }

    header_b64 = _b64url_encode(json.dumps(header, separators=(",", ":")).encode("utf-8"))
    payload_b64 = _b64url_encode(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    signing_input = f"{header_b64}.{payload_b64}".encode("ascii")

    signature = hmac.new(
        signing_secret.encode("utf-8"),
        signing_input,
        hashlib.sha256,
    ).digest()
    signature_b64 = _b64url_encode(signature)
    return f"{header_b64}.{payload_b64}.{signature_b64}"


def decode_and_verify_cube_jwt(token: str, secret: str | None = None) -> dict[str, Any]:
    """Verifies an HS256 Cube JWT signature and returns its decoded payload."""
    signing_secret = (
        secret
        if secret is not None
        else os.environ.get("CUBEJS_API_SECRET", DEFAULT_API_SECRET)
    )
    raw_token = token.strip()
    if raw_token.lower().startswith("bearer "):
        raw_token = raw_token[7:].strip()

    parts = raw_token.split(".")
    if len(parts) != 3:
        raise PortalAuthError("Malformed JWT structure.", status_code=401)

    header_b64, payload_b64, sig_b64 = parts
    signing_input = f"{header_b64}.{payload_b64}".encode("ascii")
    expected_sig = hmac.new(
        signing_secret.encode("utf-8"),
        signing_input,
        hashlib.sha256,
    ).digest()
    provided_sig = _b64url_decode(sig_b64)
    if not hmac.compare_digest(expected_sig, provided_sig):
        raise PortalAuthError("Invalid JWT signature.", status_code=401)

    payload = json.loads(_b64url_decode(payload_b64).decode("utf-8"))
    if int(payload.get("exp", 0)) < int(time.time()):
        raise PortalAuthError("Expired JWT token.", status_code=401)
    return payload
