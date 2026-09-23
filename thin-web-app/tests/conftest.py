"""
Shared fixtures for the PRD acceptance suite.

Seams under test (confirmed 2026-09-19, see PRD_ARCHITECTURE_REALIGNMENT.md):
  A. thin-web-app HTTP API   -- the `portal` fixture below
  B. Cube REST API           -- requires CUBEJS_API_SECRET
  C. DuckDB lakehouse oracle -- requires GCS HMAC credentials
  D. Static repo invariants  -- no fixture needed

Credentials are read from the environment only. Never from source files.
"""

import json
import os
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec
from jwt.algorithms import ECAlgorithm

APP_DIR = Path(__file__).resolve().parent.parent
SERVER_PY = APP_DIR / "server.py"
STARTUP_TIMEOUT_SEC = 30

# US-1.1: the suite mints its own IAP assertions. Google signs ES256 and
# publishes its keys at https://www.gstatic.com/iap/verify/public_key-jwk;
# the harness below stands in for that issuer with a throwaway key pair.
TEST_AUDIENCE = "/projects/000000000000/apps/scbi-thin-web-test"
TEST_ISSUER = "https://cloud.google.com/iap"
TEST_KID = "scbi-test-key-1"
MAPPED_EMAIL = "test.user@sanlam.co.za"


def _drain(stream, sink):
    """Consume a child process' log pipe so it can never fill and block."""
    try:
        for line in stream:
            sink.append(line)
    except (ValueError, OSError):
        pass


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class PortalClient:
    """Minimal HTTP client for the thin-web-app seam.

    `headers` are sent on every request. US-1.1 put every /api/* path behind a
    verified IAP assertion, so the default client carries one -- see the
    `portal` fixture. Use `anon_portal` for the unauthenticated boundary.
    """

    def __init__(self, base_url, headers=None):
        self.base_url = base_url
        self.headers = dict(headers or {})

    def with_headers(self, **headers):
        """A sibling client with extra/replacement headers. Does not mutate self."""
        merged = dict(self.headers)
        merged.update(headers)
        return PortalClient(self.base_url, merged)

    def url(self, path, params=None):
        if params:
            path = f"{path}?{urllib.parse.urlencode(params)}"
        return f"{self.base_url}{path}"

    def get(self, path, params=None, timeout=30):
        """Return (status, parsed_body). Never raises on HTTP error status."""
        req = urllib.request.Request(self.url(path, params), headers=self.headers)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                raw = r.read().decode("utf-8")
                status = r.status
        except urllib.error.HTTPError as e:
            raw = e.read().decode("utf-8")
            status = e.code
        try:
            return status, json.loads(raw)
        except json.JSONDecodeError:
            return status, raw

    def get_json(self, path, params=None, timeout=30):
        status, body = self.get(path, params, timeout)
        assert status == 200, f"GET {path} returned {status}: {str(body)[:300]}"
        assert isinstance(body, dict), f"GET {path} did not return a JSON object: {str(body)[:300]}"
        return body


class IapHarness:
    """Mints signed IAP assertions for the test issuer.

    Why `SCBI_IAP_JWKS_URL` is NOT the "no bypass env var" the US-1.1
    acceptance criteria forbid: full ES256 signature, `aud`, `iss` and `exp`
    verification still runs on every token. The variable only changes *which*
    issuer's public keys are trusted -- it stands in for Google, and grants
    nothing to anyone without the private half of this throwaway key pair.
    Production sets no such variable and reads Google's real JWKS.
    """

    def __init__(self, key, jwks_url):
        self.key = key
        self.jwks_url = jwks_url

    def mint(self, email=MAPPED_EMAIL, audience=TEST_AUDIENCE, issuer=TEST_ISSUER,
             expires_in=3600, kid=TEST_KID, algorithm="ES256", key=None, **extra):
        now = int(time.time())
        claims = {
            "email": email,
            "sub": f"accounts.google.com:{email}",
            "aud": audience,
            "iss": issuer,
            "iat": now,
            "exp": now + expires_in,
        }
        claims.update(extra)
        signing_key = key if key is not None else self.key
        if algorithm == "none":
            return jwt.encode(claims, None, algorithm="none", headers={"kid": kid})
        return jwt.encode(claims, signing_key, algorithm=algorithm, headers={"kid": kid})

    def header(self, **kwargs):
        return {"x-goog-iap-jwt-assertion": self.mint(**kwargs)}


