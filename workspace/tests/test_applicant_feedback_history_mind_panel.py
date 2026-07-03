"""Regression coverage for the "What you've told it" feedback-history section in
``static/js/applicantMind.js`` (dark-engine audit item 23).

Follows the convention of ``test_applicant_round1_chatmind.py`` / the ``uia11y``
steps: ``applicantMind.js`` does top-level ``document``/``fetch`` work on import
(it wires its launcher via ``document.readyState``), so it is not importable under
a bare ``node --input-type=module`` the way a dependency-free leaf module is --
hence the text/regex approach over the actual static file content, no browser/DOM.

Each assertion here was verified, by hand, to go red when the underlying addition
is reverted (revert source via a file-copy backup -> rerun -> see the assertion
fail -> restore the file) per the audit item's test-coverage DoD.
"""

from __future__ import annotations

import pathlib
import re

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
MIND_JS = REPO_ROOT / "workspace" / "static" / "js" / "applicantMind.js"


def _read() -> str:
    return MIND_JS.read_text(encoding="utf-8")


def test_feedback_history_proxy_endpoint_is_fetched():
    """The panel reads back real feedback history from the new workspace proxy
    (/api/applicant/memory/feedback-history), not a re-derived/local read."""
    src = _read()
    assert "/feedback-history" in src
    assert re.search(r"MEMORY_API\s*=\s*['\"]/api/applicant/memory['\"]", src)
    assert re.search(r"_fetchJSON\(`\$\{MEMORY_API\}/feedback-history`\)", src)


def test_what_youve_told_it_section_is_rendered():
    src = _read()
    assert "What you've told it" in src
    assert "_renderFeedbackHistory" in src
    # The render function is actually invoked from the modal body build, not just
    # defined-but-dead.
    assert re.search(r"\$\{_renderFeedbackHistory\(feedbackHistory\)\}", src)


def test_feedback_history_renderer_handles_empty_and_populated_states():
    src = _read()
    match = re.search(
        r"function _renderFeedbackHistory\(data\) \{(.*?)\n\}\n", src, re.DOTALL
    )
    assert match, "_renderFeedbackHistory not found"
    body = match.group(1)
    # Graceful empty state (mirrors _renderLessons / _renderSkills conventions).
    assert "memory-empty" in body
    # Both feedback kinds the engine's FeedbackSummaryProvider emits are labeled.
    assert "decline" in body
    assert "revised" in body or "revision" in body


def test_existing_mind_panel_sections_are_undisturbed():
    """The new section must be ADDITIVE -- the pre-existing Waiting for your
    review / Memory / Saved playbooks / Lessons sections must still render."""
    src = _read()
    for heading in (
        "Waiting for your review",
        ">Memory<",
        "Saved playbooks",
        "Lessons learned from job sites",
    ):
        assert heading in src, f"missing pre-existing section: {heading}"
    # Order: the new section is appended after the existing ones, not spliced in
    # the middle of them.
    lessons_idx = src.index("Lessons learned from job sites")
    told_it_idx = src.index(">What you've told it<")
    assert told_it_idx > lessons_idx
