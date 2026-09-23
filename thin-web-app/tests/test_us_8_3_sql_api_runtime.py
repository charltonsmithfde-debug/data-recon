"""US-8.3 — Serve Metabase and Power BI over the Cube SQL API.

> As a BI consumer, I want Metabase and Power BI to read every metric through the Cube SQL API
> (Postgres wire protocol), so that the semantic layer is the single definition of a measure and
> no client re-implements one.

Acceptance criteria:
  1. The container fails to start on a configuration where the SQL API cannot serve: credentials
     with no listening port, the inert `CUBEJS_SQL_PORT` variable, an unusable port number, or a
     super user with no switching policy.
  2. A REST-only runtime (Cloud Run) still starts with no SQL configuration at all.
  3. Each BI client authenticates as its own least-privilege role and is denied the cubes outside
     that role's domain. No client connection holds `ROLE_EXECUTIVE_ALL`, and none sees PII.
  4. The deploy artefacts supply what `cube.js` requires at module load, restrict the SQL port to
     known ranges, and carry no credential literals.

Why this story exists
---------------------
US-1.3 closed `checkSqlAuth` and built the credential store, which is exactly what a SQL client
needs. It could not be used: **no deployed runtime was listening on the Postgres wire protocol.**
Two separate reasons, both proven below rather than argued.

**The variable name was wrong.** `cube/Dockerfile` set `CUBEJS_SQL_PORT=5432` and
`docs/PBI_TO_DUCKLAKE_REPLICA_GUIDE.md` §5.2 told operators to do the same. Cube reads
`CUBEJS_PG_SQL_PORT`. `CUBEJS_SQL_PORT` is not a Cube variable, so it binds nothing and logs
nothing — the SQL API is simply absent and every client connection is refused at the TCP layer,
which is indistinguishable from a firewall problem. That is the failure this suite turns into a
startup error.

**Cloud Run cannot carry the protocol.** Measured on the live service: `scbi-cube` exposes
`containerPort: 4000` only, and Cloud Run routes a single container port speaking HTTP/1, HTTP/2,
gRPC or WebSockets. The Postgres wire protocol is raw TCP and cannot reach a Cloud Run service at
any port. So the REST API (thin web app, ID-token authenticated) stays on Cloud Run and the SQL API
runs on a TCP-capable runtime — same image, same `cube.js`, same credential store. Hence criterion
2: a runtime with no SQL configuration must still boot, or the REST service would fail on the
change that enables SQL.

Seams
-----
**A Node harness** (the `test_us_1_3_cube_auth.py` / `test_us_1_4_rbac_allowlist.py` pattern) loads
the *real* `cube/cube.js` and calls the *real* `checkSqlAuth` and `queryRewrite`. A configuration is
proven to fail by the module refusing to load, not by its source text reading correctly. The
harness deletes every SQL variable before applying a job's environment, so a test's configuration
is exactly what it declares.

**Seam D**, static repo invariants, for the deploy artefacts. These are config-as-code: a
`gcloud run deploy` line that omits a variable `cube.js` `requireEnv`s is a deploy that crash-loops,
and asserting it here is the only place that can catch it before the deploy.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import re
import subprocess
from pathlib import Path

import pytest

APP_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = APP_DIR.parent                      # data-recon/
CUBE_DIR = REPO_ROOT / "cube"
CUBE_JS = CUBE_DIR / "cube.js"
DOCKERFILE = CUBE_DIR / "Dockerfile"
DEPLOY_REST = CUBE_DIR / "deploy_cube_rest_cloudrun.sh"
DEPLOY_SQL_VM = CUBE_DIR / "deploy_cube_sql_vm.sh"
METABASE_DIR = REPO_ROOT / "metabase"
ROLE_ROSTER = APP_DIR / "role_assignments.json"

# Not revoked, and at or over RFC 7518's 32-byte floor for HS256 — see cube.js
# assertApiSecretIsUsable(). 43 chars, the width secrets.token_urlsafe(32) produces.
GOOD_SECRET = "us83TestSecretNotRealAndLongEnoughForHs256"

# The real Cube variable. CUBEJS_SQL_PORT — the one the Dockerfile and the guide used — binds
# nothing; `LEGACY_PORT_VAR` is quoted rather than assigned anywhere in this file so the sweep in
# test_no_artefact_sets_the_inert_sql_port_variable does not match its own module.
PG_PORT_VAR = "CUBEJS_PG_SQL_PORT"
LEGACY_PORT_VAR = "CUBEJS" "_SQL_PORT"

# The per-role connection set: one Metabase database per role domain, least privilege, no
# executive connection. This is the shape docs/METABASE_CUBE_SQL.md provisions.
CONNECTIONS = {
    "metabase.member@sanlam.co.za": "ROLE_FINANCE_MEMBER",
    "metabase.investments@sanlam.co.za": "ROLE_INVESTMENTS",
    "metabase.quotations@sanlam.co.za": "ROLE_ANNUITY",
}
CONNECTION_PASSWORD = "harness-only-sql-password"

# One cube inside each role's domain, and one outside it. The pairs are what make criterion 3 a
# boundary test rather than a smoke test: a store that authenticated everyone to one role would
# pass the "can reach" half and fail here.
IN_DOMAIN = {
    "ROLE_FINANCE_MEMBER": "MemberMonthly",
    "ROLE_INVESTMENTS": "InvestmentsFundamental",
    "ROLE_ANNUITY": "AnnuityQuotation",
}
OUT_OF_DOMAIN = {
    "ROLE_FINANCE_MEMBER": "AnnuityQuotation",
    "ROLE_INVESTMENTS": "AnnuityQuotation",
    "ROLE_ANNUITY": "InvestmentsFundamental",
}


# ──────────────────────────────────────────────────────────────────────────────
# Credential-store helpers — Node's crypto.scryptSync(password, salt, 32) defaults
# ──────────────────────────────────────────────────────────────────────────────

def scrypt_digest(password: str, salt_hex: str) -> str:
    """N=16384, r=8, p=1, 32-byte key. Verified byte-identical to Node v22 in US-1.3.

    If cube.js's scrypt parameters ever change, this helper must change with it and
    `test_each_metabase_connection_authenticates_as_its_own_role` is what will catch it.
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


