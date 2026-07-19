from __future__ import annotations

import pytest

from applicant.core.rules.truthfulness import (
    FabricationGrade,
    FactTrace,
    LineProvenance,
    TruthPolicy,
    coerce_truth_policy,
    grade_unsupported_claims,
    policy_blocks,
    trace_line_provenance,
    unsupported_claims,
    unsupported_prose_claims,
)


@pytest.fixture(autouse=True)
def _no_cache() -> None:
    """Parallel-execution safety: clear any module-level cache (none yet, but
    prepares for xdist)."""
    pass


class TestUnsupportedClaims:
    """unsupported_claims: whole-token matching of claims against source text.

    Checks that claim tokens absent from the source are flagged, figures are
    value-matched (40k ≡ 40000), and tokens with digits skip the word check.
    """

    def test_empty_generated(self) -> None:
        assert unsupported_claims("I know Python", "") == []

    def test_all_tokens_supported(self) -> None:
        result = unsupported_claims(
            "Python Kubernetes Django", "Python and Django"
        )
        assert result == []

    def test_unsupported_tokens_flagged(self) -> None:
        result = unsupported_claims(
            "Python", "I know Python and Kubernetes"
        )
        assert "Kubernetes" in result
        assert "Python" not in result

    def test_case_insensitive_matching(self) -> None:
        result = unsupported_claims("python", "Python is great")
        assert result == []

    def test_figure_value_matching(self) -> None:
        result = unsupported_claims(
            "Led a team of 40,000 people", "Led 40k people"
        )
        assert result == []

    def test_figure_mismatch_flagged(self) -> None:
        result = unsupported_claims(
            "Managed 10 people", "Managed 1000 people"
        )
        assert any("1000" in t or "people" in t for t in result)

    def test_dollar_figure(self) -> None:
        result = unsupported_claims(
            "Saved $30,000,000", "Saved $30M"
        )
        assert result == []

    def test_multiple_unsupported(self) -> None:
        result = unsupported_claims(
            "Python", "Python Kubernetes Django AWS"
        )
        assert "Kubernetes" in result
        assert "Django" in result
        assert "AWS" in result
        assert "Python" not in result

    def test_digit_tokens_skip_word_check(self) -> None:
        # Digit-containing tokens (2024, v3) skip the WORD check and are
        # instead value-matched. With matching values in the source and
        # no extra non-claim words, they should not be flagged.
        result = unsupported_claims(
            "Release 2024 v3 is here", "Year 2024 includes release v3"
        )
        assert result == []


class TestUnsupportedProseClaims:
    """unsupported_prose_claims: entity-shaped token matching for free prose.

    Only flags entity-shaped tokens (proper nouns, acronyms, camelCase tech) that
    are absent from the source. Sentence-initial capitals are treated as grammar.
    """

    def test_empty_generated(self) -> None:
        assert unsupported_prose_claims("Some source", "") == []

    def test_ordinary_prose_not_flagged(self) -> None:
        result = unsupported_prose_claims(
            "Worked on backend systems.",
            "I have extensive experience building and maintaining backend platforms."
        )
        assert result == []

    def test_unsupported_entity_flagged(self) -> None:
        result = unsupported_prose_claims(
            "Worked at a startup.",
            "I interned at Stanford University."
        )
        assert "Stanford" in result

    def test_supported_entity_not_flagged(self) -> None:
        result = unsupported_prose_claims(
            "Stanford University intern",
            "I interned at Stanford University."
        )
        assert result == []

    def test_acronym_detected(self) -> None:
        result = unsupported_prose_claims(
            "Built data pipelines.",
            "I built ETL and AWS infrastructure."
        )
        assert "AWS" in result

    def test_sentence_initial_skipped(self) -> None:
        result = unsupported_prose_claims(
            "",
            "Python is a great language. Based on my experience."
        )
        # "Python" is sentence-initial so it's treated as grammar;
        # "Based" is sentence-initial too. Mid-sentence proper noun not present.
        for token in result:
            # Only check if Python appears mid-sentence, not sentence-initial
            assert token != "Python"

    def test_contractions_split(self) -> None:
        result = unsupported_prose_claims(
            "Worked on software.",
            "I've worked on software."
        )
        # "I've" splits to "I" and "ve" — neither is entity-shaped
        assert result == []

    def test_mid_sentence_proper_noun_flagged(self) -> None:
        result = unsupported_prose_claims(
            "Worked at a small firm.",
            "My time at Google taught me a lot."
        )
        assert "Google" in result

    def test_figure_value_matching_in_prose(self) -> None:
        result = unsupported_prose_claims(
            "Led 40000 people",
            "Led 40k people across teams."
        )
        assert result == []

    def test_camel_case_tech(self) -> None:
        result = unsupported_prose_claims(
            "Built web apps.",
            "I used FastAPI and PostgreSQL."
        )
        assert "FastAPI" in result
        assert "PostgreSQL" in result


