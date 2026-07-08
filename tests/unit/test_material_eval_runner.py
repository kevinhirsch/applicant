"""Hermetic tests for the golden-set material eval runner (P2-6).

These exercise the full runner wiring OFFLINE (no LLM key, no egress): golden-set
loading, the real MaterialService generation path via the deterministic fallback,
the tolerant judge-response parser, per-dimension aggregation, and the
per-dimension regression / floor gate. A live signal needs OPENROUTER_API_KEY and
is exercised by the eval CI lane, not here.
"""

from __future__ import annotations

import pytest

from applicant.evaluation.material_judge import _parse_judge_response
from applicant.evaluation.material_runner import (
    EVAL_RUBRIC,
    _render_markdown,
    build_llm,
    gate_report,
    load_golden_set,
    run_golden_set,
)


@pytest.mark.unit
def test_shipped_golden_set_is_labelled_synthetic_and_complete() -> None:
    gs = load_golden_set()
    assert "SYNTHETIC" in gs.provenance.upper()
    assert len(gs.profiles) == 4
    assert len(gs.postings) == 20
    assert len(gs.pairs) == 20
    # Every pair references profiles/postings that exist.
    for pair in gs.pairs:
        assert pair.profile_id in gs.profiles
        assert pair.posting_id in gs.postings


@pytest.mark.unit
def test_build_llm_returns_none_without_key() -> None:
    assert build_llm("some/model", api_key="") is None
    assert build_llm("", api_key="key") is None


@pytest.mark.unit
@pytest.mark.parametrize(
    "text,expected",
    [
        ('{"score": 5, "rationale": "great"}', 5),
        ('```json\n{"score": 2, "rationale": "weak"}\n```', 2),
        ("Here is my assessment:\n{\"score\": 4, \"rationale\": \"good\"}", 4),
        ("I would rate this a score: 1 overall.", 1),
        ("", 3),
        ("no parseable content here", 3),
        ('{"score": 9}', 5),  # clamped by caller; parser returns raw 9
    ],
)
def test_judge_response_parser_is_tolerant(text: str, expected: int) -> None:
    score, rationale = _parse_judge_response(text)
    # The parser itself does not clamp; the caller does. For the >5 case we only
    # assert it extracted the raw integer.
    if text == '{"score": 9}':
        assert score == 9
    else:
        assert score == expected
    assert isinstance(rationale, str) and rationale


@pytest.mark.unit
def test_offline_run_generates_and_judges_without_egress() -> None:
    gs = load_golden_set()
    report = run_golden_set(
        gs,
        gen_llm=None,
        judge_llm=None,
        gen_model="(offline)",
        judge_model="(offline)",
        max_cases=3,
    )
    assert report.live is False
    assert "OFFLINE" in report.note
    assert report.material_count > 0
    # Provenance is carried through verbatim (honesty).
    assert report.provenance == gs.provenance
    # Every rubric dimension is scored.
    assert set(report.dimension_means) == set(EVAL_RUBRIC)
    # The deterministic fallback never masquerades as a real generation, but it is
    # also not a "degraded" (ladder-exhausted) fallback — no model was wired.
    assert report.degraded_count == 0


@pytest.mark.unit
def test_floor_gate_fails_below_min_score() -> None:
    gs = load_golden_set()
    report = run_golden_set(
        gs, gen_llm=None, judge_llm=None, gen_model="x", judge_model="x", max_cases=2
    )
    # An impossibly high floor must fail; a floor of 0 must pass.
    assert gate_report(report, min_score=5.5).passed is False
    assert gate_report(report, min_score=0.0).passed is True


@pytest.mark.unit
def test_regression_gate_fails_when_dimension_drops_vs_baseline() -> None:
    gs = load_golden_set()
    report = run_golden_set(
        gs, gen_llm=None, judge_llm=None, gen_model="x", judge_model="x", max_cases=2
    )
    # Baseline sets every dimension well above the observed means => regression.
    inflated = {d: 5.0 for d in report.dimension_means}
    outcome = gate_report(
        report, baseline={"dimension_means": inflated}, regression_threshold=0.5
    )
    assert outcome.passed is False
    assert outcome.failures
    # A baseline equal to the observed means => no regression.
    same = dict(report.dimension_means)
    assert gate_report(report, baseline={"dimension_means": same}).passed is True


