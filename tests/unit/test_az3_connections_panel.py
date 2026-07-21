"""AZ3-6 (#844) — the connections panel contract (source assertions).

The panel is browser-rendered HTML/JS (full E2E belongs in the P0-6 Playwright harness),
so here we pin the load-bearing contract at the source level, like the repo's other JS gates.
"""
from __future__ import annotations
from pathlib import Path

import pytest

PANEL = Path(__file__).resolve().parents[2] / "a0-applicant/webui/connections.html"


@pytest.fixture(scope="module")
def html() -> str:
    return PANEL.read_text(encoding="utf-8")


class TestConnectionsPanel:
    """Source-level assertions for the connections panel."""

    def test_get_email_accounts_via_callJsonApi(self, html):
        assert "callJsonApi('connections', " in html
        assert "action:'get_email_accounts'" in html or "'get_email_accounts'" in html

    def test_add_email_account_via_callJsonApi(self, html):
        assert "callJsonApi('connections', " in html
        assert "action:'add_email_account'" in html or "'add_email_account'" in html

    def test_test_email_account_via_callJsonApi(self, html):
        assert "callJsonApi('connections', " in html
        assert "action:'test_email_account'" in html or "'test_email_account'" in html

    def test_get_calendar_config_via_callJsonApi(self, html):
        assert "callJsonApi('connections', " in html
        assert "action:'get_calendar_config'" in html or "'get_calendar_config'" in html

    def test_set_calendar_config_via_callJsonApi(self, html):
        assert "callJsonApi('connections', " in html
        assert "action:'set_calendar_config'" in html or "'set_calendar_config'" in html

    def test_test_calendar_config_via_callJsonApi(self, html):
        assert "callJsonApi('connections', " in html
        assert "action:'test_calendar_config'" in html or "'test_calendar_config'" in html

    def test_has_imap_fields(self, html):
        assert "imap" in html.lower()

    def test_has_smtp_fields(self, html):
        assert "smtp" in html.lower()

    def test_has_caldav(self, html):
        assert "CalDAV" in html or "caldav" in html.lower()

    def test_has_app_password(self, html):
        assert "app password" in html.lower()

    def test_mentions_engine_job_search(self, html):
        assert "engine" in html.lower() or "job-search" in html.lower() or "job search" in html.lower()

    def test_mentions_assistant_mcp(self, html):
        assert "assistant" in html.lower() or "mcp" in html.lower()

    def test_has_save_button(self, html):
        assert "Save" in html

    def test_has_send_test_button(self, html):
        assert "Send test" in html or "test" in html.lower()

    def test_has_delete_button(self, html):
        assert "Delete" in html

    def test_empty_email_state(self, html):
        assert "No email account" in html or "No email" in html

    def test_empty_calendar_state(self, html):
        assert "No calendar" in html

    def test_help_surface_connections(self, html):
        assert "surface=connections" in html

    def test_interview_mentioned(self, html):
        assert "interview" in html.lower()

    def test_has_fatal_error_display(self, html):
        assert 'x-show="fatalError"' in html
        assert 'class="err" x-text="fatalError"' in html
