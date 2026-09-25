"""
Test suite for Ticket V2-3.2: Thin Web Portal Decoupled API Gateway

Verifies all 4 Acceptance Criteria:
1. Replaces monolithic legacy `thin-web-app/server.py` with modular FastAPI router (`version-two/portal/server.py`, `version-two/portal/auth.py`).
2. Extracts verified user identity from `X-Goog-Authenticated-User-Email` header, rejecting unauthenticated requests with HTTP 401.
3. Mints signed Cube JWT containing verified role and PII permissions from `role_assignments.json`.
4. Replaces synthetic data endpoints (`handle_member_analysis_query`) with live Cube REST queries.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
PORTAL_DIR = PROJECT_ROOT / "version-two" / "portal"
CUBE_DIR = PROJECT_ROOT / "version-two" / "cube"
ROSTER_PATH = PROJECT_ROOT / "thin-web-app" / "role_assignments.json"


def _load_portal_module(name: str, file_path: Path):
    if str(PORTAL_DIR) not in sys.path:
        sys.path.insert(0, str(PORTAL_DIR))
    spec = importlib.util.spec_from_file_location(name, file_path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


auth_mod = _load_portal_module("auth", PORTAL_DIR / "auth.py")
server_mod = _load_portal_module("server", PORTAL_DIR / "server.py")


class TestV232PortalApiGateway(unittest.TestCase):
    """Validates V2-3.2 Portal API Gateway authentication, JWT minting, and live Cube REST proxying."""

    def test_ac1_modular_router_and_zero_synthetic_constants(self) -> None:
        """AC 1: Replaces monolithic legacy server.py with modular router (auth.py + server.py)."""
        self.assertTrue((PORTAL_DIR / "auth.py").exists())
        self.assertTrue((PORTAL_DIR / "server.py").exists())

        server_source = (PORTAL_DIR / "server.py").read_text(encoding="utf-8")
        # Must not contain legacy synthetic fabrication banner or hardcoded fake consultant names
        self.assertNotIn("DEMO DATA — NOT FROM SOURCE", server_source)
        self.assertNotIn("Johan van der Merwe", server_source)

        app = server_mod.create_portal_app()
        client = server_mod.PortalTestClient(app)
        health = client.get("/health")
        self.assertEqual(health.status_code, 200)
        self.assertEqual(health.json()["status"], "HEALTHY")
        self.assertFalse(health.json()["synthetic_endpoints_enabled"])

    def test_ac2_iap_header_extraction_and_401_on_unauthenticated(self) -> None:
        """AC 2: Extracts verified user identity from X-Goog-Authenticated-User-Email, rejecting unauthenticated with HTTP 401."""
        app = server_mod.create_portal_app()
        client = server_mod.PortalTestClient(app)

        # Missing header -> HTTP 401
        unauth_resp = client.get("/api/whoami")
        self.assertEqual(unauth_resp.status_code, 401)
        self.assertIn("X-Goog-Authenticated-User-Email", unauth_resp.json()["error"])

        # Malformed header -> HTTP 401
        malformed_resp = client.get(
            "/api/whoami",
            headers={"X-Goog-Authenticated-User-Email": "accounts.google.com:not-an-email"},
        )
        self.assertEqual(malformed_resp.status_code, 401)

        # Valid IAP header with accounts.google.com prefix
        valid_resp = client.get(
            "/api/whoami",
            headers={"X-Goog-Authenticated-User-Email": "accounts.google.com:charltonsmithfde@gmail.com"},
        )
        self.assertEqual(valid_resp.status_code, 200)
        self.assertEqual(valid_resp.json()["email"], "charltonsmithfde@gmail.com")

    def test_ac3_mints_signed_cube_jwt_from_role_assignments_and_prevents_escalation(self) -> None:
        """AC 3: Mints signed Cube JWT containing verified role and PII permissions from role_assignments.json."""
        secret = "test-portal-cube-shared-hs256-secret-32b!!"
        app = server_mod.create_portal_app(roster_path=ROSTER_PATH, api_secret=secret)
        client = server_mod.PortalTestClient(app)

        # 1. Known system owner in role_assignments.json
        owner_resp = client.get(
            "/api/whoami",
            headers={"X-Goog-Authenticated-User-Email": "accounts.google.com:charltonsmithfde@gmail.com"},
        )
        self.assertEqual(owner_resp.status_code, 200)
        owner_data = owner_resp.json()
        self.assertTrue(owner_data["can_view_pii"])

        decoded_owner = auth_mod.decode_and_verify_cube_jwt(owner_data["jwt_token"], secret=secret)
        self.assertEqual(decoded_owner["sub"], "charltonsmithfde@gmail.com")
        self.assertTrue(decoded_owner["canViewPii"])

        # 2. Unknown corporate user attempting privilege escalation via query param -> capped to ROLE_FINANCE_MEMBER
        unknown_resp = client.get(
            "/api/whoami?role=ROLE_ADMIN&can_view_pii=true",
            headers={"X-Goog-Authenticated-User-Email": "accounts.google.com:analyst@sanlam.co.za"},
        )
        self.assertEqual(unknown_resp.status_code, 200)
        unknown_data = unknown_resp.json()
        self.assertEqual(unknown_data["role"], "ROLE_FINANCE_MEMBER")
        self.assertFalse(unknown_data["can_view_pii"])

        decoded_unknown = auth_mod.decode_and_verify_cube_jwt(unknown_data["jwt_token"], secret=secret)
        self.assertEqual(decoded_unknown["role"], "ROLE_FINANCE_MEMBER")
        self.assertFalse(decoded_unknown["canViewPii"])

    def test_ac4_replaces_synthetic_member_analysis_with_live_cube_rest_queries(self) -> None:
        """AC 4: Replaces synthetic handle_member_analysis_query with live Cube REST queries."""
        secret = "live-e2e-portal-to-cube-hs256-secret-key!!"
        with tempfile.TemporaryDirectory() as tmpdir:
            catalog_path = str(Path(tmpdir) / "portal_e2e_catalog.db")
            # Start Cube HTTP server in a background Node child process, then call it from Python Portal Gateway
            node_runner = f"""
