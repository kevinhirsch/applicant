"""AZ2 (#833-#838) — the health panel contract (source assertions).

The panel is browser-rendered HTML/JS (full E2E belongs in the P0-6 Playwright harness),
so here we pin the load-bearing contract at the source level, like the repo's other JS gates.
"""
from __future__ import annotations
from pathlib import Path

import pytest

PANEL = Path(__file__).resolve().parents[2] / "a0-applicant/webui/health.html"


@pytest.fixture(scope="module")
def html() -> str:
    return PANEL.read_text(encoding="utf-8")


class TestHealthPanel:
    """Source-level assertions for the health panel."""

    def test_drives_engine_through_health_proxy(self, html):
        assert 'callJsonApi("health", {' in html and 'action: "capabilities"' in html

    def test_renders_capability_labels(self, html):
        assert 'c.label || c.name' in html

    def test_renders_fix_copy(self, html):
        assert 'c.fix_copy' in html and 'fix_copy_required' in html

    def test_global_pause_wired(self, html):
        assert 'callJsonApi("campaigns", {' in html and 'action: "list"' in html and 'doGlobal("pause")' in html

    def test_global_resume_wired(self, html):
        assert 'doGlobal("resume")' in html

    def test_error_line_present(self, html):
        assert 'fatalError' in html
