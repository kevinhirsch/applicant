"""AZ2 (#837) — the chat panel contract (source assertions).

The panel is browser-rendered HTML/JS (full E2E belongs in the P0-6 Playwright harness),
so here we pin the load-bearing contract at the source level, like the repo's other JS gates.
"""
from __future__ import annotations
from pathlib import Path

import pytest

PANEL = Path(__file__).resolve().parents[2] / "a0-applicant/webui/chat.html"


@pytest.fixture(scope="module")
def html() -> str:
    return PANEL.read_text(encoding="utf-8")


class TestChatPanel:
    """Source-level assertions for the chat panel."""

    def test_list_campaigns_via_callJsonApi(self, html):
        assert 'callJsonApi("campaigns", { action: "list" }' in html

    def test_chat_history_via_callJsonApi(self, html):
        assert 'callJsonApi("chat", { action: "history"' in html

    def test_chat_send_via_callJsonApi(self, html):
        assert 'callJsonApi("chat"' in html
        assert 'action: "send"' in html

    def test_has_error_line(self, html):
        assert "fatalError" in html

    def test_empty_state(self, html):
        assert "Start a conversation" in html

    def test_has_conversation_div(self, html):
        assert "conversation" in html

    def test_has_msg_user_class(self, html):
        assert "msg.user" in html

    def test_has_msg_assistant_class(self, html):
        assert "msg.assistant" in html

    def test_has_input_row(self, html):
        assert "input-row" in html

    def test_has_send_button(self, html):
        assert "Send" in html

    def test_has_pending_confirm_banner(self, html):
        assert "confirm-banner" in html

    def test_chip_css_classes(self, html):
        """D1: chip rendering CSS classes exist in the panel HTML."""
        assert '.achat .chips' in html
        assert '.achat .chip' in html

    def test_chip_markup_structure(self, html):
        """D1: chips are rendered for assistant messages with actions."""
        assert 'item.actions' in html
        assert 'act.label' in html
        assert 'act.action' in html
        assert 'callJsonApi' in html

    def test_chip_actions_data_field(self, html):
        """D1: the actions field from data is attached to conversation items."""
        assert 'data.actions' in html
        assert 'pendingIdx].actions' in html

    def test_chip_assistant_only(self, html):
        """D1: chips only render for assistant role messages."""
        assert "item.role === 'assistant'" in html
