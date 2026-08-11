"""AZ3 (#839) — the channels panel contract (source assertions).

The panel is browser-rendered HTML/JS (full E2E belongs in the P0-6 Playwright harness),
so here we pin the load-bearing contract at the source level, like the repo's other JS gates.
"""
from __future__ import annotations
from pathlib import Path

import pytest

PANEL = Path(__file__).resolve().parents[2] / "a0-applicant/webui/channels.html"


@pytest.fixture(scope="module")
def html() -> str:
    return PANEL.read_text(encoding="utf-8")


class TestChannelsPanel:
    """Source-level assertions for the channels panel."""

    def test_get_config_via_callJsonApi(self, html):
        assert "callJsonApi('channels', " in html
        assert "action: 'get'" in html

    def test_set_config_via_callJsonApi(self, html):
        assert "callJsonApi('channels', " in html
        assert "action: 'set'" in html

    def test_send_test_via_callJsonApi(self, html):
        assert "callJsonApi('channels', " in html
        assert "action: 'test'" in html

    def test_has_discord_field(self, html):
        assert "discord" in html.lower()

    def test_has_email_field(self, html):
        assert "email" in html.lower()

    def test_has_ntfy_field(self, html):
        assert "ntfy" in html.lower()

    def test_has_instructions(self, html):
        assert "Discord" in html
        assert "Apprise" in html or "SMTP" in html
        assert "ntfy" in html

    def test_has_save_button(self, html):
        assert "Save" in html

    def test_has_send_test_buttons(self, html):
        assert "Send test" in html

    def test_has_error_line(self, html):
        assert "error" in html

    def test_empty_state(self, html):
        assert "No channels configured" in html

    def test_has_quiet_hours_toggle(self, html):
        assert 'quietHoursEnabled' in html or 'quiet' in html.lower()
        assert 'formQuietHoursEnabled' in html

    def test_has_quiet_hours_start_end(self, html):
        assert 'formQuietHoursStart' in html
        assert 'formQuietHoursEnd' in html

    def test_has_quiet_hours_tz(self, html):
        assert 'formQuietHoursTz' in html

    def test_has_discord_respects_quiet(self, html):
        assert 'formDiscordRespectsQuiet' in html

    def test_has_email_respects_quiet(self, html):
        assert 'formEmailRespectsQuiet' in html

    def test_has_set_quiet_hours_action(self, html):
        assert "action: 'set_quiet_hours'" in html

    def test_has_save_quiet_hours_button(self, html):
        assert 'Save quiet hours' in html or 'saveQuietHours' in html
