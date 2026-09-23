"""US-1.3 — Make Cube reject unverified callers.

Acceptance criteria (PRD_ARCHITECTURE_REALIGNMENT.md, EPIC 1):
  1. `CUBEJS_API_SECRET` is loaded from Secret Manager; no default in code.
  2. `checkSqlAuth` verifies the supplied password against a credential store. The current
     `return { password: auth.password }` — which accepts any password — is removed.
  3. Cloud Run `scbi-cube` is `--no-allow-unauthenticated`; the thin app calls it with a
     service-account ID token.
  4. A request bearing a JWT signed with the old hardcoded secret is rejected.

What is proven here, and what is not
------------------------------------
Criteria 1, 2 and 4 are proven in full. Criterion 3 splits: **the caller half is proven here**
(the thin app attaches a service-account ID token), while flipping `scbi-cube` to
`--no-allow-unauthenticated` and dropping its `allUsers` invoker binding is a GCP-side act that
cannot be asserted from the tree. That half stays on the owed list in EXECUTION_PLAN.md §6 —
the same split US-1.1 criterion 1 and US-2.2 criteria 1/3 already carry.

Seams
-----
**A Node harness** carries criteria 1, 2 and 4. It loads the *real* `cube/cube.js` and calls the
*real* `checkSqlAuth`, so a rejection is proven by the function refusing, not by the source text
looking right. This repo has now been burned three times by checks that read the right thing and
proved nothing — the `dbType` version check (ledger 2026-09-20, US-3.0), the "known flake" that
was an unread pipe (EXECUTION_PLAN §2), and the regex suite US-1.4 deliberately did not write.
`cube/node_modules` does not exist, so the harness stubs `@cubejs-backend/duckdb-driver` via
`Module._resolveFilename` rather than installing it. The pattern is lifted from
`test_us_1_4_rbac_allowlist.py`.

**Seam A, in process**, carries criterion 3's caller half. `server.py` is import-safe (everything
runs under `__main__`), so these tests import it with a patched environment and call the real
`query_cube` against a stub Cube and a stub GCE metadata server. Nothing is mocked out of the
path under test.

On the revoked secret
--------------------
Criterion 4 names the secret that was hardcoded in both servers before US-2.2. Its literal value
appears nowhere in this file, because `test_us_2_2_no_secrets.py` sweeps every `.py` and `.js`
under `data-recon/` for it and that sweep must keep passing. Only its SHA-256 is written down —
a digest is a detection rule, not a credential, and the value it covers is in the PRD prose
already. The two tests below split accordingly: one proves the *mechanism* rejects a revoked
digest using a throwaway value, the other proves the real revocation list *contains* this
digest.
"""

from __future__ import annotations

import hashlib
import http.server
import importlib.util
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import threading
from pathlib import Path

import pytest

APP_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = APP_DIR.parent
CUBE_DIR = REPO_ROOT / "cube"
CUBE_JS = CUBE_DIR / "cube.js"
MODEL_DIR = CUBE_DIR / "model" / "cubes"
SERVER_PY = APP_DIR / "server.py"

# SHA-256 of the API signing secret that sat in the repo. See the module docstring for why the
# value itself is absent. cube.js must refuse to start if CUBEJS_API_SECRET hashes to this.
REVOKED_SECRET_SHA256 = "a714a688c5d0d354fad31fa06c11531fe47ab43f37c479c8cce2372ebcac7281"

# A secret that is fine on every axis: not revoked, and at or over RFC 7518's 32-byte floor for
# HS256. 43 chars, the width `secrets.token_urlsafe(32)` produces.
GOOD_SECRET = "us13TestSecretNotRealAndLongEnoughForHs256x"

# Under the 32-byte floor. The old secret was 24 bytes, so length alone already excluded it;
# the revocation list is the guard that names criterion 4 explicitly.
SHORT_SECRET = "tooShortForHs256"

