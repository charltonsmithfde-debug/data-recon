"""
US-1.2 (cycle 5) -- The POPIA control is an indicator, not a switch.

> As a Security Officer, I want the PII masking state to be resolved server-side
> from the caller's entitlement, so that the UI cannot claim an entitlement the
> user does not have.

Cycle 4 closed the server-side hole: `resolve_identity()` decides `can_view_pii`
and every handler obeys it. What survives is the client-side half of the same
lie, in exactly the shape the role `<select>` had before cycle 4:

  * `index.html` renders the POPIA state as a `<button>`, i.e. as something you
    may change.
  * `app.js` binds a click handler that flips `isPiiMasked` and relabels the
    control **"PII Unmasked (Exec)"** -- asserting an executive entitlement that
    the server has already refused. Nothing actually unmasks.
  * All three analytical fetches still append `maskPii=<flag>` to the query
    string. The server ignores it (there is a cycle-4 test proving that), so the
    parameter's only remaining function is to suggest the client has a vote.

A control that misreports the security state is worse than no control: an
operator reading "PII Unmasked (Exec)" has no way to know the data in front of
them is masked anyway, and an auditor reading it concludes the opposite of the
truth.

The fix mirrors cycle 4's `roleSelector` -> `roleDisplay`: the POPIA pill becomes
a read-only indicator fed by `/api/identity`, and the dead parameter goes.

Seams: static repo invariant (D) for "the switch no longer exists", and the
thin-web-app HTTP API (A) for "the server still reports masked for an
unidentified caller". The member endpoint is the HTTP probe because it is the one
analytical handler that answers without Cube credentials (it is synthetic -- see
US-6.0).
"""

from pathlib import Path

import pytest

APP_DIR = Path(__file__).resolve().parent.parent
APP_JS_SRC = (APP_DIR / "app.js").read_text(encoding="utf-8")
INDEX_SRC = (APP_DIR / "index.html").read_text(encoding="utf-8")

MEMBER_ENDPOINT = "/api/member_analysis/query"

# The claim the control must never make. The server decides entitlement; the
# client may report it, never assert it.
FALSE_ENTITLEMENT_CLAIM = "PII Unmasked (Exec)"


# --------------------------------------------------------------------------
# Seam D -- the switch must not exist
# --------------------------------------------------------------------------

def test_popia_control_is_not_a_button():
    """A <button> invites a click. The masking state is not the user's to set."""
    assert '<button id="popiaToggle"' not in INDEX_SRC, (
        "index.html still renders the POPIA state as a <button>, so the UI "
        "presents a server-side entitlement as a user-settable control."
    )


def test_popia_control_has_no_click_handler():
    """The click handler is what turns a label into a (fake) switch."""
    assert 'getElementById("popiaToggle")' not in APP_JS_SRC, (
        "app.js still looks up #popiaToggle to bind behaviour to it. The "
        "indicator is populated from /api/identity, not wired to an event."
    )
    assert "popiaBtn.addEventListener" not in APP_JS_SRC, (
        "app.js still binds a click listener to the POPIA control."
    )


def test_masking_flag_is_never_flipped_by_the_client():
    """`isPiiMasked` may be assigned from identity, and from nowhere else."""
    assert "isPiiMasked = !isPiiMasked" not in APP_JS_SRC, (
        "app.js still toggles isPiiMasked in place. Its only legitimate "
        "assignment is from /api/identity in initIdentity()."
    )


def test_ui_never_claims_an_entitlement_the_server_refused():
    assert FALSE_ENTITLEMENT_CLAIM not in APP_JS_SRC, (
        f"app.js can still render {FALSE_ENTITLEMENT_CLAIM!r}. An unidentified "
        "caller is ROLE_FINANCE_MEMBER with PII masked; the label asserts the "
        "opposite of what the server just did."
    )
    assert FALSE_ENTITLEMENT_CLAIM not in INDEX_SRC, (
        f"index.html hardcodes {FALSE_ENTITLEMENT_CLAIM!r}."
    )


def test_no_fetch_sends_the_dead_mask_parameter():
    """The server ignores maskPii (cycle 4). Sending it implies otherwise."""
    hits = APP_JS_SRC.count("maskPii")
    assert hits == 0, (
        f"app.js still references maskPii {hits} time(s). The server derives "
        "masking from identity and ignores the parameter, so every send is a "
        "misleading no-op on the wire."
    )


# --------------------------------------------------------------------------
# Seam A -- the server's answer is unchanged and authoritative
# --------------------------------------------------------------------------

def test_identity_reports_masked_for_an_unidentified_caller(portal):
    identity = portal.get_json("/api/identity")
    assert identity["can_view_pii"] is False, (
        "An unidentified caller was granted PII visibility."
    )


def test_member_payload_agrees_with_identity(portal):
    """The indicator can only be honest if the payload it reflects is."""
    identity = portal.get_json("/api/identity")
    payload = portal.get_json(f"{MEMBER_ENDPOINT}?tab=overview")
    assert payload["can_view_pii"] == identity["can_view_pii"], (
        "The member payload disagrees with /api/identity about PII "
        "entitlement, so the UI cannot render a truthful indicator from either."
    )


@pytest.mark.parametrize("escalation", [
    "?tab=overview&maskPii=false",
    "?tab=overview&maskPii=false&role=ROLE_EXECUTIVE_ALL",
])
def test_asking_to_unmask_changes_nothing(portal, escalation):
    """Regression guard: the parameter is dead and must stay dead."""
    payload = portal.get_json(f"{MEMBER_ENDPOINT}{escalation}")
    assert payload["can_view_pii"] is False, (
        f"{escalation!r} unmasked PII for an unidentified caller."
    )