class TestFabricationGrade:
    """FabricationGrade enum values."""

    def test_values(self) -> None:
        assert FabricationGrade.CLEAN.value == "clean"
        assert FabricationGrade.REVIEW.value == "review"
        assert FabricationGrade.VIOLATION.value == "violation"

    def test_str_enum_behavior(self) -> None:
        assert isinstance(FabricationGrade.CLEAN, str)
        assert FabricationGrade.CLEAN.value == "clean"

    def test_membership(self) -> None:
        assert FabricationGrade("clean") is FabricationGrade.CLEAN
        assert FabricationGrade("review") is FabricationGrade.REVIEW
        assert FabricationGrade("violation") is FabricationGrade.VIOLATION


class TestGradeUnsupportedClaims:
    """grade_unsupported_claims: graded wrapper around fabrication checkers."""

    def test_clean_zero_flags(self) -> None:
        grade, flagged = grade_unsupported_claims(
            "Python Django", "Python and Django"
        )
        assert grade is FabricationGrade.CLEAN
        assert flagged == []

    def test_review_one_flag(self) -> None:
        grade, _ = grade_unsupported_claims(
            "Python", "Python and Kubernetes"
        )
        assert grade is FabricationGrade.REVIEW

    def test_violation_two_flags(self) -> None:
        grade, _ = grade_unsupported_claims(
            "Python", "Python Kubernetes Django"
        )
        assert grade is FabricationGrade.VIOLATION

    def test_violation_with_custom_threshold(self) -> None:
        grade, _ = grade_unsupported_claims(
            "Python", "Python Kubernetes",
            violation_threshold=3,
        )
        assert grade is FabricationGrade.REVIEW

    def test_prose_mode(self) -> None:
        grade, _ = grade_unsupported_claims(
            "Worked on systems.",
            "I interned at Stanford University.",
            prose=True,
        )
        assert grade is FabricationGrade.VIOLATION


class TestTruthPolicy:
    """TruthPolicy enum values."""

    def test_values(self) -> None:
        assert TruthPolicy.BALANCED.value == "balanced"
        assert TruthPolicy.STRICT.value == "strict"

    def test_str_enum_behavior(self) -> None:
        assert TruthPolicy.BALANCED.value == "balanced"

    def test_membership(self) -> None:
        assert TruthPolicy("balanced") is TruthPolicy.BALANCED
        assert TruthPolicy("strict") is TruthPolicy.STRICT


class TestCoerceTruthPolicy:
    """coerce_truth_policy: best-effort parse with safe default."""

    def test_policy_instance_returned(self) -> None:
        assert coerce_truth_policy(TruthPolicy.STRICT) is TruthPolicy.STRICT

    def test_string_balanced(self) -> None:
        assert coerce_truth_policy("balanced") is TruthPolicy.BALANCED

    def test_string_strict(self) -> None:
        assert coerce_truth_policy("strict") is TruthPolicy.STRICT

    def test_case_insensitive(self) -> None:
        assert coerce_truth_policy("BALANCED") is TruthPolicy.BALANCED

    def test_default_for_bad_value(self) -> None:
        assert coerce_truth_policy("unknown") is TruthPolicy.BALANCED
        assert coerce_truth_policy(42) is TruthPolicy.BALANCED
        assert coerce_truth_policy(None) is TruthPolicy.BALANCED