# US-8.3 added `assertSqlApiIsCoherent()` to cube.js as a module-load side effect: a populated
# CUBEJS_SQL_USERS with no CUBEJS_PG_SQL_PORT is a configuration nothing can serve, and the config
# now refuses to load rather than run a credential store no listener will ever consult. Every
# helper below provisions SQL users, so every helper must also declare the port -- otherwise this
# suite asks cube.js to load a configuration that is invalid in production, and what it proves
# about checkSqlAuth would be proven against a config that could never boot.
SQL_PORT = "5432"

# Deliberately a username the *old* prefix heuristic would have read as ROLE_FINANCE_MEMBER,
# paired below with a stored role of ROLE_ANNUITY. Had they agreed, every role assertion in this
# module would pass against the unfixed code. Metabase is the real consumer of this seam.
SQL_USER = "metabase.quotations@sanlam.co.za"
SQL_PASSWORD = "harness-only-sql-password"


# ──────────────────────────────────────────────────────────────────────────────
# Credential-store helpers
# ──────────────────────────────────────────────────────────────────────────────

def scrypt_digest(password: str, salt_hex: str) -> str:
    """Node's `crypto.scryptSync(password, salt, 32)` defaults, reproduced.

    Verified byte-identical to Node v22 before this suite was written: N=16384, r=8, p=1,
    32-byte key. If cube.js ever changes those parameters this helper must change with it, and
    `test_a_known_user_with_the_right_password_is_accepted` is what will catch it.
    """
    key = hashlib.scrypt(
        password.encode("utf-8"),
        salt=bytes.fromhex(salt_hex),
        n=16384,
        r=8,
        p=1,
        dklen=32,
    )
    return f"scrypt:{salt_hex}:{key.hex()}"


def sql_user_store(
    username: str = SQL_USER,
    password: str = SQL_PASSWORD,
    role: str = "ROLE_ANNUITY",
    salt_hex: str = "5ca1ab1e5ca1ab1e",
    **extra,
) -> str:
    entry = {"password": scrypt_digest(password, salt_hex), "role": role}
    entry.update(extra)
    return json.dumps({username: entry})


# ──────────────────────────────────────────────────────────────────────────────
# Node harness — load the real cube.js, call the real checkSqlAuth
# ──────────────────────────────────────────────────────────────────────────────

_STUB_DRIVER = (
    "class DuckDBDriver { constructor(options) { this.options = options; } }\n"
    "module.exports = { DuckDBDriver };\n"
)

_HARNESS = """
const path = require('path');
const Module = require('module');

const stub = path.resolve(__dirname, 'stub_driver.js');
const originalResolve = Module._resolveFilename;
Module._resolveFilename = function (request, ...rest) {
  if (request === '@cubejs-backend/duckdb-driver') return stub;
  return originalResolve.call(this, request, ...rest);
};

const job = JSON.parse(process.argv[3]);

// cube.js reads its configuration at module load. The GCS pair is a placeholder -- the harness
// never opens a connection. Everything else comes from the job so each test controls it.
process.env.CUBEJS_DB_DUCKDB_S3_ACCESS_KEY_ID = 'harness-not-a-real-key';
process.env.CUBEJS_DB_DUCKDB_S3_SECRET_ACCESS_KEY = 'harness-not-a-real-secret';
for (const [key, value] of Object.entries(job.env || {})) {
  if (value === null) delete process.env[key];
  else process.env[key] = value;
}

const emit = (payload) => { console.log(JSON.stringify(payload)); process.exit(0); };

let config;
try {
  config = require(process.argv[2]);
} catch (err) {
  emit({ outcome: 'load_error', message: String(err.message) });
}

(async () => {
  if (job.action === 'load') emit({ outcome: 'loaded' });

  if (job.action === 'sqlauth') {
    try {
      const result = await config.checkSqlAuth(job.request || {}, job.auth);
      emit({ outcome: 'accepted', result: result });
    } catch (err) {
      emit({ outcome: 'rejected', message: String(err.message) });
    }
  }

  emit({ outcome: 'unknown_action', message: String(job.action) });
})();
"""


