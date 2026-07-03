"""Regression coverage for rendering ``ResumeVariant.fit_scores`` -- the
per-variant JD-keyword coverage + missing terms -- as "why this variant"
evidence on résumé-variant cards (dark-engine audit item 53).

Background (verified by reading the code, not assumed):

* The engine computes/stores ``ResumeFitScoring.coverage`` (0.0..1.0) and
  ``.missing_terms`` per variant (``src/applicant/core/entities/resume_variant.py``),
  serialized on the wire as ``fit_scores: {"coverage": 0.82, "missing_terms":
  [...]}`` (see ``AdminQueryService.variant_library``,
  ``application/services/dev_seed.py``).
* The workspace proxy (``workspace/routes/applicant_documents_routes.py``
  ``variant_library`` / ``GET /api/applicant/documents/variants/{campaign_id}``)
  hands the engine's JSON back UNCHANGED -- confirmed by reading the route: it
  is a bare ``ApplicantEngineClient.list_variants`` passthrough with no field
  stripping, so no proxy change was needed for this task.
* Before this change, grep found ZERO renders of ``coverage``/``missing_terms``
  anywhere in ``workspace/static/js``. The closest existing code
  (``_loadVariantLibrary``'s per-variant summary line) treated ``fit_scores``
  as a generic bag of numbers (``Object.values(scores).map(Number)``), which
  for the real ``{coverage, missing_terms}`` shape produces a "best fit NaN"-
  style dead end (``missing_terms`` is an array, ``Number([...])`` on a
  multi-element array is ``NaN``) and never surfaced the missing terms at all.

This module confines itself to ``workspace/static/js/documentLibrary.js``,
the only file this task touches (the proxy needed no change). Follows the
``test_applicant_round2_emailscan_ui.py`` convention: source-text regex
assertions against the browser-only module (no DOM-independent entry point
cheap enough to shim). Each assertion was hand-verified to go RED when the
corresponding piece of the change is reverted (temporarily restored the
pre-fix source, reran, saw a real ``AssertionError``, then restored the fix
and reran green) -- see the docstring on each test group below for the exact
revert performed.
"""

from __future__ import annotations

import pathlib
import re

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
DOC_LIB_JS = REPO_ROOT / "workspace" / "static" / "js" / "documentLibrary.js"


def _read() -> str:
    return DOC_LIB_JS.read_text(encoding="utf-8")


def _top_level_fn(src: str, name: str) -> str:
    """Extract a top-level (4-space-indented) `function name(...) { ... }` body.

    Mirrors ``test_applicant_round2_wave3_variantscoreboard.py``'s helper: the
    function's own closing brace is the first line consisting of a bare "}"
    (with the module's 4-space indent) with no further nesting -- matched via
    a non-greedy body up to the next same-indent closing brace.
    """
    m = re.search(rf"function {re.escape(name)}\([^)]*\)\s*\{{(.*?)\n    \}}", src, re.S)
    assert m, f"expected a function {name}(...) in the source"
    return m.group(1)


def _async_top_level_fn(src: str, name: str) -> str:
    m = re.search(rf"async function {re.escape(name)}\([^)]*\)\s*\{{(.*?)\n    \}}", src, re.S)
    assert m, f"expected an async function {name}(...) in the source"
    return m.group(1)


# ── the shared coverage/missing-terms formatter ─────────────────────────────


def test_fit_score_text_helper_exists():
    src = _read()
    assert re.search(r"function _applicantFitScoreText\(fitScores\)\s*\{", src), (
        "expected a top-level _applicantFitScoreText(fitScores) helper — reverting this "
        "removes the function entirely and this regex goes red"
    )


def test_fit_score_text_reads_coverage_and_missing_terms_off_the_real_shape():
    """Must read the ACTUAL wire shape (`coverage` + `missing_terms`), not a
    generic Object.values() scrape of the fit_scores dict (the old
    `_loadVariantLibrary` bug this replaces)."""
    body = _top_level_fn(_read(), "_applicantFitScoreText")
    assert "scores.coverage" in body
    assert "scores.missing_terms" in body


def test_fit_score_text_renders_a_percentage_not_a_raw_decimal():
    """The audit item's own example is "covers 82% of the posting's language"
    — a whole-number percentage, not the raw 0..1 float."""
    body = _top_level_fn(_read(), "_applicantFitScoreText")
    assert "Math.round" in body and "* 100" in body, (
        "expected the 0..1 coverage float to be converted to a rounded percentage"
    )


def test_fit_score_text_names_the_missing_terms_in_plain_language():
    body = _top_level_fn(_read(), "_applicantFitScoreText")
    assert "missing:" in body, (
        "expected the missing-terms clause to read plainly as 'missing: ...', "
        "matching the audit item's own example phrasing"
    )