const cube = require({json.dumps(str(CUBE_DIR / "cube.js"))});
(async () => {{
  const srv = await cube.startCubeHttpServer({{
    port: 0,
    catalogDbPath: {json.dumps(catalog_path)},
    apiSecret: {json.dumps(secret)}
  }});
  console.log(JSON.stringify({{ port: srv.port }}));
  process.stdin.resume();
  process.stdin.on('data', async () => {{
    await srv.close();
    process.exit(0);
  }});
}})();
"""
            proc = subprocess.Popen(
                ["node", "-e", node_runner],
                cwd=str(PROJECT_ROOT),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            try:
                assert proc.stdout is not None
                line = proc.stdout.readline().strip()
                port_info = json.loads(line)
                cube_url = f"http://127.0.0.1:{port_info['port']}"

                app = server_mod.create_portal_app(
                    cube_base_url=cube_url,
                    roster_path=ROSTER_PATH,
                    api_secret=secret,
                )
                client = server_mod.PortalTestClient(app)

                # Query as least-privileged user (PII masked)
                resp_masked = client.get(
                    "/api/member_analysis_query?role=IGNORED_CLIENT_PARAM",
                    headers={"X-Goog-Authenticated-User-Email": "accounts.google.com:viewer@sanlam.co.za"},
                )
                self.assertEqual(resp_masked.status_code, 200)
                body_masked = resp_masked.json()
                self.assertEqual(body_masked["data_source"], "cube_rest_live")
                self.assertFalse(body_masked["demo_data"])
                self.assertEqual(body_masked["role"], "ROLE_FINANCE_MEMBER")
                self.assertFalse(body_masked["can_view_pii"])
                self.assertEqual(body_masked["metrics"]["active_member_count"], 29209326)
                self.assertIn(
                    "sha256(",
                    body_masked["compiled_dimension_sql"]["MemberAnalysis.id_number"],
                )

                # Query as authorized system owner in role_assignments.json (unmasked PII)
                resp_owner = client.get(
                    "/api/member_analysis_query",
                    headers={"X-Goog-Authenticated-User-Email": "accounts.google.com:charltonsmithfde@gmail.com"},
                )
                self.assertEqual(resp_owner.status_code, 200)
                body_owner = resp_owner.json()
                self.assertTrue(body_owner["can_view_pii"])
                self.assertEqual(body_owner["metrics"]["active_member_count"], 29209326)
                self.assertNotIn(
                    "sha256(",
                    body_owner["compiled_dimension_sql"]["MemberAnalysis.id_number"],
                )
            finally:
                for pipe in (proc.stdin, proc.stdout, proc.stderr):
                    if pipe:
                        try:
                            pipe.close()
                        except OSError:
                            pass
                proc.terminate()
                proc.wait(timeout=5)


if __name__ == "__main__":
    unittest.main()
