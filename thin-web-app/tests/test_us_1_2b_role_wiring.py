"""
US-1.2 (cycle 4) -- Every handler takes its role from resolve_identity(), not the request.

> As a Security Officer, I want the user's role resolved server-side from their
> verified identity, so that a user cannot escalate by editing a URL.

Cycle 3 built the resolution seam and exposed it at GET /api/identity. That alone
changes nothing: the analytical handlers still read `?role=` and `?maskPii=` off
the query string (and off the POST body), defaulting to ROLE_EXECUTIVE_ALL with
PII visible. The hole is only closed once every one of those call sites is gone.

Seams: static repo invariant (D) for "the pattern no longer exists anywhere", and
the thin-web-app HTTP API (A) for "an escalation attempt against a real analytical
endpoint changes nothing".

The member endpoint is the HTTP probe because it is the one analytical handler
that answers without Cube credentials (it is synthetic -- see US-6.0).
"""

from pathlib import Path

import pytest

APP_DIR = Path(__file__).resolve().parent.parent
SERVER_SRC = (APP_DIR / "server.py").read_text(encoding="utf-8")
APP_JS_SRC = (APP_DIR / "app.js").read_text(encoding="utf-8")

LEAST_PRIVILEGED_ROLE = "ROLE_FINANCE_MEMBER"
MEMBER_ENDPOINT = "/api/member_analysis/query"

REQUEST_DERIVED_PATTERNS = [
    'query.get("role"',
    'data.get("role"',
    'query.get("maskPii"',
    'data.get("maskPii"',
]


@pytest.mark.parametrize("pattern", REQUEST_DERIVED_PATTERNS)
def test_no_handler_reads_privilege_off_the_request(pattern):
    hits = SERVER_SRC.count(pattern)
    assert hits == 0, (
        f"server.py still reads privilege off the request: {pattern!r} appears "
        f"{hits} time(s). Each one is a URL-edit escalation."
    )


def test_every_analytical_handler_resolves_identity():
    """The four analytical handlers plus the raw Cube passthroughs must all resolve."""
    calls = SERVER_SRC.count("resolve_identity(self)")
    assert calls >= 6, (
        f"resolve_identity(self) is called {calls} time(s). Every handler that "
        "previously read the role off the request must call it instead."
    )


def test_executive_default_is_gone_from_handlers():
    """No handler may fall back to maximum privilege."""
    assert 'ROLE_EXECUTIVE_ALL"]' not in SERVER_SRC, (
        "A handler still defaults an unidentified caller to ROLE_EXECUTIVE_ALL."
    )


def test_member_endpoint_reports_the_resolved_role(portal):
    body = portal.get_json(MEMBER_ENDPOINT)
    assert body.get("role") == LEAST_PRIVILEGED_ROLE, (
        f"Member analysis reports role {body.get('role')!r}; the resolved role "
        f"for an anonymous caller is {LEAST_PRIVILEGED_ROLE!r}."
    )
    assert body.get("can_view_pii") is False, (
        "Member analysis grants PII to an anonymous caller."
    )


@pytest.mark.parametrize("claimed", [
    "ROLE_EXECUTIVE_ALL",
    "ROLE_DIGITAL_OPERATIONS",
    "ROLE_INVESTMENTS",
    "ROLE_ANNUITY",
])
def test_member_endpoint_ignores_a_claimed_role(portal, claimed):
    body = portal.get_json(MEMBER_ENDPOINT, {"role": claimed})
    assert body.get("role") == LEAST_PRIVILEGED_ROLE, (
        f"role={claimed} in the URL changed the member endpoint's role to "
        f"{body.get('role')!r}."
    )
    assert body.get("can_view_pii") is False


def test_member_endpoint_ignores_a_combined_escalation(portal):
    body = portal.get_json(
        MEMBER_ENDPOINT, {"role": "ROLE_EXECUTIVE_ALL", "maskPii": "false"}
    )
    assert body.get("role") == LEAST_PRIVILEGED_ROLE
    assert body.get("can_view_pii") is False


def test_ui_does_not_let_the_user_pick_a_role():
    """app.js:251 assigns currentRole from a dropdown, then sends it as ?role=.

    Once the server ignores it the control is a lie, so it must become a
    read-only display fed by /api/identity.
    """
    assert "currentRole = e.target.value" not in APP_JS_SRC, (
        "The role selector still writes currentRole, presenting role choice as "
        "something the user controls."
    )


def test_ui_reads_its_role_from_the_identity_endpoint():
    assert "/api/identity" in APP_JS_SRC, (
        "app.js never calls /api/identity, so the role it displays is not the "
        "role the server resolved."
    )
