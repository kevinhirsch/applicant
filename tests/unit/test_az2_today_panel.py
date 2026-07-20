"""AZ2 (#833-#838) — the daily-review panel contract (source assertions).

The panel is browser-rendered HTML/JS (full E2E belongs in the P0-6 Playwright harness),
so here we pin the load-bearing contract at the source level, like the repo's other JS gates.
"""
from pathlib import Path

import pytest

PANEL = Path(__file__).resolve().parents[2] / "a0-applicant/webui/today.html"


@pytest.fixture(scope="module")
def html() -> str:
    return PANEL.read_text(encoding="utf-8")


def test_drives_the_engine_through_pending_proxy(html):
    assert 'callJsonApi("pending", {' in html and 'action: "list"' in html


def test_resolve_button_wired(html):
    assert 'action: "resolve"' in html and 'action_id:' in html


def test_snooze_button_wired(html):
    assert 'action: "snooze"' in html and 'action_id:' in html and 'hours' in html


def test_resolve_bulk_button_wired(html):
    assert 'action: "resolve_bulk"' in html and 'campaign_id:' in html and 'action_ids:' in html


def test_include_snoozed_toggle(html):
    assert 'include_snoozed' in html


def test_empty_state_present(html):
    assert "all caught up" in html.lower()


def test_error_line_present(html):
    assert "fatalError" in html
