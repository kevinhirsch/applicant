"""P1-8 — Résumé <-> JD keyword / ATS match score, front-door half.

The engine half (coverage persisted in ``ResumeVariant.fit_scores``; digest rows
carrying ``keyword_coverage``/``keyword_matched``/``keyword_missing``) is covered
by ``tests/unit/test_p1_8_keyword_coverage.py``. This file pins the two
front-door surfaces, following the static-source convention
``test_applicant_backlog_jdmatch.py`` established (regex over the shipped JS —
no browser, no DOM):

* ``static/js/emailLibrary/applicantDigest.js`` ``buildDigestRow`` — the
  keyword-coverage chip on digest cards (Email tab AND Portal share this one
  renderer), rendered ONLY when the engine attached a real score.
* ``static/js/documentLibrary.js`` ``_loadJdMatch`` / ``_suggestMissingTerm`` —
  missing keywords rendered as SUGGESTION chips that only pre-fill the existing
  "Ask for a change" box; the change flows through the normal request-change ->
  redline -> approve path, never an auto-insert (fabrication-guard honoring).
"""

from __future__ import annotations

import pathlib
import re

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
JS_DIR = REPO_ROOT / "workspace" / "static" / "js"
DIGEST_JS = JS_DIR / "emailLibrary" / "applicantDigest.js"
DOCLIB_JS = JS_DIR / "documentLibrary.js"


def _read(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8")


def _digest_row_fn() -> str:
    src = _read(DIGEST_JS)
    m = re.search(r"export function buildDigestRow\(row, ctx = \{\}\) \{(.*?)\n\}\n", src, re.S)
    assert m, "expected the buildDigestRow(row, ctx) renderer"
    return m.group(1)


def _jd_match_fn() -> str:
    src = _read(DOCLIB_JS)
    m = re.search(
        r"async function _loadJdMatch\(appId, container\) \{(.*?)\n    \}\n", src, re.S
    )
    assert m, "expected to find _loadJdMatch()"
    return m.group(1)


def _suggest_fn() -> str:
    src = _read(DOCLIB_JS)
    m = re.search(
        r"function _suggestMissingTerm\(slot, term\) \{(.*?)\n    \}\n", src, re.S
    )
    assert m, "expected to find _suggestMissingTerm()"
    return m.group(1)


# ── digest card chip ─────────────────────────────────────────────────────────


def test_digest_row_renders_a_keyword_coverage_chip():
    fn = _digest_row_fn()
    assert "row.keyword_coverage" in fn
    assert "applicant-digest-keywords" in fn
    assert "Keywords ${kw}%" in fn


def test_digest_chip_only_renders_a_real_engine_score():
    """Honesty: no engine-attached score (no résumé on file / no extractable
    keywords) must mean NO chip — never a locally fabricated 0%."""
    fn = _digest_row_fn()
    assert "row.keyword_coverage != null" in fn
    assert "Number.isFinite(kwRaw)" in fn


def test_digest_chip_tooltip_names_the_missing_keywords():
    fn = _digest_row_fn()
    assert "row.keyword_missing" in fn
    assert "kwMissing.slice(0, 6)" in fn
    assert "Missing:" in fn


def test_digest_chip_reuses_the_existing_score_chip_styling():
    """No new visual system: the keyword chip reuses the same .memory-count
    styling the model-driven "% match" chip beside it already uses."""
    fn = _digest_row_fn()
    assert "cls: 'memory-count applicant-digest-keywords'" in fn


# ── redline review: missing terms as approve-gated suggestions ──────────────


def test_missing_terms_render_as_suggestion_chips():
    fn = _jd_match_fn()
    assert "doclib-applicant-suggest-term" in fn
    assert "missing.slice(0, 6)" in fn
    assert "_suggestMissingTerm(container, term)" in fn


def test_suggestion_only_prefills_the_existing_change_box():
    """The chip must ONLY pre-fill the existing "Ask for a change" instruction
    box (the redline turn path) — never call the engine itself. Auto-inserting a
    keyword would bypass the user-approval + truthfulness flow."""
    fn = _suggest_fn()
    assert ".doclib-applicant-instruction" in fn
    assert "fetch(" not in fn
    assert "/turn" not in fn
    assert "/approve" not in fn


def test_suggestion_persists_like_typed_text_and_guides_the_user():
    fn = _suggest_fn()
    # Fires the input listener so the panel's draft store keeps the suggestion.
    assert "dispatchEvent(new Event('input', { bubbles: true }))" in fn
    # Plain-language guidance when no review panel is open yet.
    assert "Open Review on a document below first" in fn
    # And the confirmation names the approval step — the user stays in charge.
    assert "Request change" in fn


def test_suggestion_text_stays_truthful():
    """The pre-filled instruction must ask to work the term in only where the
    candidate's real experience supports it — reinforcing, not fighting, the
    engine-side truthfulness guard."""
    fn = _suggest_fn()
    assert "where my real experience genuinely supports it" in fn
