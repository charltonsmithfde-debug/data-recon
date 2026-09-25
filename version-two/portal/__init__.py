"""
version-two/portal package — Thin Web Portal Decoupled API Gateway (Ticket V2-3.2).
"""

from .auth import (
    PortalAuthError,
    VerifiedIdentity,
    decode_and_verify_cube_jwt,
    extract_iap_email,
    load_role_assignments,
    mint_cube_jwt,
    resolve_verified_identity,
)
from .server import (
    PortalGatewayApp,
    PortalTestClient,
    create_portal_app,
    handle_member_analysis_query,
    proxy_cube_load,
)

__all__ = [
    "PortalAuthError",
    "VerifiedIdentity",
    "decode_and_verify_cube_jwt",
    "extract_iap_email",
    "load_role_assignments",
    "mint_cube_jwt",
    "resolve_verified_identity",
    "PortalGatewayApp",
    "PortalTestClient",
    "create_portal_app",
    "handle_member_analysis_query",
    "proxy_cube_load",
]
