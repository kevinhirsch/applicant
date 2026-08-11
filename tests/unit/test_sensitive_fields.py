"""Unit tests for applicant.core.rules.sensitive_fields (FR-ATTR-6, P2-7).

Covers is_sensitive_field, is_work_auth_question, decide_sensitive_fill,
and the SensitiveFillDecision dataclass.
"""

from __future__ import annotations

import pytest

from applicant.core.rules.sensitive_fields import (
    DECLINE_TO_SELF_IDENTIFY,
    SensitiveFillDecision,
    SensitiveFieldViolation,
    decide_sensitive_fill,
    is_sensitive_field,
    is_work_auth_question,
)


@pytest.fixture(autouse=True)
def _no_cache():
    """xdist parallel-safety: no cache to clear for this module."""
    yield


# ============================================================================
# is_sensitive_field
# ============================================================================


@pytest.mark.unit
class TestIsSensitiveField:
    """EEO/demographic field detection (FR-ATTR-6)."""

    # --- true cases: unambiguous substring markers -------------------------

    @pytest.mark.parametrize(
        "label",
        [
            "Gender",
            "Race/Ethnicity",
            "Ethnicity",
            "Disability",
            "Disabilities",
            "Veteran Status",
            "Protected Veteran",
            "Sexual Orientation",
            "LGBTQ+",
            "Pregnancy Status",
            "Religion",
            "National Origin",
            "Marital Status",
            "Date of Birth",
            "Self-Identification",
            "Self Identify",
            "Diversity",
            "Hispanic/Latino",
            "Latino",
            "Military Service",
        ],
    )
    def test_substring_markers_true(self, label: str) -> None:
        assert is_sensitive_field(label) is True

    # --- true cases: word-boundary markers ---------------------------------

    @pytest.mark.parametrize(
        "label",
        [
            "Age",
            "Age range",
            "DOB",
            "EEO Category",
            "Race",
            "Sex",
        ],
    )
    def test_word_markers_true(self, label: str) -> None:
        assert is_sensitive_field(label) is True

    # --- false cases: substring inside a non-EEO word ----------------------

    @pytest.mark.parametrize(
        "label",
        [
            "Manager",  # "age" inside but no word boundary
            "Message",  # "age" inside but no word boundary
            "unisex",  # "sex" inside but no word boundary
            "embrace",  # "race" inside but no word boundary
            "" "",
        ],
    )
    def test_false(self, label: str) -> None:
        assert is_sensitive_field(label) is False

    def test_empty_label(self) -> None:
        assert is_sensitive_field("") is False


# ============================================================================
# is_work_auth_question
# ============================================================================


@pytest.mark.unit
class TestIsWorkAuthQuestion:
    """Work-authorization question detection (P2-7)."""

    # --- true: strong multi-word cues --------------------------------------

    @pytest.mark.parametrize(
        "text",
        [
            "What is your work authorization status?",
            "Do you have authorization to work in the US?",
            "Are you authorized to work in this country?",
            "Are you legally authorized to work in the United States?",
            "Are you eligible to work in the US?",
            "Proof of eligibility to work",
            "Do you have the right to work in the US?",
            "Does this position require sponsorship?",
            "Will you require sponsorship for employment?",
            "Will you need visa sponsorship?",
            "What is your visa status?",
            "Do you have a work visa?",
            "Employment visa type",
            "Do you have a valid work permit?",
            "Immigration status",
            "Citizenship status",
        ],
    )
    def test_strong_cues_true(self, text: str) -> None:
        assert is_work_auth_question(text) is True

    # --- true: weak markers on short text (<=8 words) ----------------------

    @pytest.mark.parametrize(
        "text",
        [
            "Visa",
            "Visa status",
            "Visa type",
            "Do you need visa sponsorship?",
            "Are you a US citizen?",
            "Are you a citizen?",
            "Sponsorship required",
            "Require sponsorship",
        ],
    )
    def test_weak_markers_short_text_true(self, text: str) -> None:
        assert is_work_auth_question(text) is True

    # --- false: weak markers on long text (>8 words) -----------------------

    @pytest.mark.parametrize(
        "text",
        [
            "Please describe your experience with visa processing and immigration law compliance in your previous roles",  # >8 words, "visa" mentioned but long
            "Tell us about a time you helped a colleague who needed a sponsorship letter for a conference",  # >8 words, "sponsorship" mentioned but long
            "As part of this role you will interact with citizens across multiple departments and government agencies",  # >8 words, "citizens" mentioned but long
        ],
    )
    def test_weak_markers_long_text_false(self, text: str) -> None:
        assert is_work_auth_question(text) is False

    # --- false: no match at all --------------------------------------------

    @pytest.mark.parametrize(
        "text",
        [
            "What is your desired salary?",
            "",
            "   ",
            "Years of experience",
            "Preferred start date",
            "How did you hear about this position?",
        ],
    )
    def test_no_match_false(self, text: str) -> None:
        assert is_work_auth_question(text) is False