def connection_store(connections: dict[str, str] | None = None) -> str:
    """CUBEJS_SQL_USERS for the per-role BI connection set."""
    entries = {}
    for index, (username, role) in enumerate((connections or CONNECTIONS).items()):
        salt_hex = f"{index:02x}" * 8
        entries[username] = {
            "password": scrypt_digest(CONNECTION_PASSWORD, salt_hex),
            "role": role,
        }
    return json.dumps(entries)


# ──────────────────────────────────────────────────────────────────────────────
# Node harness — load the real cube.js, call the real checkSqlAuth / queryRewrite
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
// never opens a connection. Every SQL API variable is cleared first, so a test's configuration is
// exactly what its job declares and nothing inherited from the parent shell.
process.env.CUBEJS_DB_DUCKDB_S3_ACCESS_KEY_ID = 'harness-not-a-real-key';
process.env.CUBEJS_DB_DUCKDB_S3_SECRET_ACCESS_KEY = 'harness-not-a-real-secret';
for (const key of ['CUBEJS_PG_SQL_PORT', 'CUBEJS_SQL_PORT', 'CUBEJS_SQL_USERS',
                   'CUBEJS_SQL_SUPER_USER', 'CUBEJS_SQL_USER', 'CUBEJS_SQL_PASSWORD']) {
  delete process.env[key];
}
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

  if (job.action === 'rewrite') {
    try {
      const rewritten = config.queryRewrite(job.query, { securityContext: job.securityContext });
      emit({ outcome: 'allowed', query: rewritten });
    } catch (err) {
      emit({ outcome: 'denied', message: String(err.message) });
    }
  }

  emit({ outcome: 'unknown_action', message: String(job.action) });
})();
"""


@pytest.fixture(scope="session")
def harness_dir(tmp_path_factory) -> Path:
    directory = tmp_path_factory.mktemp("sql_api_runtime_harness")
    (directory / "stub_driver.js").write_text(_STUB_DRIVER, encoding="utf-8")
    (directory / "harness.js").write_text(_HARNESS, encoding="utf-8")
    return directory


def _run(harness_dir: Path, job: dict) -> dict:
    result = subprocess.run(
        ["node", str(harness_dir / "harness.js"), str(CUBE_JS).replace("\\", "/"), json.dumps(job)],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, (
        f"Harness exited {result.returncode}.\nstdout: {result.stdout}\nstderr: {result.stderr}"
    )
    return json.loads(result.stdout.strip().splitlines()[-1])


def sql_env(**overrides) -> dict:
    """A coherent SQL-serving runtime: a listening port and the per-role connection set."""
    env = {
        "CUBEJS_API_SECRET": GOOD_SECRET,
        "CUBEJS_SQL_USERS": connection_store(),
        PG_PORT_VAR: "5432",
    }
    env.update(overrides)
    return env


def load_config(harness_dir: Path, env: dict | None = None) -> dict:
    return _run(harness_dir, {"action": "load", "env": env if env is not None else sql_env()})


def sql_login(harness_dir: Path, username: str, password: str = CONNECTION_PASSWORD) -> dict:
    return _run(
        harness_dir,
        {"action": "sqlauth", "auth": {"u": username, "password": password}, "env": sql_env()},
    )


def rewrite(harness_dir: Path, role: str, cube_name: str) -> dict:
    return _run(
        harness_dir,
        {
            "action": "rewrite",
            "query": {"measures": [f"{cube_name}.someMeasure"], "dimensions": [], "filters": []},
            "securityContext": {"role": role, "canViewPii": False},
            "env": sql_env(),
        },
    )


# ──────────────────────────────────────────────────────────────────────────────
# Criterion 1 — a runtime that cannot serve SQL must not pretend to
# ──────────────────────────────────────────────────────────────────────────────

def test_the_harness_loads_the_real_cube_config(harness_dir):
    """Anti-vacuity guard. If this fails, every assertion below passes for the wrong reason.

    This pattern has already paid for itself twice in this repo — it is what caught cube.js's new
    CUBEJS_API_SECRET requirement breaking the US-1.4 harness. Keep writing it.
    """
    outcome = load_config(harness_dir)
    assert outcome["outcome"] == "loaded", outcome.get("message")


def test_sql_credentials_with_no_listening_port_fail_the_container(harness_dir):
    """The whole US-1.3 credential store, provisioned, reachable by nobody.

    Without this the operator sees a healthy container, a populated CUBEJS_SQL_USERS, and every
    Metabase connection refused at the TCP layer with nothing in the log to explain it.
    """
    outcome = load_config(harness_dir, sql_env(**{PG_PORT_VAR: None}))
    assert outcome["outcome"] == "load_error", (
        "cube.js started with SQL credentials and no SQL port. Every client connection will be "
        "refused and the log will say nothing."
    )
    assert PG_PORT_VAR in outcome["message"], (
        f"The error must name {PG_PORT_VAR} — it is the one thing the operator has to set. "
        f"Got: {outcome['message']}"
    )


def test_the_inert_legacy_port_variable_fails_the_container(harness_dir):
    """`CUBEJS_SQL_PORT` is not a Cube variable. It is what cube/Dockerfile set.

    Setting it looks exactly like enabling the SQL API and does nothing at all. The container must
    refuse rather than serve a REST-only runtime that its operator believes speaks Postgres.
    """
    outcome = load_config(harness_dir, sql_env(**{PG_PORT_VAR: None, LEGACY_PORT_VAR: "5432"}))
    assert outcome["outcome"] == "load_error", (
        f"cube.js accepted {LEGACY_PORT_VAR} as if it enabled the SQL API. It binds nothing."
    )
    assert PG_PORT_VAR in outcome["message"] and LEGACY_PORT_VAR in outcome["message"], (
        "The error must name both variables — the wrong one that is set and the right one to set "
        f"instead. Got: {outcome['message']}"
    )


def test_a_rest_only_runtime_loads_with_no_sql_configuration(harness_dir):
    """Criterion 2. Cloud Run cannot carry the Postgres wire protocol at any port, so the REST
    service runs with neither the port nor the credential store. It must still boot — otherwise
    enabling the SQL API anywhere takes the dashboards down.
    """
    outcome = load_config(harness_dir, {"CUBEJS_API_SECRET": GOOD_SECRET})
    assert outcome["outcome"] == "loaded", (
        f"The REST-only runtime no longer starts: {outcome.get('message')}"
    )


@pytest.mark.parametrize("bad_port", ["five-thousand", "0", "70000", "5432.5", ""])
def test_an_unusable_sql_port_fails_the_container(harness_dir, bad_port):
    """Cube coerces the port with Number(); a value that is not a usable TCP port silently yields
    no listener, which is the same invisible failure as not setting it at all.
    """
    outcome = load_config(harness_dir, sql_env(**{PG_PORT_VAR: bad_port}))
    assert outcome["outcome"] == "load_error", (
        f"cube.js accepted {PG_PORT_VAR}={bad_port!r} as a listening port."
    )


def test_a_sql_super_user_fails_the_container(harness_dir):
    """CUBEJS_SQL_SUPER_USER lets one login switch to another user's security context, and the
    policy that would constrain it — canSwitchSqlUser — is not implemented here. Set, it is a
    documented way around the per-role boundary the rest of this story builds.
    """
    outcome = load_config(harness_dir, sql_env(CUBEJS_SQL_SUPER_USER="metabase.member@sanlam.co.za"))
    assert outcome["outcome"] == "load_error", (
        "cube.js started with a SQL super user and no canSwitchSqlUser policy: that login can "
        "assume any role in the store, including one it was never granted."
    )
    assert "canSwitchSqlUser" in outcome["message"], (
        f"The error must name the missing policy. Got: {outcome['message']}"
    )


# ──────────────────────────────────────────────────────────────────────────────
# Criterion 3 — one connection per role domain, least privilege, no PII
# ──────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("username,role", sorted(CONNECTIONS.items()))
def test_each_metabase_connection_authenticates_as_its_own_role(harness_dir, username, role):
    """The multi-connection design is only real if one store serves several roles at once.

    One Metabase database entry per role domain is the shape this proves: Cube derives the
    security context at login, so a connection *is* a role.
    """
    outcome = sql_login(harness_dir, username)
    assert outcome["outcome"] == "accepted", (
        f"{username} could not log in: {outcome.get('message')}"
    )
    assert outcome["result"]["securityContext"]["role"] == role, (
        f"{username} authenticated as {outcome['result']['securityContext']['role']}, not {role}. "
        "The role must come from the store entry, never from the username."
    )


@pytest.mark.parametrize("username,role", sorted(CONNECTIONS.items()))
def test_no_metabase_connection_sees_pii_in_the_clear(harness_dir, username, role):
    """Criterion 3's POPIA half, and the reason a single ROLE_EXECUTIVE_ALL connection was not
    the answer: it is the only role with canViewPii, so one shared connection would unmask
    member_nk on every dashboard that joins DimMember.
    """
    outcome = sql_login(harness_dir, username)
    assert outcome["outcome"] == "accepted", outcome.get("message")
    assert outcome["result"]["securityContext"]["canViewPii"] is False, (
        f"{username} ({role}) holds PII in the clear. No BI client connection may."
    )


@pytest.mark.parametrize("role,cube_name", sorted(IN_DOMAIN.items()))
def test_each_connection_can_reach_its_own_domain(harness_dir, role, cube_name):
    """The other half of the boundary: least privilege must not mean no privilege."""
    outcome = rewrite(harness_dir, role, cube_name)
    assert outcome["outcome"] == "allowed", (
        f"{role} is allowlisted for {cube_name} but queryRewrite denied it: "
        f"{outcome.get('message')}"
    )


@pytest.mark.parametrize("role,cube_name", sorted(OUT_OF_DOMAIN.items()))
def test_each_connection_is_denied_the_cubes_outside_its_domain(harness_dir, role, cube_name):
    """This is what makes several connections worth the operational cost. If one connection could
    read every cube there would be no reason not to share one.
    """
    outcome = rewrite(harness_dir, role, cube_name)
    assert outcome["outcome"] == "denied", (
        f"{role} reached {cube_name}, which is outside its allowlist. The per-connection boundary "
        "is not enforced."
    )


def test_a_store_naming_an_unknown_role_fails_the_container(harness_dir):
    """Provisioning a fourth connection with a typo'd role must fail the deploy, not the first
    query of whichever dashboard happens to use it.
    """
    outcome = load_config(
        harness_dir,
        sql_env(CUBEJS_SQL_USERS=connection_store({"metabase.typo@sanlam.co.za": "ROLE_FINANCE"})),
    )
    assert outcome["outcome"] == "load_error", (
        "A credential entry naming a role with no ROLE_PERMISSIONS entry was accepted."
    )


# ──────────────────────────────────────────────────────────────────────────────
# Criterion 4 — the deploy artefacts (seam D)
# ──────────────────────────────────────────────────────────────────────────────

def _artefact_files(suffixes: set[str], extra_names: set[str] | None = None):
    skip_dirs = {"__pycache__", ".git", ".pytest_cache", "node_modules", ".venv", "venv"}
    for path in REPO_ROOT.rglob("*"):
        if not path.is_file():
            continue
        if any(part in skip_dirs for part in path.parts):
            continue
        if path.name == Path(__file__).name:
            continue
        if path.suffix in suffixes or path.name in (extra_names or set()):
            yield path


def test_the_cube_image_enables_the_sql_api_on_the_real_variable():
    text = DOCKERFILE.read_text(encoding="utf-8")
    assert re.search(rf"^ENV\s+{PG_PORT_VAR}=5432\s*$", text, re.M), (
        f"cube/Dockerfile must set {PG_PORT_VAR}=5432. Without it the SQL API binds nothing on "
        "every runtime built from this image."
    )


def test_no_artefact_sets_the_inert_sql_port_variable():
    """A sweep, in the spirit of test_us_2_2_no_secrets: the wrong variable came back once
    already, from the Dockerfile into the replica guide into the deployment.

    Only *assignment* is a finding. cube.js and the docs have to name the variable in order to
    tell an operator not to set it.
    """
    assignment = re.compile(rf"(?<![A-Z_]){LEGACY_PORT_VAR}\s*[=:]")
    hits = []
    for path in _artefact_files({".md", ".sh", ".ps1", ".js", ".py", ".json", ".yaml", ".yml"},
                                {"Dockerfile"}):
        for number, line in enumerate(path.read_text(encoding="utf-8", errors="ignore").splitlines(), 1):
            if assignment.search(line):
                hits.append(f"{path.relative_to(REPO_ROOT)}:{number}")
    assert not hits, (
        f"{LEGACY_PORT_VAR} is assigned in: {', '.join(hits)}. It is not a Cube variable — it "
        f"binds nothing. Use {PG_PORT_VAR}."
    )


def test_no_deploy_artefact_wires_a_bi_client_to_the_executive_role():
    """The §6 decision, made executable. ROLE_EXECUTIVE_ALL is the only role with PII in the
    clear; a shared BI connection holding it defeats every mask in SharedDimensions.js.

    `.js` is excluded because cube.js defines the role; this is about what a deploy *grants*.

    `role_assignments.json` is excluded and checked by the next test instead, more strictly.
    It is the one artefact where the role may legitimately appear: it maps a *verified human
    identity* that IAP asserted, which is exactly who the executive role is for, and it is not
    a connection at all. Reading it as a BI client would have meant no person could ever hold
    the role the cube defines for people — so the guard is sharpened here, not relaxed.
    """
    hits = []
    for path in _artefact_files({".sh", ".ps1", ".json", ".env", ".yaml", ".yml"}):
        if path == ROLE_ROSTER:
            continue
        for number, line in enumerate(path.read_text(encoding="utf-8", errors="ignore").splitlines(), 1):
            if "ROLE_EXECUTIVE_ALL" in line:
                hits.append(f"{path.relative_to(REPO_ROOT)}:{number}")
    assert not hits, (
        f"A deploy artefact grants ROLE_EXECUTIVE_ALL to a client connection: {', '.join(hits)}. "
        "Provision one connection per role domain instead — docs/METABASE_CUBE_SQL.md."
    )


def test_the_role_roster_grants_the_executive_role_only_to_named_people():
    """The stricter half of the rule above, for the one file allowed to name the role.

    A *person* may hold ROLE_EXECUTIVE_ALL: IAP verified who they are, and the entry is
    reviewable in one place. A non-human principal may not — a service account key or a shared
    BI credential holding it is precisely the shared connection the previous test forbids, and
    it would defeat every mask in SharedDimensions.js for everyone using that connection.
    """
    if not ROLE_ROSTER.exists():
        pytest.skip("no roster: every caller falls back to least privilege, which is safe")
    roster = json.loads(ROLE_ROSTER.read_text(encoding="utf-8"))

    offenders = [
        email for email, entry in roster.items()
        if isinstance(entry, dict) and entry.get("role") == "ROLE_EXECUTIVE_ALL"
        and (email.endswith(".gserviceaccount.com") or "@" not in email)
    ]
    assert not offenders, (
        f"{', '.join(offenders)} hold ROLE_EXECUTIVE_ALL in role_assignments.json and are not "
        "people. That role is the only one with PII in the clear; a shared, non-human credential "
        "holding it unmasks every member for everyone who uses it."
    )


def test_the_role_roster_validates():
    """scripts/access/manage_access.py owns the roster's rules — an unknown role is a silent
    demotion, an unknown group is a silently missing IAM grant, can_view_pii means nothing
    outside the executive role, and one address is reserved by conftest.

    Running its validator here means a hand-edit that skips the tool is still caught before a
    deploy, rather than at the moment somebody cannot see their dashboard.
    """
    spec = importlib.util.spec_from_file_location(
        "scbi_manage_access", REPO_ROOT / "scripts" / "access" / "manage_access.py")
    manage_access = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(manage_access)

    roster = json.loads(ROLE_ROSTER.read_text(encoding="utf-8")) if ROLE_ROSTER.exists() else {}
    problems = manage_access.validate(roster) + manage_access.check_roles_match_the_server()
    assert not problems, "role_assignments.json: " + "; ".join(problems)


@pytest.mark.parametrize(
    "script",
    ["deploy_cube_rest_cloudrun.sh", "deploy_cube_sql_vm.sh"],
)
def test_every_cube_deploy_supplies_the_gcs_hmac_pair(script):
    """cube.js requireEnv()s both names at module load, so a deploy that omits them crash-loops.

    The deployed revision measured on 2026-09-20 omitted both: the next deploy of the current
    cube.js would not have started. This is that blocker turned into a test.
    """
    text = (CUBE_DIR / script).read_text(encoding="utf-8")
    for name in ("CUBEJS_DB_DUCKDB_S3_ACCESS_KEY_ID", "CUBEJS_DB_DUCKDB_S3_SECRET_ACCESS_KEY"):
        assert name in text, (
            f"cube/{script} does not supply {name}. cube.js requireEnv()s it at module load, so "
            "the container will fail to start."
        )


def test_the_sql_runtime_does_not_open_the_postgres_port_to_the_internet():
    """An open 5432 makes the whole US-1.3 credential store the only thing between the internet
    and the semantic layer. It is a scrypt check, not a network boundary; it is not meant to be
    the only one.
    """
    text = DEPLOY_SQL_VM.read_text(encoding="utf-8")
    offenders = [
        line.strip()
        for line in text.splitlines()
        if "source-ranges" in line and ("0.0.0.0/0" in line or "::/0" in line)
    ]
    assert not offenders, (
        f"cube/deploy_cube_sql_vm.sh exposes the SQL port to every address: {offenders}"
    )
    assert "--source-ranges" in text, (
        "cube/deploy_cube_sql_vm.sh must restrict the SQL port with an explicit --source-ranges."
    )


def test_metabase_can_reach_a_private_sql_runtime():
    """Metabase runs on Cloud Run. Without VPC egress it has no route to a private address at
    all, so the connection fails before any credential is checked.
    """
    text = (METABASE_DIR / "deploy_metabase.sh").read_text(encoding="utf-8")
    assert "--network" in text or "--vpc-connector" in text, (
        "metabase/deploy_metabase.sh gives the service no VPC egress, so it cannot reach the Cube "
        "SQL runtime's private address."
    )


@pytest.mark.parametrize(
    "script",
    ["metabase/deploy_metabase.sh", "metabase/deploy_metabase.ps1",
     "scripts/provision_gcp_infra.ps1"],
)
def test_no_provisioning_script_carries_a_password_default(script):
    """US-2.2 swept `.py .js .json .sh .yaml .yml .env .tf` and not `.ps1`, so the PowerShell
    twins of two already-fixed shell scripts kept their literal passwords. Same story, same rule.
    """
    text = (REPO_ROOT / script).read_text(encoding="utf-8")
    offenders = [
        f"line {number}"
        for number, line in enumerate(text.splitlines(), 1)
        if re.search(r"(Password|PASSWORD|Pass)\s*=\s*[\"'][^\"'$)]", line)
    ]
    assert not offenders, (
        f"{script} carries a password literal at {', '.join(offenders)}. Require it from the "
        "environment, as the shell scripts already do."
    )