@pytest.fixture(scope="session")
def harness_dir(tmp_path_factory) -> Path:
    directory = tmp_path_factory.mktemp("cube_auth_harness")
    (directory / "stub_driver.js").write_text(_STUB_DRIVER, encoding="utf-8")
    (directory / "harness.js").write_text(_HARNESS, encoding="utf-8")
    return directory


def _run(harness_dir: Path, config_path: Path, job: dict) -> dict:
    result = subprocess.run(
        [
            "node",
            str(harness_dir / "harness.js"),
            str(config_path).replace("\\", "/"),
            json.dumps(job),
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, (
        f"Harness exited {result.returncode}.\nstdout: {result.stdout}\nstderr: {result.stderr}"
    )
    return json.loads(result.stdout.strip().splitlines()[-1])


def sql_login(harness_dir: Path, auth: dict, env: dict | None = None,
              config_path: Path | None = None) -> dict:
    """Ask the real checkSqlAuth to authenticate `auth`. Returns accepted/rejected/load_error."""
    full_env = {
        "CUBEJS_API_SECRET": GOOD_SECRET,
        "CUBEJS_SQL_USERS": sql_user_store(),
        "CUBEJS_PG_SQL_PORT": SQL_PORT,
    }
    full_env.update(env or {})
    return _run(
        harness_dir,
        config_path or CUBE_JS,
        {"action": "sqlauth", "auth": auth, "env": full_env},
    )


def load_config(harness_dir: Path, env: dict | None = None,
                config_path: Path | None = None) -> dict:
    full_env = {
        "CUBEJS_API_SECRET": GOOD_SECRET,
        "CUBEJS_SQL_USERS": sql_user_store(),
        "CUBEJS_PG_SQL_PORT": SQL_PORT,
    }
    full_env.update(env or {})
    return _run(harness_dir, config_path or CUBE_JS, {"action": "load", "env": full_env})


# ──────────────────────────────────────────────────────────────────────────────
# Criterion 2 — checkSqlAuth verifies the password
# ──────────────────────────────────────────────────────────────────────────────

def test_the_harness_loads_the_real_cube_config(harness_dir):
    """Anti-vacuity guard. If this fails, every assertion below passes for the wrong reason."""
    assert load_config(harness_dir)["outcome"] == "loaded"


def test_sql_login_with_an_arbitrary_password_fails(harness_dir):
    """The PRD's verification clause, verbatim: 'SQL API login with an arbitrary password fails.'

    This is the hole US-1.3 exists to close. `return { password: auth.password }` echoed whatever
    arrived, so Cube's own comparison compared the caller's password against itself.
    """
    outcome = sql_login(harness_dir, {"u": SQL_USER, "password": "not-the-stored-password"})
    assert outcome["outcome"] == "rejected", (
        "checkSqlAuth accepted an arbitrary password for a known user. The SQL API is still an "
        f"open endpoint. It returned: {json.dumps(outcome.get('result'))}"
    )


def test_a_known_user_with_the_right_password_is_accepted(harness_dir):
    """The other half of criterion 2: verification must not reject everyone."""
    outcome = sql_login(harness_dir, {"u": SQL_USER, "password": SQL_PASSWORD})
    assert outcome["outcome"] == "accepted", (
        f"checkSqlAuth rejected the stored credential: {outcome.get('message')}"
    )
    context = outcome["result"]["securityContext"]
    assert context["role"] == "ROLE_ANNUITY", (
        f"The role must come from the credential store, not the username. Got {context['role']}."
    )


def test_an_unknown_username_is_rejected(harness_dir):
    outcome = sql_login(harness_dir, {"u": "nobody@example.com", "password": SQL_PASSWORD})
    assert outcome["outcome"] == "rejected", (
        "A username absent from the credential store was authenticated."
    )


def test_an_empty_password_is_rejected(harness_dir):
    for password in ("", None):
        outcome = sql_login(harness_dir, {"u": SQL_USER, "password": password})
        assert outcome["outcome"] == "rejected", (
            f"checkSqlAuth accepted password={password!r} for a known user."
        )


def test_a_login_with_no_username_is_rejected(harness_dir):
    """`auth.u` used to default to 'public_user' and carry ROLE_FINANCE_MEMBER."""
    outcome = sql_login(harness_dir, {"password": SQL_PASSWORD})
    assert outcome["outcome"] == "rejected", (
        "An anonymous SQL login was authenticated. There is no public user."
    )


def test_the_sql_api_fails_closed_when_no_credential_store_is_configured(harness_dir):
    """No store must mean no SQL access, not open access.

    Cube's own `CUBEJS_SQL_USER` / `CUBEJS_SQL_PASSWORD` check is bypassed entirely whenever
    `checkSqlAuth` is defined, so 'unconfigured' cannot be allowed to mean 'unauthenticated'.
    """
    outcome = sql_login(
        harness_dir,
        {"u": SQL_USER, "password": SQL_PASSWORD},
        env={"CUBEJS_SQL_USERS": None},
    )
    assert outcome["outcome"] == "rejected", (
        "With no CUBEJS_SQL_USERS configured, checkSqlAuth authenticated a caller."
    )


def test_the_username_prefix_heuristic_is_gone(harness_dir):
    """P3 in the PRD names this: role was derived from the spelling of the username.

    `exec*` and `admin` self-promoted to ROLE_EXECUTIVE_ALL with canViewPii true, on any
    password. A caller must now be in the store, and the store must say the role.
    """
    for username in ("exec.someone", "admin", "digital.ops", "investments.desk", "annuity.desk"):
        outcome = sql_login(harness_dir, {"u": username, "password": SQL_PASSWORD})
        assert outcome["outcome"] == "rejected", (
            f"'{username}' authenticated without a credential-store entry; the prefix "
            "heuristic still grants a role."
        )


def test_can_view_pii_is_derived_from_the_role_not_from_the_store(harness_dir):
    """ROLE_PERMISSIONS is the single source of truth for PII visibility.

    A store entry that claims canViewPii on a role that does not hold it must not be believed,
    or the credential store becomes a second, weaker place to grant PII.
    """
    outcome = sql_login(
        harness_dir,
        {"u": SQL_USER, "password": SQL_PASSWORD},
        env={"CUBEJS_SQL_USERS": sql_user_store(role="ROLE_ANNUITY", canViewPii=True)},
    )
    assert outcome["outcome"] == "accepted", outcome.get("message")
    assert outcome["result"]["securityContext"]["canViewPii"] is False, (
        "A credential-store entry granted itself PII visibility on a role whose "
        "ROLE_PERMISSIONS entry has canViewPii false."
    )


def test_startup_fails_when_the_credential_store_names_an_unknown_role(harness_dir):
    outcome = load_config(
        harness_dir,
        env={"CUBEJS_SQL_USERS": sql_user_store(role="ROLE_MADE_UP")},
    )
    assert outcome["outcome"] == "load_error", (
        "cube.js started with a SQL user mapped to a role that has no permissions entry. "
        "queryRewrite would throw on that user's first query instead of at deploy time."
    )
    assert "ROLE_MADE_UP" in outcome["message"], outcome["message"]


def test_startup_fails_when_the_credential_store_is_malformed(harness_dir):
    outcome = load_config(harness_dir, env={"CUBEJS_SQL_USERS": "{not json"})
    assert outcome["outcome"] == "load_error", (
        "Unparseable CUBEJS_SQL_USERS was tolerated. A typo in the secret would silently "
        "close the SQL API instead of failing the deploy."
    )


def test_startup_fails_when_a_stored_password_is_not_a_supported_digest(harness_dir):
    """A plaintext password in the store must be rejected, not hashed on the fly or compared raw."""
    store = json.dumps({SQL_USER: {"password": SQL_PASSWORD, "role": "ROLE_ANNUITY"}})
    outcome = load_config(harness_dir, env={"CUBEJS_SQL_USERS": store})
    assert outcome["outcome"] == "load_error", (
        "A credential-store entry holding something other than a scrypt digest was accepted."
    )


# ──────────────────────────────────────────────────────────────────────────────
# Criteria 1 and 4 — the API secret
# ──────────────────────────────────────────────────────────────────────────────

def test_startup_fails_when_the_api_secret_is_absent(harness_dir):
    """Criterion 1. No in-code default means a missing secret stops the container."""
    outcome = load_config(harness_dir, env={"CUBEJS_API_SECRET": None})
    assert outcome["outcome"] == "load_error", (
        "cube.js started with no CUBEJS_API_SECRET. Cube 0.35 in dev mode generates a random "
        "one, which would make every thin-app token fail verification for an unexplained reason."
    )
    assert "CUBEJS_API_SECRET" in outcome["message"], outcome["message"]


def test_startup_fails_on_a_secret_below_the_hs256_floor(harness_dir):
    """RFC 7518 §3.2: an HS256 key must be at least as long as the hash output, 32 bytes."""
    outcome = load_config(harness_dir, env={"CUBEJS_API_SECRET": SHORT_SECRET})
    assert outcome["outcome"] == "load_error", (
        f"A {len(SHORT_SECRET)}-byte HS256 signing key was accepted."
    )


def test_a_revoked_secret_fails_startup(harness_dir, tmp_path):
    """Criterion 4, mechanism half — proven with a throwaway value, not the real one.

    A copy of cube.js gets a second entry on the revocation list: the digest of a secret this
    test invents. If the guard works, supplying that secret fails the container.
    """
    copied = _cube_dir_copy(tmp_path)
    config = copied / "cube.js"
    source = config.read_text(encoding="utf-8")

    throwaway = "aThrowawaySecretRevokedByThisTestOnlyxx"
    digest = hashlib.sha256(throwaway.encode("utf-8")).hexdigest()
    patched = source.replace(
        f"  '{REVOKED_SECRET_SHA256}'",
        f"  '{digest}',\n  '{REVOKED_SECRET_SHA256}'",
        1,
    )
    assert patched != source, (
        "Could not inject a revoked digest. REVOKED_API_SECRET_SHA256 is no longer a list of "
        "quoted hex digests in cube.js; this fixture needs updating."
    )
    config.write_text(patched, encoding="utf-8")

    outcome = load_config(harness_dir, env={"CUBEJS_API_SECRET": throwaway}, config_path=config)
    assert outcome["outcome"] == "load_error", (
        "cube.js started with a secret whose digest is on the revocation list."
    )
    assert "revoked" in outcome["message"].lower(), outcome["message"]

    # ... and the same copy must still start on a secret that is not revoked, or the test above
    # proves only that the copy is broken.
    assert load_config(harness_dir, config_path=config)["outcome"] == "loaded"


def test_the_revocation_list_contains_the_old_hardcoded_secret(harness_dir):
    """Criterion 4, coverage half. The mechanism above is worthless aimed at nothing."""
    source = CUBE_JS.read_text(encoding="utf-8")
    match = re.search(r"const REVOKED_API_SECRET_SHA256 = new Set\(\[(.*?)\]\)", source, re.DOTALL)
    assert match, "cube.js has no REVOKED_API_SECRET_SHA256 set."
    digests = {d.lower() for d in re.findall(r"'([0-9a-fA-F]{64})'", match.group(1))}
    assert REVOKED_SECRET_SHA256 in digests, (
        "The secret that was hardcoded in both servers before US-2.2 is not on cube.js's "
        "revocation list, so a redeploy could quietly restore it."
    )


def test_the_api_secret_has_no_in_code_default(harness_dir):
    """Criterion 1 restated as a source invariant, since a default would make the test above
    pass while still shipping a fallback key."""
    source = CUBE_JS.read_text(encoding="utf-8")
    assert not re.search(r"CUBEJS_API_SECRET['\"]?\s*\]?\s*\|\|", source), (
        "cube.js falls back to a literal when CUBEJS_API_SECRET is unset."
    )


def _cube_dir_copy(tmp_path: Path) -> Path:
    """A writable copy of cube.js beside the model layer its startup assertions validate."""
    copied = tmp_path / "cube"
    copied.mkdir()
    shutil.copy2(CUBE_JS, copied / "cube.js")
    shutil.copytree(MODEL_DIR, copied / "model" / "cubes")
    return copied


def test_the_unmodified_config_still_loads(harness_dir, tmp_path):
    """Guards every patched-copy test above: an unpatched copy must load cleanly."""
    copied = _cube_dir_copy(tmp_path)
    assert load_config(harness_dir, config_path=copied / "cube.js")["outcome"] == "loaded"


# ──────────────────────────────────────────────────────────────────────────────
# Criterion 3, caller half — the thin app attaches a service-account ID token
# ──────────────────────────────────────────────────────────────────────────────

METADATA_IDENTITY_PATH = "/computeMetadata/v1/instance/service-accounts/default/identity"
CUBE_AUDIENCE = "https://scbi-cube-us13-test.example.run.app"


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class _Recorder(http.server.BaseHTTPRequestHandler):
    """Base for the two stubs. Records every request on the server object."""

    def log_message(self, *args):  # keep the suite's output clean
        pass

    def _record(self):
        self.server.requests.append(
            {
                "path": self.path,
                "headers": {k.lower(): v for k, v in self.headers.items()},
            }
        )

    def _respond(self, body: bytes, content_type: str, status: int = 200):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class _MetadataHandler(_Recorder):
    """Stands in for the GCE metadata server that mints service-account ID tokens."""

    def do_GET(self):
        self._record()
        if not self.path.startswith(METADATA_IDENTITY_PATH):
            self._respond(b"not found", "text/plain", status=404)
            return
        if self.headers.get("Metadata-Flavor") != "Google":
            # The real metadata server refuses without this header. So must the stub, or the
            # test would pass against a client that omits it.
            self._respond(b"missing Metadata-Flavor", "text/plain", status=403)
            return
        audience = self.path.partition("audience=")[2]
        self._respond(f"id-token-for.{audience}".encode(), "text/plain")


class _CubeHandler(_Recorder):
    def do_POST(self):
        self._record()
        length = int(self.headers.get("Content-Length") or 0)
        self.rfile.read(length)
        self._respond(json.dumps({"data": [{"x": 1}]}).encode(), "application/json")


def _serve(handler) -> tuple[http.server.ThreadingHTTPServer, str]:
    server = http.server.ThreadingHTTPServer(("127.0.0.1", _free_port()), handler)
    server.requests = []
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_port}"


@pytest.fixture
def stub_metadata():
    server, base = _serve(_MetadataHandler)
    try:
        yield server, base
    finally:
        server.shutdown()
        server.server_close()


@pytest.fixture
def stub_cube():
    server, base = _serve(_CubeHandler)
    try:
        yield server, base
    finally:
        server.shutdown()
        server.server_close()


def load_server(monkeypatch, **env) -> object:
    """Import server.py fresh with `env` applied. It is import-safe: run_server() is
    only reached under `__main__`."""
    defaults = {
        "CUBEJS_API_SECRET": GOOD_SECRET,
        "SCBI_IAP_AUDIENCE": "/projects/000000000000/apps/us13-test",
    }
    for key, value in {**defaults, **env}.items():
        if value is None:
            monkeypatch.delenv(key, raising=False)
        else:
            monkeypatch.setenv(key, value)

    spec = importlib.util.spec_from_file_location("scbi_server_us13", SERVER_PY)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, "scbi_server_us13", module)
    spec.loader.exec_module(module)
    return module


