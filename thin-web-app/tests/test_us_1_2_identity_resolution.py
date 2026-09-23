"""
US-1.2 -- Derive role from identity, never from the request.

> As a Security Officer, I want the user's role resolved server-side from their
> verified identity, so that a user cannot escalate by editing a URL.

Seam: thin-web-app HTTP API.

Today every handler reads `?role=` and `?maskPii=` straight off the query string
and defaults to ROLE_EXECUTIVE_ALL with PII visible (server.py:116, 153, 282,
499, 641) -- maximum privilege for an anonymous caller.

This cycle establishes the resolution seam: a single server-side answer to "who
is calling and what may they see", exposed at GET /api/identity so the UI can
display it read-only. Wiring every analytical handler to it is the next cycle.

Least privilege here is ROLE_FINANCE_MEMBER with PII masked -- matching Cube's
own fallback in cube.js:139,165, so no new role is invented.

Revised 2026-09-20 by US-1.1. "Anonymous" is no longer a caller this endpoint
answers: every /api/* path is behind a verified IAP assertion, so an
unidentified caller gets 401, not a least-privilege body. The substance of
US-1.2 -- that role and PII entitlement are never read off the request -- is
now asserted against an *authenticated* caller, which is strictly stronger:
the escalation attempts below are made by someone the server does trust.

`MAPPED_EMAIL` is deliberately absent from role_assignments.json, so a verified
caller still falls back to LEAST_PRIVILEGED_ROLE with PII masked. Only
`authenticated`, `email` and `role_source` differ from the pre-US-1.1 body.
"""

import pytest

from conftest import MAPPED_EMAIL

ENDPOINT = "/api/identity"

LEAST_PRIVILEGED_ROLE = "ROLE_FINANCE_MEMBER"

ALL_ROLES = [
    "ROLE_EXECUTIVE_ALL",
    "ROLE_FINANCE_MEMBER",
    "ROLE_DIGITAL_OPERATIONS",
    "ROLE_INVESTMENTS",
    "ROLE_ANNUITY",
]


def test_identity_endpoint_answers_who_is_calling(portal):
    body = portal.get_json(ENDPOINT)
    assert "role" in body, "No resolved role: the UI has nothing to display read-only."
    assert "can_view_pii" in body, "No resolved PII entitlement."
    assert "authenticated" in body, (
        "Response does not say whether the caller was actually identified, so the "
        "UI cannot distinguish 'signed in as' from 'anonymous fallback'."
    )


def test_unidentified_caller_is_not_answered_at_all(anon_portal):
    """US-1.1 replaced the anonymous least-privilege body with a 401.

    The old contract here asserted an unidentified caller got 200 plus
    `authenticated: False`. That was correct only while nothing could be
    verified. Now it must not be served.
    """
    status, _ = anon_portal.get(ENDPOINT)
    assert status == 401, (
        f"An unidentified caller got {status} from {ENDPOINT} instead of 401."
    )


def test_verified_but_unmapped_caller_gets_least_privilege(portal):
    """Identified is not the same as entitled.

    A caller the server verifies but has no role assignment for must still land
    on least privilege -- an authenticated stranger is not an executive.
    """
    body = portal.get_json(ENDPOINT)
    assert body["authenticated"] is True, (
        "A valid IAP assertion was not recognised as an identity."
    )
    assert body["email"] == MAPPED_EMAIL
    assert body["role"] == LEAST_PRIVILEGED_ROLE, (
        f"Unmapped caller resolved to {body['role']!r} instead of least "
        f"privilege {LEAST_PRIVILEGED_ROLE!r}."
    )
    assert body["can_view_pii"] is False, (
        "Unmapped caller may view unmasked member identifiers."
    )


@pytest.mark.parametrize("claimed", ALL_ROLES)
def test_role_parameter_cannot_change_the_resolved_role(portal, claimed):
    body = portal.get_json(ENDPOINT, {"role": claimed})
    assert body["role"] == LEAST_PRIVILEGED_ROLE, (
        f"Asking for role={claimed} changed the resolved role to {body['role']!r}. "
        "Role must come from identity, never from the request."
    )


@pytest.mark.parametrize("value", ["false", "FALSE", "0", "no", ""])
def test_maskpii_parameter_cannot_unmask(portal, value):
    body = portal.get_json(ENDPOINT, {"maskPii": value})
    assert body["can_view_pii"] is False, (
        f"maskPii={value!r} unmasked PII for an anonymous caller."
    )


def test_combined_escalation_attempt_is_ignored(portal):
    """The exact escalation the PRD calls out."""
    body = portal.get_json(ENDPOINT, {"role": "ROLE_EXECUTIVE_ALL", "maskPii": "false"})
    assert body["role"] == LEAST_PRIVILEGED_ROLE
    assert body["can_view_pii"] is False


def test_forged_iap_header_does_not_elevate(anon_portal):
    """A header a caller can write themselves must grant nothing.

    US-1.2's original concern was that an unverified assertion header would
    replace a query-string hole with a header one. US-1.1 settles it: an
    unverifiable assertion is now a 401 rather than a downgrade to anonymous.
    `x-goog-authenticated-user-email` is included because it is equally
    caller-writable and must never be read as an identity.
    """
    forger = anon_portal.with_headers(**{
        "x-goog-iap-jwt-assertion": "forged.not.verified",
        "x-goog-authenticated-user-email": "accounts.google.com:exec@sanlam.co.za",
    })
    status, _ = forger.get(ENDPOINT)
    assert status == 401, (
        f"A forged IAP header was answered {status} instead of 401."
    )


def test_authenticated_caller_cannot_claim_an_email(portal):
    """The email comes from the signed token, never from a second header.

    A verified caller adding `x-goog-authenticated-user-email` must not become
    someone else -- that header is not a source of identity.
    """
    impersonator = portal.with_headers(**{
        "x-goog-authenticated-user-email": "accounts.google.com:exec@sanlam.co.za",
    })
    body = impersonator.get_json(ENDPOINT)
    assert body["email"] == MAPPED_EMAIL, (
        f"Identity became {body['email']!r} on the strength of a writable header."
    )
    assert body["role"] == LEAST_PRIVILEGED_ROLE


def test_role_assignment_map_is_the_documented_source_of_truth(portal):
    """US-1.2 requires a role-mapping source of truth keyed by verified email."""
    body = portal.get_json(ENDPOINT)
    assert "role_source" in body, (
        "Response does not name where the role came from, so the mapping is not "
        "auditable."
    )
    assert body["role_source"] == "role_assignments", (
        f"Unexpected role_source {body['role_source']!r}. A verified caller's "
        "role must be attributed to the assignment map, not to the anonymous "
        "fallback -- US-1.1 means there are no anonymous callers here."
    )
