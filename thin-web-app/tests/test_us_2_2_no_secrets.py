"""
US-2.2 -- Source all secrets from Secret Manager; no secret has an in-code default.

> As a Platform Engineer, I want runtime credentials injected at deploy time, so
> that no secret has an in-code default.

Seam: static repo invariant (D), plus one process-level check that a missing
variable actually stops the server.

PRD verification clause: "tests/test_no_secrets.py: a regex sweep for GOOG1,
AKIA, ScbiCubeSecret, ChangeMe, Prod2026! over data-recon/** returns zero hits."
This module is that sweep, named to the suite's test_us_* convention so pytest.ini
collects it.

Deliberately NOT asserted here, because they are GCP-side and cannot be proven
from the tree: that the three Secret Manager entries exist, and that Cloud Run
mounts them with --set-secrets. Those stay manual acceptance steps on US-2.2.

This module NEVER prints a matched line. A failure reports the pattern, the file
and the line number only -- enough to fix, nothing worth leaking into a log.
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest

APP_DIR = Path(__file__).resolve().parent.parent
SWEEP_ROOT = APP_DIR.parent              # data-recon/
SERVER_PY = APP_DIR / "server.py"
CUBE_JS = SWEEP_ROOT / "cube" / "cube.js"

# The PRD's five markers. Values are detection rules, not credentials.
PATTERNS = {
    "GOOG1": "GCS HMAC access key id",
    "AKIA": "AWS access key id",
    "ScbiCubeSecret": "Cube API signing secret",
    "ChangeMe": "placeholder password",
    "Prod2026!": "provisioning password",
}

# Runtime code and deploy config. Markdown is excluded on purpose: the PRD and
# this suite's notes name the markers in order to demand their removal, and a
# security document that cannot name what it is rotating is useless.
# ".ps1" was missing until US-8.3. Every PowerShell twin of an already-fixed shell script
# therefore kept its literal password -- deploy_metabase.ps1 and provision_gcp_infra.ps1 both
# did, for three weeks after their .sh counterparts were cleaned. A sweep is only worth what
# its suffix list covers, so the list is the thing to keep honest.
SWEEP_SUFFIXES = {".py", ".js", ".json", ".sh", ".ps1", ".yaml", ".yml", ".env", ".tf"}
SWEEP_EXTRA_NAMES = {"Dockerfile", "docker-compose.yml", "Procfile"}

SKIP_DIRS = {"__pycache__", ".git", ".pytest_cache", "node_modules", ".venv", "venv"}
SKIP_FILES = {Path(__file__).name}       # this module defines the patterns


def _sweep_files():
    for path in SWEEP_ROOT.rglob("*"):
        if not path.is_file():
            continue
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        if path.name in SKIP_FILES:
            continue
        if path.suffix in SWEEP_SUFFIXES or path.name in SWEEP_EXTRA_NAMES:
            yield path


def _hits(pattern):
    """Return [(relative_path, line_number)] -- never the line itself."""
    found = []
    for path in _sweep_files():
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if pattern not in text:
            continue
        for n, line in enumerate(text.splitlines(), 1):
            if pattern in line:
                found.append((path.relative_to(SWEEP_ROOT).as_posix(), n))
    return found


@pytest.mark.parametrize("pattern", sorted(PATTERNS))
def test_no_secret_literal_in_runtime_source(pattern):
    hits = _hits(pattern)
    where = ", ".join(f"{f}:{n}" for f, n in hits)
    assert not hits, (
        f"{len(hits)} in-code occurrence(s) of the {PATTERNS[pattern]} "
        f"({pattern!r}) under data-recon/: {where}. A copy of the tree grants "
        "this credential to whoever holds it."
    )


def test_sweep_actually_walks_the_tree():
    """A sweep that silently matches nothing would pass forever."""
    files = list(_sweep_files())
    assert len(files) >= 5, f"Sweep found only {len(files)} file(s); it is not walking data-recon/."
    names = {f.name for f in files}
    assert "server.py" in names and "cube.js" in names, (
        f"Sweep missed the two files most likely to hold secrets: found {sorted(names)[:10]}"
    )


def test_cube_secret_has_no_inline_fallback():
    src = SERVER_PY.read_text(encoding="utf-8")
    assert 'os.environ.get("CUBEJS_API_SECRET",' not in src, (
        "server.py supplies a default for CUBEJS_API_SECRET, so a deployment "
        "that forgets the variable silently signs with an in-code key instead "
        "of failing."
    )


def test_cube_js_sources_gcs_credentials_from_the_environment():
    src = CUBE_JS.read_text(encoding="utf-8")
    for name in ("GCS_ACCESS_KEY", "GCS_SECRET_KEY"):
        assert f"const {name} = '" not in src and f'const {name} = "' not in src, (
            f"cube.js assigns {name} from a string literal instead of the environment."
        )
        assert name in src and "process.env" in src, (
            f"cube.js no longer references {name} via the environment."
        )


def test_missing_cube_secret_stops_the_server():
    """The PRD's wording: 'a missing variable raises at startup'.

    A server that refuses to start exits at once; one that starts serves
    forever. So exhausting the wait IS the failure signal -- keep it short
    rather than paying a long timeout for the known-bad path.
    """
    env = {k: v for k, v in os.environ.items() if k != "CUBEJS_API_SECRET"}
    proc = subprocess.Popen(
        [sys.executable, str(SERVER_PY), "8099"],
        cwd=str(APP_DIR), env=env,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )
    try:
        try:
            returncode = proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            raise AssertionError(
                "server.py started with no CUBEJS_API_SECRET in the environment. "
                "It must refuse to run rather than fall back to an in-code key."
            )
        output = proc.stdout.read()
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()

    assert returncode != 0, (
        "server.py exited cleanly with no CUBEJS_API_SECRET in the environment. "
        "It must refuse to run rather than fall back to an in-code key."
    )
    assert "CUBEJS_API_SECRET" in output.upper(), (
        "server.py failed without naming the missing variable, so the operator "
        "cannot tell what to set."
    )