def test_the_cube_call_carries_a_service_account_id_token(monkeypatch, stub_metadata, stub_cube):
    """Criterion 3, caller half. With `scbi-cube` behind --no-allow-unauthenticated, Cloud Run
    needs a Google-signed ID token for the service, and Cube still needs its own HS256 token."""
    metadata_server, metadata_base = stub_metadata
    cube_server, cube_base = stub_cube

    server = load_server(
        monkeypatch,
        CUBEJS_BASE_URL=cube_base,
        SCBI_CUBE_ID_TOKEN_AUDIENCE=CUBE_AUDIENCE,
        SCBI_METADATA_BASE_URL=metadata_base,
    )
    server.query_cube({"measures": ["MemberMonthly.count"]})

    assert cube_server.requests, "No request reached the stub Cube."
    headers = cube_server.requests[-1]["headers"]

    # Cloud Run authenticates X-Serverless-Authorization and leaves Authorization for the app,
    # which is what lets both tokens travel on one request.
    assert "x-serverless-authorization" in headers, (
        "The Cube request carried no service-account ID token, so it will be refused with 403 "
        f"once scbi-cube is --no-allow-unauthenticated. Headers sent: {sorted(headers)}"
    )
    assert headers["x-serverless-authorization"] == f"Bearer id-token-for.{CUBE_AUDIENCE}", (
        "The ID token was not minted for the configured audience: "
        f"{headers['x-serverless-authorization']}"
    )
    assert headers.get("authorization", "").startswith("Bearer "), (
        "Cube's own HS256 token must stay on Authorization; moving it would break checkAuth."
    )
    assert headers["authorization"] != headers["x-serverless-authorization"], (
        "The same token was sent as both the Cloud Run identity and the Cube API token."
    )

    identity_calls = [r for r in metadata_server.requests
                      if r["path"].startswith(METADATA_IDENTITY_PATH)]
    assert identity_calls, "The metadata server was never asked for an identity token."
    assert f"audience={CUBE_AUDIENCE}" in identity_calls[-1]["path"]