def test_fit_score_text_hides_gracefully_when_coverage_is_absent():
    """Not every variant has been JD-matched — the helper must return the
    empty string (render nothing) rather than fabricate a 0% / NaN% line when
    `coverage` is missing or not a number."""
    body = _top_level_fn(_read(), "_applicantFitScoreText")
    assert re.search(r"Number\.isFinite\(coverage\)", body), (
        "expected a Number.isFinite(coverage) guard before formatting any output"
    )
    assert "return ''" in body


def test_fit_score_text_is_white_label_plain_language():
    """No internal jargon ('fit_scores', 'FR-RESUME', 'coverage:' raw field
    names) leaking into the rendered STRING TEMPLATE the user sees. (The
    function body legitimately reads `scores.coverage`/`scores.missing_terms`
    as field accessors — this checks the user-visible template text only.)"""
    body = _top_level_fn(_read(), "_applicantFitScoreText")
    template_lines = [ln for ln in body.splitlines() if "text" in ln and ("`" in ln or "+=" in ln)]
    joined = "\n".join(template_lines)
    assert "FR-" not in joined and "NFR-" not in joined
    assert "fit_scores" not in joined


# ── wired into the résumé-variant card (`_applicantCard`'s isVariant branch) ─


def test_applicant_card_renders_fit_score_alongside_existing_variant_actions():
    """Reverting this specific hunk (dropping the `if (isVariant) { const
    fitText = ... }` block added right after the "What I drew on" panel and
    before the actions row) makes this regex go red while leaving the
    sibling Download/Promote buttons untouched — confirms the new code is
    additive, not a replacement of the existing isVariant branch."""
    src = _read()
    body = _top_level_fn(src, "_applicantCard")
    assert "_applicantFitScoreText(item.fit_scores)" in body, (
        "expected _applicantCard's isVariant branch to read the real per-item fit_scores"
    )
    # Still additive: the pre-existing actions this task must not clobber.
    assert "Approve resume" in body
    assert "Download PDF" in body
    assert "Promote to base résumé" in body


def test_applicant_card_fit_score_line_is_gated_on_hidden_when_empty():
    body = _top_level_fn(_read(), "_applicantCard")
    m = re.search(r"const fitText = _applicantFitScoreText\(item\.fit_scores\);\s*\n\s*if \(fitText\)", body)
    assert m, "expected the fit-score element to be appended only when fitText is non-empty"


def test_applicant_card_fit_score_line_lives_in_the_card_body_not_the_actions_row():
    """Placement check: the fit-score div must be appended to `card` BEFORE
    the `actions` div is constructed, i.e. it is evidence in the card body
    near (not inside) the approve/download/promote actions row."""
    body = _top_level_fn(_read(), "_applicantCard")
    fit_idx = body.index("_applicantFitScoreText(item.fit_scores)")
    actions_idx = body.index("const actions = document.createElement('div');")
    assert fit_idx < actions_idx, (
        "the fit-score line must be added to the card body before the actions row is built"
    )


def test_applicant_card_fit_score_uses_text_content_not_html_injection():
    """Uses .textContent (auto-escaped) rather than concatenating fitText into
    innerHTML, since missing_terms ultimately derives from job-posting text."""
    body = _top_level_fn(_read(), "_applicantCard")
    m = re.search(r"fit\.textContent = fitText;", body)
    assert m, "expected the fit-score line to be set via .textContent, not innerHTML"


# ── the campaign-scoped resume-variant library (`_loadVariantLibrary`) ──────


def test_variant_library_reuses_the_same_shared_formatter():
    """`_loadVariantLibrary` (the campaign-scoped "Resume variants" panel,
    wired to the doclib-variant-lookup-btn) is the one place fit_scores was
    ALREADY reaching the browser before this task, via a broken generic
    Object.values()/Number() scrape. It must now reuse the same
    _applicantFitScoreText helper _applicantCard uses — not a second,
    divergent formatting of the same data."""
    body = _async_top_level_fn(_read(), "_loadVariantLibrary")
    assert "_applicantFitScoreText(v.fit_scores)" in body
    # The old buggy generic scrape must be gone.
    assert "Object.values(scores)" not in body
    assert "best fit" not in body


def test_variant_library_still_falls_back_to_not_scored():
    body = _async_top_level_fn(_read(), "_loadVariantLibrary")
    assert "'not scored'" in body


def test_variant_library_still_escapes_the_score_line_for_the_dom():
    """The formatted text is user/JD-derived; it must go through the same
    `esc()` helper as the rest of the row before landing in innerHTML."""
    body = _async_top_level_fn(_read(), "_loadVariantLibrary")
    assert re.search(r"\$\{esc\(scoreText\)\}", body), (
        "expected the score line to be HTML-escaped before interpolation into innerHTML"
    )


# ── node syntax sanity (mirrors every other documentLibrary.js test file) ──


def test_document_library_js_is_syntactically_valid(node_available):
    import subprocess

    result = subprocess.run(
        ["node", "--check", str(DOC_LIB_JS)], capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr


@pytest.fixture(scope="module")
def node_available():
    import shutil

    if shutil.which("node") is None:
        pytest.skip("node binary not on PATH")
