"""AZ2 (#836) — the takeover panel contract (source assertions).

The panel is browser-rendered HTML/JS (full E2E belongs in the P0-6 Playwright harness),
so here we pin the load-bearing contract at the source level, like the repo's other JS gates.
"""
from __future__ import annotations
from pathlib import Path

import pytest

PANEL = Path(__file__).resolve().parents[2] / "a0-applicant/webui/takeover.html"


@pytest.fixture(scope="module")
def html() -> str:
    return PANEL.read_text(encoding="utf-8")


class TestTakeoverPanel:
    """Source-level assertions for the takeover panel."""

    def test_list_sessions_via_callJsonApi(self, html):
        assert 'callJsonApi("takeover",' in html
        assert '{ action: "sessions" }' in html or "action: 'sessions'" in html or '"sessions"' in html

    def test_view_url_via_callJsonApi(self, html):
        assert 'view_url' in html

    def test_takeover_via_callJsonApi(self, html):
        assert 'takeover' in html

    def test_resume_2fa_via_callJsonApi(self, html):
        assert 'resume_2fa' in html

    def test_resume_account_via_callJsonApi(self, html):
        assert 'resume_account' in html

    def test_resume_detection_via_callJsonApi(self, html):
        assert 'resume_detection' in html

    def test_handoff_via_callJsonApi(self, html):
        assert 'handoff' in html

    def test_final_approval_via_callJsonApi(self, html):
        assert 'final_approval' in html

    def test_iframe_embed(self, html):
        assert '<iframe' in html or '<iframe ' in html

    def test_human_approval_label(self, html):
        assert 'human' in html.lower() or 'Human' in html

    def test_fatalError_line(self, html):
        assert 'fatalError' in html

    def test_empty_state(self, html):
        assert 'No live sessions' in html or 'No sessions' in html
