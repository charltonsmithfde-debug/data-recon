"""US-1.4 — Close the RBAC allowlist gap.

Acceptance criteria (PRD_ARCHITECTURE_REALIGNMENT.md, EPIC 1):
  1. Every name in ROLE_PERMISSIONS[*].allowedCubes resolves to a defined cube, or is removed.
  2. A startup assertion fails the container if an allowlisted cube is undefined.
  3. SHARED_DIMENSIONS is reviewed: DimMember is removed from the unconditional whitelist,
     since it carries PII and currently bypasses the cube-boundary check for every role.

Two seams are used here.

**Seam D (static)** parses `cube/cube.js` and `cube/model/cubes/*.js` off disk. That proves the
allowlists *say* the right thing.

**A Node harness** is the part that matters. It loads the real `cube.js` and calls the real
`queryRewrite` with a stubbed DuckDB driver, so the tests prove the boundary actually *denies*,
not merely that the source text looks correct. This repo has been burned twice by checks that
read the right thing and proved nothing — the `dbType` version check that gave a false green
(ledger 2026-09-20, US-3.0) and the "known flake" that was an unread pipe (EXECUTION_PLAN §2).
A regex over `cube.js` would be a third. `cube/node_modules` does not exist, so the harness
stubs `@cubejs-backend/duckdb-driver` via `Module._resolveFilename` rather than installing it.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
CUBE_DIR = REPO_ROOT / "cube"
CUBE_JS = CUBE_DIR / "cube.js"
MODEL_DIR = CUBE_DIR / "model" / "cubes"

# Roles that legitimately need member demographics. DimMember stops being a free-for-all
# shared dimension in this story; anything here must hold it by explicit grant instead.
DEMOGRAPHIC_ROLES = {"ROLE_EXECUTIVE_ALL", "ROLE_FINANCE_MEMBER"}


# ──────────────────────────────────────────────────────────────────────────────
# Seam D — parse what is on disk
# ──────────────────────────────────────────────────────────────────────────────

def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def defined_cubes() -> set[str]:
    """Every cube name actually declared in the model layer."""
    names: set[str] = set()
    for model_file in sorted(MODEL_DIR.glob("*.js")):
        names.update(re.findall(r"^cube\(\s*'([^']+)'", _read(model_file), re.MULTILINE))
    return names


def _role_permissions_block() -> str:
    source = _read(CUBE_JS)
    match = re.search(r"const ROLE_PERMISSIONS = \{(.*?)\n\};", source, re.DOTALL)
    assert match, "ROLE_PERMISSIONS is no longer a top-level const in cube.js."
    return match.group(1)


def role_allowlists() -> dict[str, list[str]]:
    """{role: [allowlisted cube names]} exactly as cube.js declares them."""
    block = _role_permissions_block()
    allowlists: dict[str, list[str]] = {}
    for role_match in re.finditer(
        r"(ROLE_[A-Z_]+):\s*\{(.*?)\n  \}", block, re.DOTALL
    ):
        role, body = role_match.group(1), role_match.group(2)
        cubes_match = re.search(r"allowedCubes:\s*\[(.*?)\]", body, re.DOTALL)
        assert cubes_match, f"{role} has no allowedCubes array."
        allowlists[role] = re.findall(r"'([^']+)'", cubes_match.group(1))
    assert allowlists, "No roles parsed out of ROLE_PERMISSIONS."
    return allowlists


def shared_dimensions() -> list[str]:
    source = _read(CUBE_JS)
    match = re.search(r"const SHARED_DIMENSIONS = \[(.*?)\];", source, re.DOTALL)
    assert match, "SHARED_DIMENSIONS is no longer declared as an array in cube.js."
    return re.findall(r"'([^']+)'", match.group(1))


def test_every_allowlisted_cube_is_defined():
    """Criterion 1. The gap this story exists to close."""
    defined = defined_cubes()
    orphans = {
        role: [c for c in cubes if c != "*" and c not in defined]
        for role, cubes in role_allowlists().items()
    }
    orphans = {role: missing for role, missing in orphans.items() if missing}
    assert not orphans, (
        "These allowlisted cube names do not resolve to any cube in model/cubes/: "
        f"{json.dumps(orphans, indent=2)}\n"
        "Permissions that name cubes which do not exist do not describe reality."
    )


def test_shared_dimensions_all_resolve_to_defined_cubes():
    """A typo in SHARED_DIMENSIONS silently grants nothing; an unnoticed one is still a lie."""
    defined = defined_cubes()
    missing = [name for name in shared_dimensions() if name not in defined]
    assert not missing, f"SHARED_DIMENSIONS names undefined cubes: {missing}"


def test_dim_member_is_not_an_unconditional_shared_dimension():
    """Criterion 3. DimMember carries PII and must be governed by the allowlist."""
    assert "DimMember" not in shared_dimensions(), (
        "DimMember is still in SHARED_DIMENSIONS, so the cube-boundary check is skipped for "
        "it on every role. It exposes memberNk, memberGender, memberMaritalStatus, "
        "memberAgeBand and currentAge."
    )


def test_roles_that_need_demographics_hold_dim_member_explicitly():
    """Removing DimMember from the bypass must not silently break the demographic dashboards.

    US-6.1 reads gender and age-band breakdowns, and every verified caller currently falls back
    to ROLE_FINANCE_MEMBER, so that role must still reach DimMember -- by grant, not by bypass.
    """
    allowlists = role_allowlists()
    for role in DEMOGRAPHIC_ROLES:
        cubes = allowlists[role]
        assert "DimMember" in cubes or "*" in cubes, (
            f"{role} lost DimMember access entirely. It was removed from SHARED_DIMENSIONS "
            "without being granted explicitly, which breaks the US-6.1 demographic cards."
        )


def test_roles_without_a_demographic_need_cannot_reach_dim_member():
    allowlists = role_allowlists()
    for role, cubes in allowlists.items():
        if role in DEMOGRAPHIC_ROLES:
            continue
        assert "DimMember" not in cubes and "*" not in cubes, (
            f"{role} has no demographic remit but can query DimMember."
        )


# ──────────────────────────────────────────────────────────────────────────────
# Node harness — load the real cube.js and exercise the real queryRewrite
# ──────────────────────────────────────────────────────────────────────────────

_STUB_DRIVER = "class DuckDBDriver { constructor(options) { this.options = options; } }\n" \
               "module.exports = { DuckDBDriver };\n"

# Patches module resolution so the real cube.js can be required with no node_modules present,
# then runs one job against the config it exports.
_HARNESS = """
const path = require('path');
const Module = require('module');