# ============================================================================
# SensitiveFillDecision dataclass
# ============================================================================


@pytest.mark.unit
class TestSensitiveFillDecision:
    """Frozen dataclass integrity."""

    def test_construction(self) -> None:
        d = SensitiveFillDecision(
            field_label="Gender",
            is_sensitive=True,
            value="Male",
            from_explicit_answer=True,
        )
        assert d.field_label == "Gender"
        assert d.is_sensitive is True
        assert d.value == "Male"
        assert d.from_explicit_answer is True

    def test_frozen(self) -> None:
        d = SensitiveFillDecision(
            field_label="Race",
            is_sensitive=True,
            value="decline to self-identify",
            from_explicit_answer=False,
        )
        with pytest.raises(AttributeError):
            d.value = "Asian"  # type: ignore[misc]


# ============================================================================
# decide_sensitive_fill
# ============================================================================


@pytest.mark.unit
class TestDecideSensitiveFill:
    """Core sensitive-fill decision logic (FR-ATTR-6)."""

    # --- non-sensitive fields pass through --------------------------------

    def test_non_sensitive_without_answer(self) -> None:
        d = decide_sensitive_fill("Manager", explicit_answer=None)
        assert d.is_sensitive is False
        assert d.value == ""
        assert d.from_explicit_answer is False

    def test_non_sensitive_with_explicit_answer(self) -> None:
        d = decide_sensitive_fill("Manager", explicit_answer="John")
        assert d.is_sensitive is False
        assert d.value == "John"
        assert d.from_explicit_answer is True

    def test_non_sensitive_with_ai_suggested(self) -> None:
        d = decide_sensitive_fill("Manager", explicit_answer=None, ai_suggested="Jane")
        assert d.is_sensitive is False
        assert d.value == ""

    # --- sensitive fields: ai_suggested raises error ----------------------

    def test_sensitive_with_ai_suggested_raises(self) -> None:
        with pytest.raises(SensitiveFieldViolation) as exc:
            decide_sensitive_fill("Gender", explicit_answer=None, ai_suggested="Male")
        assert "Gender" in str(exc.value)

    def test_sensitive_with_ai_suggested_and_explicit_raises(self) -> None:
        with pytest.raises(SensitiveFieldViolation):
            decide_sensitive_fill(
                "Race/Ethnicity",
                explicit_answer="Asian",
                ai_suggested="Asian",
            )

    # --- sensitive fields: explicit answer used ---------------------------

    def test_sensitive_with_explicit_answer(self) -> None:
        d = decide_sensitive_fill("Veteran Status", explicit_answer="Not a veteran")
        assert d.is_sensitive is True
        assert d.value == "Not a veteran"
        assert d.from_explicit_answer is True

    # --- sensitive fields: no explicit answer -> decline default -----------

    def test_sensitive_without_answer_default(self) -> None:
        d = decide_sensitive_fill("Disability", explicit_answer=None)
        assert d.is_sensitive is True
        assert d.value == DECLINE_TO_SELF_IDENTIFY
        assert d.from_explicit_answer is False

    def test_sensitive_with_empty_string_answer(self) -> None:
        d = decide_sensitive_fill("Age", explicit_answer="")
        assert d.is_sensitive is True
        assert d.value == DECLINE_TO_SELF_IDENTIFY
        assert d.from_explicit_answer is False

    # --- edge cases -------------------------------------------------------

    def test_word_marker_sensitive_with_default(self) -> None:
        d = decide_sensitive_fill("Eeo", explicit_answer=None)
        assert d.is_sensitive is True
        assert d.value == DECLINE_TO_SELF_IDENTIFY
