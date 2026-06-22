"""Unit tests for graded fabrication detection (FR-HARVEST-TRUTHTIER).

Covers:
- FabricationGrade enum values and string behaviour.
- grade_unsupported_claims: CLEAN / REVIEW / VIOLATION tiers for resume bullets.
- grade_unsupported_claims(prose=True): same tiers for free-prose cover letters.
- Custom violation_threshold.
- Tuple return structure (grade, flagged list).
- Backward-compat: existing unsupported_claims / unsupported_prose_claims unchanged.
"""

from __future__ import annotations

from applicant.core.rules.truthfulness import (
    FabricationGrade,
    grade_unsupported_claims,
    unsupported_claims,
    unsupported_prose_claims,
)

# ---------------------------------------------------------------------------
# FabricationGrade enum
# ---------------------------------------------------------------------------


class TestFabricationGrade:
    def test_values_are_strings(self) -> None:
        assert FabricationGrade.CLEAN == "clean"
        assert FabricationGrade.REVIEW == "review"
        assert FabricationGrade.VIOLATION == "violation"

    def test_str_subclass(self) -> None:
        assert isinstance(FabricationGrade.CLEAN, str)

    def test_three_members(self) -> None:
        assert len(list(FabricationGrade)) == 3

    def test_ordering_by_severity(self) -> None:
        grades = [FabricationGrade.CLEAN, FabricationGrade.REVIEW, FabricationGrade.VIOLATION]
        assert grades[0] != grades[1] != grades[2]


# ---------------------------------------------------------------------------
# grade_unsupported_claims — resume-bullet mode (prose=False)
# ---------------------------------------------------------------------------


TRUE_RESUME = "Python SQL PostgreSQL FastAPI Docker five years experience"


class TestGradeClean:
    def test_fully_supported_returns_clean(self) -> None:
        grade, flagged = grade_unsupported_claims(TRUE_RESUME, "Python and SQL.")
        assert grade == FabricationGrade.CLEAN
        assert flagged == []

    def test_empty_generated_is_clean(self) -> None:
        grade, flagged = grade_unsupported_claims(TRUE_RESUME, "")
        assert grade == FabricationGrade.CLEAN
        assert flagged == []

    def test_empty_both_is_clean(self) -> None:
        grade, flagged = grade_unsupported_claims("", "")
        assert grade == FabricationGrade.CLEAN
        assert flagged == []

    def test_stopwords_only_is_clean(self) -> None:
        grade, flagged = grade_unsupported_claims(TRUE_RESUME, "I have worked with the team.")
        assert grade == FabricationGrade.CLEAN
        assert flagged == []


class TestGradeReview:
    def test_single_unsupported_token_is_review(self) -> None:
        grade, flagged = grade_unsupported_claims(TRUE_RESUME, "Expert in Kubernetes.")
        assert grade == FabricationGrade.REVIEW
        assert "Kubernetes" in flagged or "kubernetes" in [f.lower() for f in flagged]

    def test_flagged_list_nonempty_on_review(self) -> None:
        grade, flagged = grade_unsupported_claims(TRUE_RESUME, "Expert in Kubernetes.")
        assert len(flagged) == 1

    def test_review_not_clean_not_violation(self) -> None:
        grade, _ = grade_unsupported_claims(TRUE_RESUME, "Expert in Kubernetes.")
        assert grade != FabricationGrade.CLEAN
        assert grade != FabricationGrade.VIOLATION


class TestGradeViolation:
    def test_two_unsupported_tokens_is_violation(self) -> None:
        grade, flagged = grade_unsupported_claims(
            TRUE_RESUME, "Expert in Kubernetes and TensorFlow."
        )
        assert grade == FabricationGrade.VIOLATION
        assert len(flagged) >= 2

    def test_many_unsupported_tokens_is_violation(self) -> None:
        grade, flagged = grade_unsupported_claims(
            TRUE_RESUME, "Stanford PhD in Kubernetes TensorFlow Spark."
        )
        assert grade == FabricationGrade.VIOLATION
        assert len(flagged) >= 2


class TestCustomViolationThreshold:
    def test_threshold_1_makes_single_token_a_violation(self) -> None:
        grade, _ = grade_unsupported_claims(
            TRUE_RESUME, "Expert in Kubernetes.", violation_threshold=1
        )
        assert grade == FabricationGrade.VIOLATION

    def test_threshold_3_makes_two_tokens_review(self) -> None:
        grade, flagged = grade_unsupported_claims(
            TRUE_RESUME, "Kubernetes and TensorFlow.", violation_threshold=3
        )
        assert grade == FabricationGrade.REVIEW
        assert len(flagged) == 2

    def test_threshold_3_three_tokens_is_violation(self) -> None:
        grade, _ = grade_unsupported_claims(
            TRUE_RESUME, "Kubernetes TensorFlow Spark.", violation_threshold=3
        )
        assert grade == FabricationGrade.VIOLATION