@pytest.mark.unit
def test_score_regex_rejects_multi_digit_values() -> None:
    """"score: 10" must not read as 1 — it falls to the honest unparsed default."""
    score, rationale = _parse_judge_response("I would rate this a score: 10 overall.")
    assert score == 3
    assert "could not be parsed" in rationale


@pytest.mark.unit
def test_max_cases_zero_runs_zero_cases() -> None:
    """An explicit cap of 0 means zero cases (dry wiring check), not uncapped."""
    gs = load_golden_set()
    report = run_golden_set(
        gs, gen_llm=None, judge_llm=None, gen_model="x", judge_model="x", max_cases=0
    )
    assert report.case_count == 0
    assert report.material_count == 0


@pytest.mark.unit
def test_skipped_unresolved_pairs_are_counted_apart_from_cases() -> None:
    """A pair naming an unknown profile/posting is skipped and reported as such;
    case_count reflects only what actually ran (H-series)."""
    import dataclasses

    gs = load_golden_set()
    bad_pair = dataclasses.replace(gs.pairs[0], profile_id="prof-does-not-exist")
    gs2 = dataclasses.replace(gs, pairs=[gs.pairs[0], bad_pair])
    report = run_golden_set(
        gs2, gen_llm=None, judge_llm=None, gen_model="x", judge_model="x"
    )
    assert report.case_count == 1
    assert report.skipped_count == 1
    md = _render_markdown(report, gate_report(report, min_score=0.0))
    assert "Skipped (unresolved ids, not run):** 1" in md


@pytest.mark.unit
def test_markdown_note_blockquote_is_contiguous() -> None:
    """The two note paragraphs form ONE blockquote via a `>` continuation line
    (markdownlint MD028: no bare blank line inside a blockquote)."""
    gs = load_golden_set()
    report = run_golden_set(
        gs, gen_llm=None, judge_llm=None, gen_model="x", judge_model="x", max_cases=1
    )
    md = _render_markdown(report, gate_report(report, min_score=0.0))
    md_lines = md.splitlines()
    quote_idx = [i for i, ln in enumerate(md_lines) if ln.startswith(">")]
    assert quote_idx, "expected blockquote lines"
    # The quote block is contiguous: no bare blank line between two `>` lines.
    for a, b in zip(quote_idx, quote_idx[1:], strict=False):
        assert b == a + 1, f"blockquote broken by a blank line at line {a + 1}"


@pytest.mark.unit
def test_markdown_report_escapes_pipes_in_dynamic_cells() -> None:
    """Case ids are ``profile|posting`` — an unescaped pipe splits the table column."""
    gs = load_golden_set()
    report = run_golden_set(
        gs, gen_llm=None, judge_llm=None, gen_model="x", judge_model="x", max_cases=1
    )
    md = _render_markdown(report, gate_report(report, min_score=0.0))
    table = md.split("## Per-material results", 1)[1]
    rows = [ln for ln in table.splitlines() if ln.startswith("| prof-")]
    assert rows, "expected at least one per-material row"
    for row in rows:
        # 5 columns => exactly 6 unescaped pipes per row; the case id's own
        # pipe must be escaped as \| so it does not add a column.
        assert row.count("|") - row.count("\\|") == 6
        assert "\\|" in row  # the profile|posting separator, escaped


@pytest.mark.unit
def test_fabrication_cross_check_is_report_only_by_default() -> None:
    gs = load_golden_set()
    report = run_golden_set(
        gs, gen_llm=None, judge_llm=None, gen_model="x", judge_model="x", max_cases=2
    )
    # Default (None) never hard-fails on the deterministic count, even if nonzero.
    report.fabrication_material_count = 3
    assert gate_report(report, min_score=0.0).passed is True
    # Opting in with a hard cap turns it into a failure.
    assert gate_report(report, min_score=0.0, max_fabrication_materials=0).passed is False