class TestPolicyBlocks:
    """policy_blocks: whether flagged facts should hard-block generation."""

    def test_no_flags_no_block(self) -> None:
        assert policy_blocks([], TruthPolicy.STRICT) is False
        assert policy_blocks([], TruthPolicy.BALANCED) is False

    def test_strict_blocks(self) -> None:
        assert policy_blocks(["Kubernetes"], TruthPolicy.STRICT) is True

    def test_balanced_never_blocks(self) -> None:
        assert policy_blocks(["Kubernetes"], TruthPolicy.BALANCED) is False
        assert policy_blocks(["Kubernetes", "Django"], TruthPolicy.BALANCED) is False


class TestFactTrace:
    """FactTrace dataclass for provenance."""

    def test_default_unsourced(self) -> None:
        ft = FactTrace(token="Kubernetes")
        assert ft.token == "Kubernetes"
        assert ft.sources == ()
        assert ft.unsourced is True

    def test_with_sources(self) -> None:
        ft = FactTrace(token="Python", sources=("resume",))
        assert ft.token == "Python"
        assert ft.sources == ("resume",)
        assert ft.unsourced is False

    def test_multiple_sources(self) -> None:
        ft = FactTrace(token="AWS", sources=("base", "profile"))
        assert ft.sources == ("base", "profile")

    def test_frozen(self) -> None:
        ft = FactTrace(token="Python")
        with pytest.raises(Exception):
            ft.token = "Java"  # type: ignore[misc]


class TestLineProvenance:
    """LineProvenance dataclass for per-line provenance."""

    def test_default_empty_facts(self) -> None:
        lp = LineProvenance(line="I know Python.")
        assert lp.line == "I know Python."
        assert lp.facts == ()

    def test_with_facts(self) -> None:
        ft = FactTrace(token="Python", sources=("resume",))
        lp = LineProvenance(line="I know Python.", facts=(ft,))
        assert len(lp.facts) == 1
        assert lp.facts[0].token == "Python"

    def test_frozen(self) -> None:
        lp = LineProvenance(line="test")
        with pytest.raises(Exception):
            lp.line = "changed"  # type: ignore[misc]


class TestTraceLineProvenance:
    """trace_line_provenance: per-line provenance against ground-truth sources."""

    def test_empty_generated(self) -> None:
        result = trace_line_provenance(
            [("resume", "Python engineer")], ""
        )
        assert result == ()

    def test_supported_token_traced(self) -> None:
        result = trace_line_provenance(
            [("resume", "Python Django engineer")],
            "I am a Python engineer.",
        )
        assert len(result) == 1
        lp = result[0]
        assert len(lp.facts) >= 1
        python_fact = next(
            (f for f in lp.facts if f.token == "Python"), None
        )
        assert python_fact is not None
        assert "resume" in python_fact.sources

    def test_unsourced_token_flagged(self) -> None:
        result = trace_line_provenance(
            [("resume", "Python engineer")],
            "I am a Python and Kubernetes engineer.",
        )
        assert len(result) == 1
        lp = result[0]
        kubernetes_fact = next(
            (f for f in lp.facts if f.token == "Kubernetes"), None
        )
        assert kubernetes_fact is not None
        assert kubernetes_fact.unsourced is True

    def test_prose_mode(self) -> None:
        result = trace_line_provenance(
            [("resume", "Software engineer with data skills.")],
            "I have experience with Google Cloud and AWS.",
            prose=True,
        )
        assert len(result) >= 1
        all_tokens = [f.token for lp in result for f in lp.facts]
        assert "Google" in all_tokens

    def test_multiple_sources(self) -> None:
        result = trace_line_provenance(
            [
                ("resume", "Python engineer"),
                ("profile", "AWS certified"),
            ],
            "Python and AWS engineer.",
        )
        assert len(result) >= 1
        lp = result[0]
        aws_fact = next(
            (f for f in lp.facts if f.token == "AWS"), None
        )
        assert aws_fact is not None
        assert "profile" in aws_fact.sources