const stub = path.resolve(__dirname, 'stub_driver.js');
const originalResolve = Module._resolveFilename;
Module._resolveFilename = function (request, ...rest) {
  if (request === '@cubejs-backend/duckdb-driver') return stub;
  return originalResolve.call(this, request, ...rest);
};

// cube.js calls requireEnv() at module load (US-2.2). These are placeholders: the harness never
// opens a connection, it only calls queryRewrite.
process.env.CUBEJS_DB_DUCKDB_S3_ACCESS_KEY_ID = 'harness-not-a-real-key';
process.env.CUBEJS_DB_DUCKDB_S3_SECRET_ACCESS_KEY = 'harness-not-a-real-secret';
// US-1.3 added CUBEJS_API_SECRET to that set, and vets it: at or over 32 bytes (RFC 7518 s3.2)
// and not on cube.js's revocation list. `test_us_1_3_cube_auth.py` owns those rules; here the
// value only has to satisfy them. Without it every assertion in this module would fail on a
// load_error -- which is exactly what test_harness_loads_the_real_cube_config reported when
// US-1.3 landed, rather than the denial tests passing vacuously.
process.env.CUBEJS_API_SECRET = 'us14HarnessSecretNotRealButLongEnoughx';

const job = JSON.parse(process.argv[3]);

let config;
try {
  config = require(process.argv[2]);
} catch (err) {
  console.log(JSON.stringify({ outcome: 'load_error', message: String(err.message) }));
  process.exit(0);
}

if (job.action === 'load') {
  console.log(JSON.stringify({ outcome: 'loaded' }));
  process.exit(0);
}

try {
  const rewritten = config.queryRewrite(job.query, { securityContext: job.securityContext });
  console.log(JSON.stringify({ outcome: 'allowed', query: rewritten }));
} catch (err) {
  console.log(JSON.stringify({ outcome: 'denied', message: String(err.message) }));
}
"""


@pytest.fixture(scope="session")
def harness_dir(tmp_path_factory) -> Path:
    directory = tmp_path_factory.mktemp("cube_harness")
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


def rewrite(harness_dir: Path, role: str, members: list[str]) -> dict:
    """Ask the real queryRewrite whether `role` may query the given `Cube.field` members."""
    return _run(
        harness_dir,
        CUBE_JS,
        {
            "action": "rewrite",
            "query": {"dimensions": members},
            "securityContext": {"role": role, "canViewPii": role == "ROLE_EXECUTIVE_ALL"},
        },
    )


def test_harness_loads_the_real_cube_config(harness_dir):
    """If this fails, every behavioural assertion below is vacuous rather than passing."""
    assert _run(harness_dir, CUBE_JS, {"action": "load"})["outcome"] == "loaded"


def test_each_role_can_query_every_cube_on_its_own_allowlist(harness_dir):
    """The PRD's verification: enumerate allowlisted cubes per role; all succeed."""
    for role, cubes in role_allowlists().items():
        for cube_name in cubes:
            if cube_name == "*":
                continue
            outcome = rewrite(harness_dir, role, [f"{cube_name}.someField"])
            assert outcome["outcome"] == "allowed", (
                f"{role} is allowlisted for {cube_name} but queryRewrite denied it: "
                f"{outcome.get('message')}"
            )


