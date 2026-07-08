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

    def test_wrapped_sentence_still_surfaces_the_flagged_proper_noun(self) -> None:
        # A prose sentence wrapped across a newline pushes the proper noun to the
        # start of a LINE without starting a SENTENCE. The document-level guard
        # flags it; the per-line provenance view must agree — a per-line re-run of
        # the extractor would reset sentence-initial state and silently drop it.
        generated = "I worked at\nStanford."
        combined = "\n".join(text for _, text in SOURCES)
        guard = set(unsupported_prose_claims(combined, generated))
        assert "Stanford" in guard  # the guard flags the wrapped proper noun
        out = trace_line_provenance(SOURCES, generated, prose=True)
        by_line = {lp.line: {f.token: f for f in lp.facts} for lp in out}
        # ...and the provenance view lists it, unsourced, on its own line.
        assert "Stanford" in by_line["Stanford."]
        assert by_line["Stanford."]["Stanford"].unsourced
        traced_unsourced = {f.token for lp in out for f in lp.facts if f.unsourced}
        assert traced_unsourced == guard

    def test_sentence_initial_sourced_token_still_shows_its_source(self) -> None:
        # The guard reads a sentence-initial capital as grammar (never flags it),
        # but when the writer leads a sentence with a REAL sourced detail the
        # provenance view must still show its support — not report a "complete"
        # trace that omits a visible fact (Greptile on #749).
        generated = "Python powered the migration."
        combined = "\n".join(text for _, text in SOURCES)
        assert "Python" not in unsupported_prose_claims(combined, generated)
        out = trace_line_provenance(SOURCES, generated, prose=True)
        facts = {f.token: f for f in out[0].facts}
        assert facts["Python"].sources == ("your profile (Skills)",)

    def test_sentence_initial_unsupported_word_stays_grammar_not_flagged(self) -> None:
        # An UNSOURCED sentence starter is exactly what the guard's
        # sentence-initial rule protects ("Yesterday I applied...") — it must
        # not appear in facts at all, keeping unsourced == the guard's flags.
        generated = "Zanzibar powered the migration."
        combined = "\n".join(text for _, text in SOURCES)
        guard = set(unsupported_prose_claims(combined, generated))
        assert "Zanzibar" not in guard
        out = trace_line_provenance(SOURCES, generated, prose=True)
        tokens = {f.token for lp in out for f in lp.facts}
        assert "Zanzibar" not in tokens
        traced_unsourced = {f.token for lp in out for f in lp.facts if f.unsourced}
        assert traced_unsourced == guard

    def test_empty_generated_returns_nothing(self) -> None:
        assert trace_line_provenance(SOURCES, "", prose=True) == ()

    def test_fact_trace_unsourced_property(self) -> None:
        assert FactTrace(token="x").unsourced is True
        assert FactTrace(token="x", sources=("a",)).unsourced is False