def test_the_id_token_is_cached_across_calls(monkeypatch, stub_metadata, stub_cube):
    """One metadata round trip per token lifetime, not one per query. The dashboards issue
    eight or more Cube calls per page load."""
    metadata_server, metadata_base = stub_metadata
    cube_server, cube_base = stub_cube

    server = load_server(
        monkeypatch,
        CUBEJS_BASE_URL=cube_base,
        SCBI_CUBE_ID_TOKEN_AUDIENCE=CUBE_AUDIENCE,
        SCBI_METADATA_BASE_URL=metadata_base,
    )
    for _ in range(4):
        server.query_cube({"measures": ["MemberMonthly.count"]})

    identity_calls = [r for r in metadata_server.requests
                      if r["path"].startswith(METADATA_IDENTITY_PATH)]
    assert len(identity_calls) == 1, (
        f"The ID token was re-minted on every query ({len(identity_calls)} metadata calls for "
        "4 Cube queries)."
    )
    assert len(cube_server.requests) == 4


def test_no_id_token_is_sent_when_no_audience_is_configured(monkeypatch, stub_cube):
    """Today's behaviour, kept deliberately: scbi-cube currently allows unauthenticated
    invocation, and local runs have no metadata server. Configuring the audience is what opts
    in — so the code half can land before the infra half without breaking either."""
    cube_server, cube_base = stub_cube
    server = load_server(
        monkeypatch,
        CUBEJS_BASE_URL=cube_base,
        SCBI_CUBE_ID_TOKEN_AUDIENCE=None,
    )
    server.query_cube({"measures": ["MemberMonthly.count"]})

    headers = cube_server.requests[-1]["headers"]
    assert "x-serverless-authorization" not in headers
    assert headers.get("authorization", "").startswith("Bearer ")


def test_an_unobtainable_id_token_fails_the_request_rather_than_downgrading_it(
    monkeypatch, stub_cube
):
    """Configured-but-unavailable must not silently send an unauthenticated request. Cloud Run
    would answer 403 and the failure would be reported as a Cube error."""
    cube_server, cube_base = stub_cube
    dead_metadata = f"http://127.0.0.1:{_free_port()}"   # bound by nothing

    server = load_server(
        monkeypatch,
        CUBEJS_BASE_URL=cube_base,
        SCBI_CUBE_ID_TOKEN_AUDIENCE=CUBE_AUDIENCE,
        SCBI_METADATA_BASE_URL=dead_metadata,
    )
    with pytest.raises(Exception):
        server.query_cube({"measures": ["MemberMonthly.count"]})

    assert not cube_server.requests, (
        "A Cube request went out with no ID token after the metadata server was unreachable."
    )