def test_each_role_is_denied_every_cube_off_its_allowlist(harness_dir):
    """The PRD's verification: for each non-allowlisted cube, assert AccessDenied."""
    defined = defined_cubes()
    shared = set(shared_dimensions())
    for role, cubes in role_allowlists().items():
        if "*" in cubes:
            continue
        for cube_name in sorted(defined - set(cubes) - shared):
            outcome = rewrite(harness_dir, role, [f"{cube_name}.someField"])
            assert outcome["outcome"] == "denied", (
                f"{role} is not allowlisted for {cube_name} but queryRewrite allowed it."
            )
            assert "AccessDenied" in outcome["message"]


def test_dim_member_is_denied_to_a_role_without_a_demographic_remit(harness_dir):
    """Criterion 3, proven by enforcement rather than by reading the constant."""
    outcome = rewrite(harness_dir, "ROLE_ANNUITY", ["DimMember.memberGender"])
    assert outcome["outcome"] == "denied", (
        "ROLE_ANNUITY reached DimMember. The PII bypass is still open."
    )
    assert "AccessDenied" in outcome["message"]


def test_dim_member_is_still_reachable_by_the_default_role(harness_dir):
    """The least-privileged role every verified caller falls back to still drives US-6.1."""
    outcome = rewrite(harness_dir, "ROLE_FINANCE_MEMBER", ["DimMember.memberGender"])
    assert outcome["outcome"] == "allowed", (
        f"ROLE_FINANCE_MEMBER can no longer read demographics: {outcome.get('message')}"
    )


def test_an_unknown_role_is_rejected_outright(harness_dir):
    outcome = rewrite(harness_dir, "ROLE_DOES_NOT_EXIST", ["MemberMonthly.someField"])
    assert outcome["outcome"] == "denied"
    assert "Unauthorized" in outcome["message"]


def test_a_query_naming_no_cube_is_not_a_way_past_the_boundary(harness_dir):
    """Bare members carry no `Cube.` prefix, so extractCubeName returns null for them."""
    outcome = rewrite(harness_dir, "ROLE_ANNUITY", ["bareMemberWithNoCubePrefix"])
    assert outcome["outcome"] == "allowed", "A prefix-less member should simply match no cube."


# ──────────────────────────────────────────────────────────────────────────────
# Criterion 2 — the startup assertion
# ──────────────────────────────────────────────────────────────────────────────

def _cube_dir_copy(tmp_path: Path) -> Path:
    """A writable copy of cube.js beside a copy of the model layer it validates against."""
    copied = tmp_path / "cube"
    copied.mkdir()
    shutil.copy2(CUBE_JS, copied / "cube.js")
    shutil.copytree(MODEL_DIR, copied / "model" / "cubes")
    return copied


def test_startup_fails_when_an_allowlisted_cube_is_undefined(harness_dir, tmp_path):
    """Criterion 2. The guard must fail the container, not warn and carry on."""
    copied = _cube_dir_copy(tmp_path)
    config = copied / "cube.js"
    source = config.read_text(encoding="utf-8")
    patched = source.replace(
        "      'AnnuityQuotation'",
        "      'ACubeThatWasNeverDefined',\n      'AnnuityQuotation'",
        1,
    )
    assert patched != source, "Could not inject an undefined cube; the fixture needs updating."
    config.write_text(patched, encoding="utf-8")

    outcome = _run(harness_dir, config, {"action": "load"})
    assert outcome["outcome"] == "load_error", (
        "cube.js loaded cleanly with 'ACubeThatWasNeverDefined' on a role allowlist. "
        "Nothing fails the container when permissions name a cube that does not exist."
    )
    assert "ACubeThatWasNeverDefined" in outcome["message"], (
        f"Startup failed, but the message does not name the offender: {outcome['message']}"
    )


def test_startup_fails_when_a_shared_dimension_is_undefined(harness_dir, tmp_path):
    copied = _cube_dir_copy(tmp_path)
    config = copied / "cube.js"
    source = config.read_text(encoding="utf-8")
    patched = source.replace(
        "const SHARED_DIMENSIONS = [\n  'DimDate',",
        "const SHARED_DIMENSIONS = [\n  'DimTypo',\n  'DimDate',",
        1,
    )
    assert patched != source, "Could not inject an undefined shared dimension."
    config.write_text(patched, encoding="utf-8")

    outcome = _run(harness_dir, config, {"action": "load"})
    assert outcome["outcome"] == "load_error"
    assert "DimTypo" in outcome["message"]


def test_the_unmodified_config_still_loads(harness_dir, tmp_path):
    """Guards the two tests above: a copy that was *not* patched must load fine."""
    copied = _cube_dir_copy(tmp_path)
    assert _run(harness_dir, copied / "cube.js", {"action": "load"})["outcome"] == "loaded"
