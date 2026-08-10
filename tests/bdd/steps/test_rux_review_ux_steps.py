"""Step bindings for the REVIEW-UX frontend acceptance spec (EPIC REVIEW-UX).

Mirrors the repo's other frontend BDD gates (e.g. ``test_enh_t13_uikit_steps.py``):
all probes are coarse structural facts read off the real panel source — no browser is
launched and no socket is opened. The Review modal is a thin UX layer over the engine
``/api/review`` surface (proxy ``plugins/applicant/review``); these steps pin the wire
contract + theme-safety the frontend depends on.
"""
from __future__ import annotations

import pathlib

from pytest_bdd import given, scenarios, then

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
# The Review modal is the existing documents.html surface (the Digest "Review" button's
# target); the RUX workflow is folded into it reuse-first rather than forking a panel.
REVIEW = REPO_ROOT / "a0-applicant" / "webui" / "documents.html"
DIGEST = REPO_ROOT / "a0-applicant" / "webui" / "digest.html"

scenarios(str(REPO_ROOT / "tests" / "bdd" / "features" / "enhancements" / "rux_review_ux.feature"))


def _read(path: pathlib.Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


# --- Given -----------------------------------------------------------------

@given("the Review modal panel", target_fixture="html")
def _review_panel() -> str:
    text = _read(REVIEW)
    assert text, f"Review modal missing at {REVIEW}"
    return text


@given("the Digest panel", target_fixture="html")
def _digest_panel() -> str:
    text = _read(DIGEST)
    assert text, f"Digest panel missing at {DIGEST}"
    return text


# --- Then (RUX-1) ----------------------------------------------------------

@then("it links the shared applicant theme stylesheet")
def _links_theme(html: str) -> None:
    assert "/plugins/applicant/webui/applicant-theme.css" in html


@then('it exposes a "View source posting" link that opens in a new tab without opener leak')
def _source_link(html: str) -> None:
    assert "View source posting" in html or "View source" in html
    assert 'target="_blank"' in html
    assert "noopener" in html
    assert "source_url" in html


@then("it shows a posted-date freshness cue")
def _freshness(html: str) -> None:
    assert "posted_relative" in html and "posted_stale" in html


@then("it offers a cached snapshot fallback via the review snapshot action")
def _snapshot(html: str) -> None:
    assert 'action: "snapshot"' in html


@then("each row exposes a source posting link opening in a new tab")
def _row_source_link(html: str) -> None:
    assert 'x-for="row in rows"' in html
    assert "View source posting" in html or "View source" in html
    assert 'target="_blank"' in html and "noopener" in html
    assert "row.link" in html or "source_url" in html


@then("each row offers a cached snapshot fallback via the review snapshot action")
def _row_snapshot(html: str) -> None:
    assert 'callJsonApi("review",' in html
    assert 'action: "snapshot"' in html


@then("the digest Review button opens the Review modal carrying the posting id")
def _digest_opens_review(html: str) -> None:
    assert "window.openModal" in html and "documents.html" in html
    assert "posting_id" in html


# --- Then (RUX-2) ----------------------------------------------------------

@then("it offers Continue, Save for later, and Discard decisions via the review decide action")
def _three_way(html: str) -> None:
    assert 'action: "decide"' in html
    assert "Continue" in html
    assert "Save for later" in html or "Save-for-later" in html
    assert "Discard" in html


@then("discarding requires a non-blank reason")
def _discard_reason(html: str) -> None:
    assert "reason" in html and ".trim()" in html


# --- Then (RUX-3) ----------------------------------------------------------

@then("it renders the generated sections with their review status")
def _sections(html: str) -> None:
    assert "sections" in html and "section_id" in html and "status" in html


@then("it can inline-edit and save a section via the edit_section action")
def _edit_section(html: str) -> None:
    assert 'action: "edit_section"' in html and "textarea" in html and "content" in html


@then("it can regenerate a single section via the regenerate_section action")
def _regen_section(html: str) -> None:
    assert 'action: "regenerate_section"' in html


@then("it can apply feedback across sections via the apply_feedback action")
def _apply_feedback(html: str) -> None:
    assert 'action: "apply_feedback"' in html


@then("it can regenerate the whole app via the regenerate_all action")
def _regen_all(html: str) -> None:
    assert 'action: "regenerate_all"' in html


# --- Then (RUX-5) ----------------------------------------------------------

@then("it exposes a freeform profile feedback box via the profile_feedback action")
def _profile_feedback(html: str) -> None:
    assert 'action: "profile_feedback"' in html


@then("it shows what changed and lets the reviewer revert it")
def _transparent_reversible(html: str) -> None:
    assert "changes" in html
    assert 'action: "revert_feedback"' in html or "revert" in html.lower()