# ---------------------------------------------------------------------------
# grade_unsupported_claims — free-prose mode (prose=True)
# ---------------------------------------------------------------------------


TRUE_RESUME_PROSE = "Python machine learning FastAPI AWS cloud infrastructure five years"


class TestGradeProseClean:
    def test_clean_letter_with_supported_entities(self) -> None:
        letter = "I have five years of Python experience building AWS cloud infrastructure."
        grade, flagged = grade_unsupported_claims(TRUE_RESUME_PROSE, letter, prose=True)
        assert grade == FabricationGrade.CLEAN
        assert flagged == []

    def test_empty_letter_is_clean(self) -> None:
        grade, flagged = grade_unsupported_claims(TRUE_RESUME_PROSE, "", prose=True)
        assert grade == FabricationGrade.CLEAN
        assert flagged == []


class TestGradeProseReview:
    def test_single_invented_entity_is_review(self) -> None:
        letter = "I hold a Stanford degree with expertise in Python."
        grade, flagged = grade_unsupported_claims(TRUE_RESUME_PROSE, letter, prose=True)
        assert grade == FabricationGrade.REVIEW
        assert "Stanford" in flagged

    def test_single_fabricated_org_is_review(self) -> None:
        letter = "I worked at Google using Python and AWS."
        grade, flagged = grade_unsupported_claims(TRUE_RESUME_PROSE, letter, prose=True)
        assert grade == FabricationGrade.REVIEW
        assert "Google" in flagged


class TestGradeProseViolation:
    def test_multiple_invented_entities_is_violation(self) -> None:
        letter = "I hold a Stanford PhD with expertise in Kubernetes and TensorFlow."
        grade, flagged = grade_unsupported_claims(TRUE_RESUME_PROSE, letter, prose=True)
        assert grade == FabricationGrade.VIOLATION
        assert len(flagged) >= 2


# ---------------------------------------------------------------------------
# Return structure
# ---------------------------------------------------------------------------


class TestReturnStructure:
    def test_returns_tuple_of_two(self) -> None:
        result = grade_unsupported_claims(TRUE_RESUME, "Python.")
        assert isinstance(result, tuple)
        assert len(result) == 2

    def test_first_element_is_grade(self) -> None:
        grade, _ = grade_unsupported_claims(TRUE_RESUME, "Python.")
        assert isinstance(grade, FabricationGrade)

    def test_second_element_is_list(self) -> None:
        _, flagged = grade_unsupported_claims(TRUE_RESUME, "Python.")
        assert isinstance(flagged, list)

    def test_flagged_list_consistent_with_underlying_checker(self) -> None:
        generated = "Expert in Kubernetes and TensorFlow."
        _, flagged_grade = grade_unsupported_claims(TRUE_RESUME, generated)
        flagged_direct = unsupported_claims(TRUE_RESUME, generated)
        assert flagged_grade == flagged_direct

    def test_flagged_prose_list_consistent_with_underlying_checker(self) -> None:
        generated = "Stanford PhD working with Kubernetes."
        _, flagged_grade = grade_unsupported_claims(TRUE_RESUME_PROSE, generated, prose=True)
        flagged_direct = unsupported_prose_claims(TRUE_RESUME_PROSE, generated)
        assert flagged_grade == flagged_direct


# ---------------------------------------------------------------------------
# Backward compatibility — existing public API unchanged
# ---------------------------------------------------------------------------


class TestBackwardCompat:
    def test_unsupported_claims_still_returns_list(self) -> None:
        result = unsupported_claims(TRUE_RESUME, "Kubernetes")
        assert isinstance(result, list)

    def test_unsupported_prose_claims_still_returns_list(self) -> None:
        result = unsupported_prose_claims(TRUE_RESUME_PROSE, "Stanford PhD.")
        assert isinstance(result, list)

    def test_clean_path_still_empty_list(self) -> None:
        assert unsupported_claims(TRUE_RESUME, "Python SQL.") == []

    def test_violation_path_still_nonempty_list(self) -> None:
        assert unsupported_claims(TRUE_RESUME, "Kubernetes TensorFlow") != []
