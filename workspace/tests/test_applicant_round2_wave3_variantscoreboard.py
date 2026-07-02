"""Regression coverage for the per-variant A/B scoreboard (design-audit Top-25
#19), confined to ``static/js/applicantDebug.js``'s Variants tab (``_renderVariants``).

Follows the convention of ``test_applicant_round1_observability.py``: every
fact is read from the actual static file content via ``pathlib`` + regex — no
browser, no DOM, no real socket (this module does top-level launcher-wiring
work on import, so it is not importable under a bare
``node --input-type=module`` without a DOM shim; same precedent as round-1).

Engine-side coverage (the honest usage-count + interview-rate computation
itself, ``AdminQueryService.variant_library``) lives in
``tests/unit/test_cov_round2_variantscoreboard.py`` — hermetic, no real DB.

Each assertion here was verified, by hand, to actually go red when the
underlying fix is reverted (temporarily restored the pre-fix ``_renderVariants``
body, reran, saw the assertion fail with a real AssertionError, restored).
"""

from __future__ import annotations

import pathlib
import re

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
DEBUG_JS = REPO_ROOT / "workspace" / "static" / "js" / "applicantDebug.js"


def _read() -> str:
    return DEBUG_JS.read_text(encoding="utf-8")


def _top_level_fn(src: str, name: str) -> str:
    """Extract a top-level (unindented) `function name(...) { ... }` body.

    Same convention as ``test_applicant_round1_observability.py``: the
    function's own closing brace is the first line consisting of a bare "}"
    with no leading whitespace.
    """
    m = re.search(rf"function {re.escape(name)}\([^)]*\)\s*\{{(.*?)\n\}}", src, re.S)
    assert m, f"expected a top-level function {name}(...) in the source"
    return m.group(1)


def _async_top_level_fn(src: str, name: str) -> str:
    m = re.search(rf"async function {re.escape(name)}\([^)]*\)\s*\{{(.*?)\n\}}", src, re.S)
    assert m, f"expected a top-level async function {name}(...) in the source"
    return m.group(1)


# ── usage count + interview rate are read straight off the engine payload ──


def test_render_variants_reads_uses_and_interview_rate_off_each_variant():
    body = _async_top_level_fn(_read(), "_renderVariants")
    assert "v.uses" in body, "each row must read the engine-computed uses count (v.uses)"
    assert "v.interview_rate" in body, (
        "each row must read the engine-computed interview_rate (v.interview_rate)"
    )


def test_render_variants_shows_not_enough_data_state_instead_of_fabricating_a_rate():
    """interview_rate is ``None`` until a variant has data (see the engine
    test suite) — the row must show an honest "not enough data yet" state in
    that case, never a fabricated 0%/blank rate."""
    body = _async_top_level_fn(_read(), "_renderVariants")
    m = re.search(r"rateText\s*=\s*v\.interview_rate\s*!=\s*null\s*\?([^:]*):(.*)", body)
    assert m, "expected a rateText ternary gated on `v.interview_rate != null`"
    fallback = m.group(2)
    assert "not enough data yet" in fallback, (
        "the null-rate fallback branch must read 'not enough data yet', not a fabricated number"
    )


def test_render_variants_rows_still_use_the_shared_list_row_treatment():
    """Sibling-list convention (#93/#100): no new visual kit, reuse
    `.applicant-debug-list-row` / `.applicant-debug-list` like Sources/Tools/
    Insights already do — not a fresh `.admin-card`-per-item stack — and the
    new usage/rate line must live INSIDE that same row treatment, not a
    separately-styled addition."""
    body = _async_top_level_fn(_read(), "_renderVariants")
    assert "applicant-debug-list-row" in body
    assert "applicant-debug-list" in body
    assert "admin-card" not in body, (
        "Variants rows must not regress back to the old .admin-card-per-item stacking"
    )
    row_div = re.search(r"<div class=\"applicant-debug-list-row\">(.*?)</div>\s*`;", body, re.S)
    assert row_div, "expected the per-variant row template literal"
    assert "usesText" in row_div.group(1) and "rateText" in row_div.group(1), (
        "the usage-count/interview-rate line must render inside the shared row template"
    )


# ── the "use this variant more/less" nudge ──────────────────────────────────


def test_variant_nudge_function_exists_and_is_wired_into_render_variants():
    src = _read()
    assert re.search(r"function _variantNudge\(variants\)\s*\{", src), (
        "expected a top-level _variantNudge(variants) helper"
    )
    render_body = _async_top_level_fn(src, "_renderVariants")
    assert "_variantNudge(variants)" in render_body, (
        "_renderVariants must call _variantNudge and render its output"
    )


def test_variant_nudge_requires_at_least_two_tracked_uses_on_each_side():
    """A single lucky/unlucky application must not produce a confident-sounding
    claim — both variants being compared need >= 2 tracked uses."""
    body = _top_level_fn(_read(), "_variantNudge")
    m = re.search(r"\(v\.uses \|\| 0\)\s*>=\s*(\d+)", body)
    assert m, "expected the comparable-variants filter to gate on a minimum uses count"
    assert int(m.group(1)) >= 2, "the minimum-uses gate must be at least 2, not a single sample"


def test_variant_nudge_requires_a_clear_gap_before_speaking_up():
    """The nudge must not fire on a marginal difference — only a clear gap."""
    body = _top_level_fn(_read(), "_variantNudge")
    m = re.search(r"best\.interview_rate\s*-\s*worst\.interview_rate\s*<\s*(\d+)", body)
    assert m, "expected a minimum percentage-point gap guard before nudging"
    assert int(m.group(1)) >= 10, "the gap guard must be a meaningfully large threshold"


def test_variant_nudge_names_the_stronger_and_weaker_variant_in_plain_language():
    body = _top_level_fn(_read(), "_variantNudge")
    assert "consider using" in body, "the nudge copy must be an actionable plain-language nudge"
    assert "bestLabel" in body and "worstLabel" in body, (
        "the nudge must name which variant to use more, not speak in the abstract"
    )


def test_variant_label_helper_reused_by_both_rows_and_nudge():
    """Rows and the nudge must name a variant the same way (no drift between
    what a row says and what the nudge calls it)."""
    src = _read()
    assert re.search(r"function _variantLabel\(v\)\s*\{", src)
    nudge_body = _top_level_fn(src, "_variantNudge")
    assert "_variantLabel(best)" in nudge_body
    assert "_variantLabel(worst)" in nudge_body
