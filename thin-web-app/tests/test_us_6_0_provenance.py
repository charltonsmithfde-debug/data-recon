"""
US-6.0 -- Stop asserting "live".

> As a Product Owner, I want the portal to stop claiming fabricated data is live,
> so that no decision is taken on it while the rebuild runs.

Seam: thin-web-app HTTP API (`/api/member_analysis/query`).

The behaviour under test is provenance honesty: a response must declare where its
numbers came from, and must not assert a live Cube link it does not have.

These expectations move with the rebuild. When US-6.1..6.4 land and the handler
actually queries Cube, `EXPECTED_SOURCE` below becomes "cube" -- the contract
(a response always declares its provenance) does not change.
"""

import pytest

ENDPOINT = "/api/member_analysis/query"

# The member_analysis handler is still the synthetic path (server.py:296,
# `base_total = 366784`). Flip to "cube" as part of US-6.1.
EXPECTED_SOURCE = "synthetic"

# A representative spread of filter states: the claim must hold for all of them.
FILTER_CASES = [
    pytest.param({}, id="no-filters"),
    pytest.param({"fund": "SANLAM UMBRELLA PENSION FUND"}, id="fund"),
    pytest.param({"business_unit": "SUS"}, id="business-unit"),
    pytest.param({"date": "31-DEC-2025", "client": "All"}, id="date-and-client"),
]


@pytest.mark.parametrize("filters", FILTER_CASES)
def test_response_does_not_claim_a_live_feed(portal, filters):
    body = portal.get_json(ENDPOINT, filters)
    assert body.get("live_feed") is not True, (
        "Response asserts live_feed=true while the numbers are fabricated in-process."
    )


@pytest.mark.parametrize("filters", FILTER_CASES)
def test_response_does_not_claim_cube_is_linked(portal, filters):
    body = portal.get_json(ENDPOINT, filters)
    status = str(body.get("cube_status", ""))
    assert "Linked" not in status and "Active" not in status, (
        f"Response asserts a Cube link it never made: cube_status={status!r}"
    )


@pytest.mark.parametrize("filters", FILTER_CASES)
def test_response_declares_its_provenance(portal, filters):
    body = portal.get_json(ENDPOINT, filters)
    assert "data_source" in body, (
        "Response carries no data_source field, so a client cannot tell measured "
        "data from fabricated data."
    )
    assert body["data_source"] == EXPECTED_SOURCE, (
        f"data_source is {body['data_source']!r}, expected {EXPECTED_SOURCE!r}."
    )


@pytest.mark.parametrize("filters", FILTER_CASES)
def test_response_flags_demo_data_so_the_ui_can_warn(portal, filters):
    body = portal.get_json(ENDPOINT, filters)
    assert body.get("demo_data") is True, (
        "Response does not set demo_data=true, so the DEMO DATA banner required by "
        "US-6.0 has nothing to render from."
    )
