"""
Automated Verification Suite for Ticket V2-2.2:
Server-Enforced RBAC & Dynamic POPIA Masking Security Context

Compatible with both standard library `unittest` and `pytest`.
"""

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
VERSION_TWO_DIR = PROJECT_ROOT / "version-two"
CUBE_DIR = VERSION_TWO_DIR / "cube"
SECURITY_JS_PATH = CUBE_DIR / "security.js"
CUBE_JS_PATH = CUBE_DIR / "cube.js"
ROSTER_PATH = PROJECT_ROOT / "thin-web-app" / "role_assignments.json"


class TestV222CubeSecurityContext(unittest.TestCase):
    """Test suite validating server-enforced RBAC and POPIA masking (V2-2.2)."""

    def test_jwt_verification_extracts_role_and_can_view_pii(self):
        """AC1: security.js extracts role and canViewPii from the verified JWT payload."""
        self.assertTrue(SECURITY_JS_PATH.is_file(), "version-two/cube/security.js must exist")
        self.assertTrue(ROSTER_PATH.is_file(), "thin-web-app/role_assignments.json must exist")

        node_script = f"""
        const sec = require({json.dumps(str(SECURITY_JS_PATH))});
        const secret = 'unit-test-hs256-secret-key-minimum-32-bytes!!';

        (async () => {{
          // 1. Valid Executive token -> role: ROLE_EXECUTIVE_ALL, canViewPii: true
          const execToken = sec.signHs256Jwt({{
            sub: 'charltonsmithfde@gmail.com',
            role: 'ROLE_EXECUTIVE_ALL',
            canViewPii: true
          }}, secret);
          const execReq = {{ headers: {{ authorization: `Bearer ${{execToken}}` }} }};
          const execCtx = await sec.checkAuth(execReq, null, secret);

          // 2. Non-PII role attempting to self-assert canViewPii: true -> forced to false
          const analystToken = sec.signHs256Jwt({{
            sub: 'analyst@sanlam.co.za',
            role: 'ROLE_ANNUITY_ANALYST',
            canViewPii: true
          }}, secret);
          const analystCtx = await sec.checkAuth({{}}, analystToken, secret);

          // 3. Forged signature -> rejected with 401
          let forgedRejected = false;
          let forgedStatus = null;
          try {{
            await sec.checkAuth({{}}, execToken + 'tampered', secret);
          }} catch (err) {{
            forgedRejected = true;
            forgedStatus = err.statusCode;
          }}

          // 4. Roster lookup for system owner vs unmapped user
          const ownerRoster = sec.resolveUserRoleFromRoster('charltonsmithfde@gmail.com');
          const unknownRoster = sec.resolveUserRoleFromRoster('unmapped.user@sanlam.co.za');

          console.log(JSON.stringify({{
            execCtx,
            analystCtx,
            forgedRejected,
            forgedStatus,
            ownerRoster,
            unknownRoster
          }}));
        }})().catch((e) => {{
          console.error(e);
          process.exit(1);
        }});
        """
        proc = subprocess.run(
            ["node", "-e", node_script],
            capture_output=True,
            text=True,
            check=True,
        )
        res = json.loads(proc.stdout.strip())

        self.assertEqual(res["execCtx"]["role"], "ROLE_EXECUTIVE_ALL")
        self.assertTrue(res["execCtx"]["canViewPii"])
        self.assertEqual(res["analystCtx"]["role"], "ROLE_ANNUITY_ANALYST")
        self.assertFalse(res["analystCtx"]["canViewPii"])
        self.assertTrue(res["forgedRejected"])
        self.assertEqual(res["forgedStatus"], 401)

        self.assertEqual(res["ownerRoster"]["role"], "ROLE_EXECUTIVE_ALL")
        self.assertTrue(res["ownerRoster"]["canViewPii"])
        self.assertEqual(res["unknownRoster"]["role"], "ROLE_FINANCE_MEMBER")
        self.assertFalse(res["unknownRoster"]["canViewPii"])

    def test_unauthorized_cube_rejected_with_http_403_forbidden(self):
        """AC2: Inbound queries requesting cubes outside ROLE_PERMISSIONS[role].allowedCubes are rejected with HTTP 403."""
        tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        db_path = tmp.name
        tmp.close()

        try:
            node_script = f"""
            const sec = require({json.dumps(str(SECURITY_JS_PATH))});
            const cube = require({json.dumps(str(CUBE_JS_PATH))});
            const secret = 'unit-test-hs256-secret-key-minimum-32-bytes!!';

            (async () => {{
              const instance = await cube.startCubeHttpServer({{
                port: 0,
                catalogDbPath: {json.dumps(db_path)},
                apiSecret: secret
              }});
              try {{
                const annuityToken = sec.signHs256Jwt({{
                  sub: 'annuity.analyst@sanlam.co.za',
                  role: 'ROLE_ANNUITY_ANALYST',
                  canViewPii: false
                }}, secret);

                // 1. Authorized query (AnnuityQuotation + SharedDimensions) -> HTTP 200
                const allowedRes = await fetch(`http://127.0.0.1:${{instance.port}}/cubejs-api/v1/load`, {{
                  method: 'POST',
                  headers: {{
                    'Content-Type': 'application/json',
                    'Authorization': `Bearer ${{annuityToken}}`
                  }},
                  body: JSON.stringify({{
                    query: {{
                      measures: ['AnnuityQuotation.quotationCount'],
                      dimensions: ['SharedDimensions.schemeName']
                    }}
                  }})
                }});

                // 2. Unauthorized query (MemberAnalysis) by ROLE_ANNUITY_ANALYST -> HTTP 403
                const forbiddenRes = await fetch(`http://127.0.0.1:${{instance.port}}/cubejs-api/v1/load`, {{
                  method: 'POST',
                  headers: {{
                    'Content-Type': 'application/json',
                    'Authorization': `Bearer ${{annuityToken}}`
                  }},
                  body: JSON.stringify({{
                    query: {{
                      measures: ['MemberAnalysis.activeMemberCount'],
                      dimensions: ['MemberAnalysis.member_id']
                    }}
                  }})
                }});
                const forbiddenBody = await forbiddenRes.json();

                console.log(JSON.stringify({{
                  allowedStatus: allowedRes.status,
                  forbiddenStatus: forbiddenRes.status,
                  forbiddenError: forbiddenBody.error
                }}));
              }} finally {{
                await instance.close();
              }}
            }})().catch((e) => {{
              console.error(e);
              process.exit(1);
            }});
            """
            proc = subprocess.run(
                ["node", "-e", node_script],
                capture_output=True,
                text=True,
                check=True,
            )
            res = json.loads(proc.stdout.strip())

            self.assertEqual(res["allowedStatus"], 200)
            self.assertEqual(res["forbiddenStatus"], 403)
            self.assertIn("HTTP 403 Forbidden", res["forbiddenError"])
            self.assertIn("MemberAnalysis", res["forbiddenError"])
        finally:
            if os.path.exists(db_path):
                os.remove(db_path)

    def test_popia_pii_dimensions_compile_to_salted_hashes(self):
        """AC3: Dimension fields flagged as PII (id_number, member_id, client_name) dynamically compile to salted hashes when canViewPii === false."""
        node_script = f"""
        const sec = require({json.dumps(str(SECURITY_JS_PATH))});

        const maskedQuery = sec.queryRewrite(
          {{
            measures: ['MemberAnalysis.activeMemberCount'],
            dimensions: [
              'MemberAnalysis.id_number',
              'MemberAnalysis.member_id',
              'MemberAnalysis.client_name',
              'MemberAnalysis.member_age'
            ]
          }},
          {{
            securityContext: {{
              role: 'ROLE_FINANCE_MEMBER',
              canViewPii: false
            }}
          }}
        );

        const unmaskedQuery = sec.queryRewrite(
          {{
            measures: ['MemberAnalysis.activeMemberCount'],
            dimensions: [
              'MemberAnalysis.id_number',
              'MemberAnalysis.member_id',
              'MemberAnalysis.client_name',
              'MemberAnalysis.member_age'
            ]
          }},
          {{
            securityContext: {{
              role: 'ROLE_EXECUTIVE_ALL',
              canViewPii: true
            }}
          }}
        );

        const sampleRow = {{
          'MemberAnalysis.id_number': '8501015800084',
          'MemberAnalysis.member_id': 'MEM-99281',
          'MemberAnalysis.client_name': 'Jane Doe',
          'MemberAnalysis.member_age': 41
        }};
        const maskedRow = sec.maskRowPiiFields(sampleRow, {{ role: 'ROLE_FINANCE_MEMBER', canViewPii: false }});
        const unmaskedRow = sec.maskRowPiiFields(sampleRow, {{ role: 'ROLE_EXECUTIVE_ALL', canViewPii: true }});

        console.log(JSON.stringify({{
          maskedSql: maskedQuery.__compiledDimensionSql,
          unmaskedSql: unmaskedQuery.__compiledDimensionSql,
          maskedRow,
          unmaskedRow
        }}));
        """
        proc = subprocess.run(
            ["node", "-e", node_script],
            capture_output=True,
            text=True,
            check=True,
        )
        res = json.loads(proc.stdout.strip())

        for pii_field in ["id_number", "member_id", "client_name"]:
            dim_key = f"MemberAnalysis.{pii_field}"
            self.assertIn("sha256(CAST(", res["maskedSql"][dim_key])
            self.assertEqual(res["unmaskedSql"][dim_key], dim_key)
            self.assertNotEqual(res["maskedRow"][dim_key], res["unmaskedRow"][dim_key])
            self.assertEqual(len(res["maskedRow"][dim_key]), 64)

        # Non-PII dimension remains untouched
        self.assertEqual(res["maskedSql"]["MemberAnalysis.member_age"], "MemberAnalysis.member_age")
        self.assertEqual(res["maskedRow"]["MemberAnalysis.member_age"], 41)

    def test_sql_api_scrypt_password_verification_rejects_forged_credentials(self):
        """AC4: Password verification for SQL API callers uses secure scrypt hash comparison, rejecting forged credentials."""
        node_script = f"""
        const sec = require({json.dumps(str(SECURITY_JS_PATH))});

        (async () => {{
          const validPassword = 'correct-horse-battery-staple';
          const digest = sec.scryptDigest(validPassword);
          const rawStore = JSON.stringify({{
            'metabase.quotations@sanlam.co.za': {{
              password: digest,
              role: 'ROLE_ANNUITY_ANALYST'
            }}
          }});
          const store = sec.parseSqlUsers(rawStore);

          // 1. Valid password -> accepted
          const authOk = await sec.checkSqlAuth(
            {{}},
            {{ u: 'metabase.quotations@sanlam.co.za', password: validPassword }},
            store
          );

          // 2. Wrong password -> rejected
          let wrongPassRejected = false;
          try {{
            await sec.checkSqlAuth(
              {{}},
              {{ u: 'metabase.quotations@sanlam.co.za', password: 'forged-password' }},
              store
            );
          }} catch (_err) {{
            wrongPassRejected = true;
          }}

          // 3. Unknown user -> rejected
          let unknownUserRejected = false;
          try {{
            await sec.checkSqlAuth(
              {{}},
              {{ u: 'attacker@sanlam.co.za', password: validPassword }},
              store
            );
          }} catch (_err) {{
            unknownUserRejected = true;
          }}

          // 4. Plaintext password in store -> rejected at parse time
          let plaintextStoreRejected = false;
          try {{
            sec.parseSqlUsers(JSON.stringify({{
              'bad@sanlam.co.za': {{ password: 'plaintext_password', role: 'ROLE_ANNUITY_ANALYST' }}
            }}));
          }} catch (_err) {{
            plaintextStoreRejected = true;
          }}

          console.log(JSON.stringify({{
            authOk,
            wrongPassRejected,
            unknownUserRejected,
            plaintextStoreRejected
          }}));
        }})().catch((e) => {{
          console.error(e);
          process.exit(1);
        }});
        """
        proc = subprocess.run(
            ["node", "-e", node_script],
            capture_output=True,
            text=True,
            check=True,
        )
        res = json.loads(proc.stdout.strip())

        self.assertEqual(res["authOk"]["securityContext"]["role"], "ROLE_ANNUITY_ANALYST")
        self.assertFalse(res["authOk"]["securityContext"]["canViewPii"])
        self.assertTrue(res["wrongPassRejected"])
        self.assertTrue(res["unknownUserRejected"])
        self.assertTrue(res["plaintextStoreRejected"])


if __name__ == "__main__":
    unittest.main()
