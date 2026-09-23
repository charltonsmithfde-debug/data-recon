"""US-1.1 -- Authenticate before serving anything.

Acceptance criteria (PRD_ARCHITECTURE_REALIGNMENT.md:239):
  1. Cloud Run service sits behind IAP with `--allow-unauthenticated` absent.
     *Infrastructure, not agent-runnable -- not asserted here. See EXECUTION_PLAN §4.*
  2. Any unauthenticated request to /api/* returns 401.
  3. `x-goog-iap-jwt-assertion` is verified for signature, `aud`, `iss` and `exp`.
  4. Verification failure returns 401.
  5. No bypass env var exists.

The PRD names this file `tests/test_auth_boundary.py`; it is
`test_us_1_1_auth_boundary.py` so that `pytest.ini`'s `test_us_*.py` pattern
actually collects it. Recorded in EXECUTION_PLAN §7.
"""

import json

import pytest
from cryptography.hazmat.primitives.asymmetric import ec

from conftest import MAPPED_EMAIL, PortalClient

# Criterion 2 says *any* /api/* path, so the gate is asserted as one chokepoint
# over a spread of handlers -- local, Cube-backed, telemetry and unknown alike.
API_PATHS = [
    "/api/identity",
    "/api/status",
    "/api/cube/load",
    "/api/cube/slicers",
    "/api/member_analysis/query",
    "/api/telemetry/overview",
    "/api/does-not-exist",
]

# Only these two answer without reaching Cube, so they are the ones a positive
# test can assert a 200 on offline.
LOCAL_API_PATHS = ["/api/identity", "/api/status"]


@pytest.mark.parametrize("path", API_PATHS)
def test_unauthenticated_request_is_rejected(anon_portal, path):
    """Criterion 2: no assertion header at all -> 401, on every /api/* path."""
    status, _ = anon_portal.get(path)
    assert status == 401, f"{path} served an unauthenticated caller {status}"


@pytest.mark.parametrize("path", API_PATHS)
def test_garbage_assertion_is_rejected(anon_portal, path):
    """A header that is not a JWT at all must not crash into a 500."""
    client = anon_portal.with_headers(**{"x-goog-iap-jwt-assertion": "not-a-jwt"})
    status, _ = client.get(path)
    assert status == 401, f"{path} answered {status} to a malformed assertion"


def test_expired_assertion_is_rejected(_server_base, iap):
    """Criterion 3: `exp` is checked."""
    client = PortalClient(_server_base, iap.header(expires_in=-60))
    status, _ = client.get("/api/identity")
    assert status == 401


def test_wrong_audience_is_rejected(_server_base, iap):
    """Criterion 3: `aud` is checked -- a token minted for another IAP app."""
    client = PortalClient(_server_base,
                          iap.header(audience="/projects/999/apps/someone-else"))
    status, _ = client.get("/api/identity")
    assert status == 401


def test_wrong_issuer_is_rejected(_server_base, iap):
    """Criterion 3: `iss` is checked."""
    client = PortalClient(_server_base, iap.header(issuer="https://evil.example/iap"))
    status, _ = client.get("/api/identity")
    assert status == 401


def test_foreign_key_signature_is_rejected(_server_base, iap):
    """Criterion 3: the signature is checked against the trusted JWKS.

    Every claim is correct; only the signing key is not the issuer's.
    """
    attacker_key = ec.generate_private_key(ec.SECP256R1())
    client = PortalClient(_server_base, iap.header(key=attacker_key))
    status, _ = client.get("/api/identity")
    assert status == 401


def test_tampered_payload_is_rejected(_server_base, iap):
    """Swapping the email in a validly-signed token breaks the signature."""
    token = iap.mint(email=MAPPED_EMAIL)
    header_b64, payload_b64, signature = token.split(".")
    forged_payload = jwt_b64(json.loads(b64pad_decode(payload_b64)) |
                             {"email": "attacker@evil.example"})
    client = PortalClient(_server_base, {
        "x-goog-iap-jwt-assertion": f"{header_b64}.{forged_payload}.{signature}"})
    status, _ = client.get("/api/identity")
    assert status == 401


def test_unsigned_alg_none_token_is_rejected(_server_base, iap):
    """`alg: none` must never be accepted -- the classic JWT bypass."""
    client = PortalClient(_server_base, iap.header(algorithm="none"))
    status, _ = client.get("/api/identity")
    assert status == 401


def test_unknown_kid_is_rejected(_server_base, iap):
    """A `kid` absent from the JWKS has no key to verify against."""
    client = PortalClient(_server_base, iap.header(kid="no-such-key"))
    status, _ = client.get("/api/identity")
    assert status == 401


@pytest.mark.parametrize("path", LOCAL_API_PATHS)
def test_valid_assertion_is_served(portal, path):
    """The gate must let a properly signed, in-audience, unexpired caller through."""
    status, body = portal.get(path)
    assert status == 200, f"{path} rejected a valid assertion: {status} {str(body)[:200]}"


def test_verified_caller_is_authenticated(portal):
    """Criterion 3 end to end: the email the gate trusts is the token's own."""
    body = portal.get_json("/api/identity")
    assert body["authenticated"] is True
    assert body["email"] == MAPPED_EMAIL


def test_static_assets_are_not_behind_the_api_gate(anon_portal):
    """Only /api/* is gated here. IAP fronts the static tier in production
    (criterion 1); a 401 on `/` would break the local dev loop for no gain."""
    status, _ = anon_portal.get("/")
    assert status != 401


def test_no_bypass_env_var_exists():
    """Criterion 5: no switch in server.py turns the gate off.

    `SCBI_IAP_JWKS_URL` is permitted and is not such a switch -- it redirects
    *which* issuer is trusted, and full signature/aud/iss/exp verification
    still runs. See IapHarness' docstring.
    """
    source = (__import__("pathlib").Path(__file__).resolve().parent.parent
              / "server.py").read_text(encoding="utf-8")
    for forbidden in ("SCBI_SKIP_AUTH", "SCBI_DISABLE_AUTH", "SCBI_ALLOW_ANONYMOUS",
                      "SKIP_IAP", "DISABLE_IAP", "SCBI_DEV_MODE", "SCBI_NO_AUTH"):
        assert forbidden not in source, f"server.py reads a bypass switch: {forbidden}"


def b64pad_decode(segment):
    import base64
    return base64.urlsafe_b64decode(segment + "=" * (-len(segment) % 4))


def jwt_b64(claims):
    import base64
    raw = json.dumps(claims, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")
