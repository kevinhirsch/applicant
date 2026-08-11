"""AZ3 (#842) — interview-prep panel source assertions.

The panel is static HTML rendered by the WebUI; we pin the load-bearing contract
at the source level.
"""
from pathlib import Path

import pytest

PANEL = (
    Path(__file__).resolve().parents[2]
    / "a0-applicant/webui/interview_prep.html"
)


@pytest.fixture(scope="module")
def html() -> str:
    return PANEL.read_text(encoding="utf-8")


class TestInterviewPrepPanel:
    """Source-assert the interview-prep panel conforms to the spec contract."""

    def test_has_css_prefix(self, html):
        assert ".aintprep" in html

    def test_has_alpine_data(self, html):
        # commit 44c3c155b ("fix(ui): repair panel errors surfaced by a full
        # monkey-crawl (23->0 broken panels)") fixed a REAL bug this test used to
        # pin the broken form of: `x-data="window.Alpine.data('X')"` is Alpine's
        # GETTER (returns undefined outside a running Alpine context), so the
        # component never instantiated -- cascading into "aintprep is not
        # defined" at runtime. The fix switched every affected panel (interview_
        # prep included) to the correct `x-data="X()"` shorthand. Assert the
        # component is both registered AND invoked via the corrected call site.
        assert "window.Alpine.data('aintprep', " in html
        assert 'x-data="aintprep()"' in html

    def test_has_campaign_picker(self, html):
        assert "callJsonApi('campaigns'" in html
        assert "action: 'list'" in html

    def test_has_application_picker(self, html):
        assert "callJsonApi('tracker'" in html
        assert "board" in html

    def test_calls_interview_prep_get(self, html):
        assert "callJsonApi('interview_prep'" in html
        assert "action: 'get'" in html

    def test_has_empty_state(self, html):
        assert "no interview prep" in html.lower() or "No interview prep" in html

    def test_has_error_line(self, html):
        assert "x-show=\"fatalError" in html

    def test_has_help_affordance(self, html):
        assert "help.html?surface=interview_prep" in html

    def test_has_engine_llm_notice(self, html):
        assert "engine-generated" in html.lower() or "engine LLM" in html.lower() or "engine" in html.lower()
