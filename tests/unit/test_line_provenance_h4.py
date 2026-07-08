"""Unit tests for the pure line-provenance rule (H4 — visible provenance).

``trace_line_provenance`` makes the fabrication guard's verdict LEGIBLE: for each
line of a generated document it names WHICH labelled ground-truth component (a
profile attribute, the base résumé, the posting context) supports each fact-class
token, and returns unsourced tokens with empty sources so the review UI flags
them instead of hiding them. It must reuse the guard's own tokenizers/matchers so
the provenance view can never disagree with ``unsupported_claims`` /
``unsupported_prose_claims``.
"""

from __future__ import annotations

from applicant.core.rules.truthfulness import (
    FactTrace,
    trace_line_provenance,
    unsupported_claims,
    unsupported_prose_claims,
)

SOURCES = [
    ("your profile (Skills)", "Python"),
    ("your base résumé", "I built data pipelines at Acme Corp, cutting p99 latency 38%."),
    ("the job posting you're applying to", "Globex Senior Engineer"),
]


class TestTraceLineProvenance:
    def test_supported_tokens_name_their_source(self) -> None:
        out = trace_line_provenance(SOURCES, "I used Python at Acme.", prose=True)
        assert len(out) == 1
        facts = {f.token: f.sources for f in out[0].facts}
        assert facts["Python"] == ("your profile (Skills)",)
        assert facts["Acme"] == ("your base résumé",)

    def test_unsourced_tokens_are_flagged_not_hidden(self) -> None:
        out = trace_line_provenance(SOURCES, "I ran Kubernetes at Stanford.", prose=True)
        facts = {f.token: f for f in out[0].facts}
        assert facts["Kubernetes"].unsourced
        assert facts["Stanford"].sources == ()

    def test_posting_context_supports_the_addressee(self) -> None:
        out = trace_line_provenance(SOURCES, "Dear Globex team,", prose=True)
        facts = {f.token: f.sources for f in out[0].facts}
        assert facts["Globex"] == ("the job posting you're applying to",)

    def test_numbers_are_value_matched_not_spelling_matched(self) -> None:
        out = trace_line_provenance(SOURCES, "I cut latency 38% at Acme.", prose=True)
        facts = {f.token: f.sources for f in out[0].facts}
        # "38%" in the draft matches the source's "38%" by VALUE ("38" token).
        assert any("38" in tok for tok in facts)
        for tok, sources in facts.items():
            if "38" in tok:
                assert sources == ("your base résumé",)

    def test_a_token_supported_by_multiple_sources_lists_them_all(self) -> None:
        sources = [("your profile (Skills)", "Python"), ("your base résumé", "Python work")]
        out = trace_line_provenance(sources, "Python", prose=False)
        assert out[0].facts[0].sources == (
            "your profile (Skills)",
            "your base résumé",
        )

    def test_blank_lines_are_skipped_and_tokens_deduped_per_line(self) -> None:
        out = trace_line_provenance(SOURCES, "Python Python\n\n  \nAcme", prose=False)
        assert len(out) == 2
        assert [f.token for f in out[0].facts] == ["Python"]

    def test_unsourced_set_matches_the_guard_exactly_prose(self) -> None:
        generated = "I deployed Python on Kubernetes at Stanford in 2015."
        combined = "\n".join(text for _, text in SOURCES)
        guard = set(unsupported_prose_claims(combined, generated))
        out = trace_line_provenance(SOURCES, generated, prose=True)
        traced_unsourced = {f.token for lp in out for f in lp.facts if f.unsourced}
        assert traced_unsourced == guard

    def test_unsourced_set_matches_the_guard_exactly_strict(self) -> None:
        generated = "Built kubernetes dashboards\nWrote Python pipelines"
        combined = "\n".join(text for _, text in SOURCES)
        guard = set(unsupported_claims(combined, generated))
        out = trace_line_provenance(SOURCES, generated, prose=False)
        traced_unsourced = {f.token for lp in out for f in lp.facts if f.unsourced}
        assert traced_unsourced == guard

    def test_lowercase_fabricated_skill_still_unsourced_strict(self) -> None:
        out = trace_line_provenance(SOURCES, "kubernetes expertise", prose=False)
        facts = {f.token: f for f in out[0].facts}
        assert facts["kubernetes"].unsourced

    def test_empty_generated_returns_nothing(self) -> None:
        assert trace_line_provenance(SOURCES, "", prose=True) == ()

    def test_fact_trace_unsourced_property(self) -> None:
        assert FactTrace(token="x").unsourced is True
        assert FactTrace(token="x", sources=("a",)).unsourced is False
