"""AZ2 (#833-#838) — the notifications panel contract (source assertions).

The panel is browser-rendered HTML/JS (full E2E belongs in the P0-6 Playwright harness),
so here we pin the load-bearing contract at the source level, like the repo's other JS gates.
"""
from pathlib import Path

import pytest

PANEL = Path(__file__).resolve().parents[2] / "a0-applicant/webui/notifications.html"


@pytest.fixture(scope="module")
def html() -> str:
    return PANEL.read_text(encoding="utf-8")


class TestNotificationsPanel:
    """Source-level assertions for the notifications panel."""

    def test_drives_the_engine_through_notifications_proxy(self, html):
        assert 'callJsonApi("notifications", {' in html and 'action: "list"' in html

    def test_mark_seen_button_wired(self, html):
        assert 'action: "seen"' in html and 'notification_id:' in html

    def test_deliver_now_button_wired(self, html):
        assert 'action: "deliver_now"' in html

    def test_empty_state_present(self, html):
        assert 'empty' in html.lower() or 'no notifications' in html.lower()

    def test_error_line_present(self, html):
        assert 'fatalError' in html or 'r.ok' in html or 'r.error' in html