@pytest.fixture(scope="session")
def iap(tmp_path_factory):
    """A throwaway ES256 issuer plus a file:// JWKS the server can fetch."""
    key = ec.generate_private_key(ec.SECP256R1())
    jwk = json.loads(ECAlgorithm.to_jwk(key.public_key()))
    jwk.update({"kid": TEST_KID, "alg": "ES256", "use": "sig"})
    jwks_path = tmp_path_factory.mktemp("iap") / "jwks.json"
    jwks_path.write_text(json.dumps({"keys": [jwk]}), encoding="utf-8")
    return IapHarness(key, jwks_path.as_uri())


@pytest.fixture(scope="session")
def _server_base(iap):
    """Boot thin-web-app/server.py on a free port; yield its base URL.

    An externally running instance can be targeted with TEST_SERVER_BASE.
    Yields a string, not a client -- `portal` and `anon_portal` wrap it.
    """
    external = os.environ.get("TEST_SERVER_BASE")
    if external:
        yield external.rstrip("/")
        return

    port = _free_port()
    # US-2.2: server.py now refuses to start without CUBEJS_API_SECRET. The
    # fixture supplies an obvious non-secret so the unauthenticated suite runs
    # offline; a real value already in the environment is left untouched, which
    # is what the live_cube (seam B) tests use.
    env = os.environ.copy()
    env.setdefault("CUBEJS_API_SECRET", "test-only-not-a-real-secret")
    # US-1.1: point the gate at the test issuer, not Google.
    env["SCBI_IAP_AUDIENCE"] = TEST_AUDIENCE
    env["SCBI_IAP_JWKS_URL"] = iap.jwks_url
    proc = subprocess.Popen(
        [sys.executable, str(SERVER_PY), str(port)],
        cwd=str(APP_DIR),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    # The log pipe MUST be drained continuously. http.server writes one line per
    # request; an unread PIPE fills its OS buffer after ~49 requests and the
    # server then blocks forever on write -- from that point every request in the
    # suite times out, permanently, whatever it asks for. This was mis-diagnosed
    # as upstream Cube latency (EXECUTION_PLAN §2) until it was measured on
    # 2026-09-20: the cliff is deterministic, at request 49, and reproduces on a
    # server with no US-1.1 gate at all. The output is kept rather than sent to
    # DEVNULL so a startup failure can still be reported.
    server_log = []
    drainer = threading.Thread(target=_drain, args=(proc.stdout, server_log), daemon=True)
    drainer.start()
    base = f"http://127.0.0.1:{port}"
    deadline = time.time() + STARTUP_TIMEOUT_SEC
    while time.time() < deadline:
        if proc.poll() is not None:
            drainer.join(timeout=2)
            raise RuntimeError("server.py exited during startup:\n"
                               + "".join(server_log))
        try:
            with urllib.request.urlopen(f"{base}/", timeout=2):
                break
        except Exception:
            time.sleep(0.25)
    else:
        proc.kill()
        drainer.join(timeout=2)
        raise RuntimeError(
            f"server.py did not become ready within {STARTUP_TIMEOUT_SEC}s:\n"
            + "".join(server_log))

    try:
        yield base
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()


@pytest.fixture(scope="session")
def anon_portal(_server_base):
    """An unauthenticated client. US-1.1 says every /api/* path answers it 401."""
    return PortalClient(_server_base)


@pytest.fixture(scope="session")
def portal(_server_base, iap):
    """The default client: authenticated with a valid IAP assertion.

    `MAPPED_EMAIL` is absent from role_assignments.json, so the server falls
    back to LEAST_PRIVILEGED_ROLE with can_view_pii False -- the same
    privilege the pre-US-1.1 suite already asserted.
    """
    return PortalClient(_server_base, iap.header())
