"""
US-6.0 (second acceptance criterion) -- the DEMO DATA banner.

> Dashboard 1 renders a visible `DEMO DATA -- NOT FROM SOURCE` banner until
> US-6.1..6.4 land.

Seam: static repo invariants (confirmed seam D).

PROXY TEST -- READ THIS BEFORE TRUSTING IT
------------------------------------------
The honest seam for "renders a visible banner" is the rendered DOM, which needs a
headless browser. None is installed, and that work is US-7.3. Until then this
module asserts the wiring exists: the markup declares a banner element, and the
render path drives it from the API's `demo_data` flag rather than a hardcoded
literal.

This is implementation-coupled by construction and will pass a banner that is,
say, invisible behind a z-index. US-7.3 must replace it with a real visibility
assertion; delete this module then.
"""

import re
from pathlib import Path

import pytest

APP_DIR = Path(__file__).resolve().parent.parent
INDEX_HTML = (APP_DIR / "index.html").read_text(encoding="utf-8")
APP_JS = (APP_DIR / "app.js").read_text(encoding="utf-8")

BANNER_ID = "memberDemoBanner"


def test_dashboard_1_declares_a_banner_element():
    assert f'id="{BANNER_ID}"' in INDEX_HTML, (
        f"index.html has no #{BANNER_ID} element for the US-6.0 demo banner."
    )


def test_banner_lives_inside_dashboard_1():
    view_start = INDEX_HTML.find('id="memberAnalysisView"')
    assert view_start != -1, "index.html no longer contains #memberAnalysisView."
    banner_pos = INDEX_HTML.find(f'id="{BANNER_ID}"')
    assert banner_pos > view_start, (
        "The demo banner must sit inside the Member Analysis view, not elsewhere "
        "in the shell."
    )


def test_banner_is_driven_by_the_api_flag_not_hardcoded():
    assert "demo_data" in APP_JS, (
        "app.js never reads the API's demo_data flag, so the banner cannot "
        "disappear when US-6.1 makes the data real."
    )
    assert BANNER_ID in APP_JS, f"app.js never touches #{BANNER_ID}."


def test_banner_carries_the_wording_the_prd_specifies():
    """The em dash is part of the specified string; accept the server's copy or a local fallback."""
    pattern = re.compile(r"DEMO DATA\s*[—-]\s*NOT FROM SOURCE")
    assert pattern.search(APP_JS) or pattern.search(INDEX_HTML), (
        "Neither the markup nor the render path contains the required wording "
        "'DEMO DATA -- NOT FROM SOURCE'."
    )


def _member_render_path():
    """app.js source of fetchMemberAnalysisData() -- the Dashboard 1 render path.

    Scoped deliberately: the identical claim in fetchInvestmentAnalysisData()
    belongs to Dashboard 2 and is owned by US-6.6, not this story.
    """
    start = APP_JS.find("async function fetchMemberAnalysisData")
    assert start != -1, "app.js no longer defines fetchMemberAnalysisData()."
    nxt = APP_JS.find(chr(10) + "async function ", start + 1)
    end = nxt if nxt != -1 else len(APP_JS)
    return APP_JS[start:end]


def test_stale_live_feed_claim_is_gone_from_the_render_path():
    """app.js used to relabel the cloud tag 'scbi-cube live feed active' off data.live_feed."""
    path = _member_render_path()
    assert "live feed active" not in path, (
        "Dashboard 1's render path still shows a 'live feed active' label built "
        "from the removed live_feed field (US-6.0)."
    )
    assert "data.live_feed" not in path, (
        "Dashboard 1's render path still reads data.live_feed."
    )
