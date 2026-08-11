"""AZ3 (#841) — the mind panel contract (source assertions).

The panel is browser-rendered HTML/JS (full E2E belongs in the P0-6 Playwright harness),
so here we pin the load-bearing contract at the source level, like the repo's other JS gates.
"""
from __future__ import annotations
from pathlib import Path

import pytest

PANEL = Path(__file__).resolve().parents[2] / "a0-applicant/webui/mind.html"


@pytest.fixture(scope="module")
def html() -> str:
    return PANEL.read_text(encoding="utf-8")


class TestMindPanel:
    """Source-level assertions for the mind panel."""

    def test_drives_engine_through_mind_proxy(self, html):
        assert 'callJsonApi("mind", { action: "memory" }' in html

    def test_renders_skills_section(self, html):
        assert 'callJsonApi("mind", { action: "skills" }' in html

    def test_renders_curation_section(self, html):
        assert 'callJsonApi("mind", { action: "curation" }' in html

    def test_approve_wired(self, html):
        assert 'callJsonApi("mind", { action: "approve", proposal_id:' in html

    def test_forget_wired(self, html):
        assert 'callJsonApi("mind", { action: "forget",' in html

    def test_error_line_present(self, html):
        assert 'fatalError' in html
