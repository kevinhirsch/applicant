"""AZ2 (#833-#838) — the campaigns panel contract (source assertions).

The panel is browser-rendered HTML/JS (full E2E belongs in the P0-6 Playwright harness),
so here we pin the load-bearing contract at the source level, like the repo's other JS gates.
"""
from pathlib import Path

import pytest

PANEL = Path(__file__).resolve().parents[2] / "a0-applicant/webui/campaigns.html"


@pytest.fixture(scope="module")
def html() -> str:
    return PANEL.read_text(encoding="utf-8")


def test_drives_the_engine_through_campaigns_proxy(html):
    assert 'callJsonApi("campaigns", {' in html and 'action: "list"' in html


def test_create_button_wired(html):
    assert 'action: "create"' in html and 'name:' in html


def test_clone_button_wired(html):
    assert 'action: "clone"' in html and 'campaign_id:' in html


def test_update_active_toggle_wired(html):
    assert 'action: "update"' in html and 'campaign_id:' in html and 'active:' in html


def test_empty_state_present(html):
    assert 'empty' in html.lower() or 'no campaigns' in html.lower()


def test_error_line_present(html):
    assert 'fatalError' in html or 'r.ok' in html or 'r.error' in html
