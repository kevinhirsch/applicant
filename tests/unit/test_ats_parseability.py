"""Unit tests for ATS parseability rules (AZ0-81)."""

from __future__ import annotations

import pytest

from applicant.core.rules.ats_parseability import (
    ParseabilityReport,
    UploadHealthReport,
    UPLOAD_HEALTH_GOOD,
    UPLOAD_HEALTH_ISSUES,
    UPLOAD_HEALTH_UNREADABLE,
    check_upload_health,
    check_render_parseability,
)


# ---------------------------------------------------------------------------
# Parallel-safety: autouse fixture for xdist (no LRU cache in this module,
# but all modules in the suite get an autouse fixture per convention).
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clean_state() -> None:
    pass


# ===================================================================
# ParseabilityReport
# ===================================================================


class TestParseabilityReportConstruction:
    """Frozen dataclass construction and defaults."""

    def test_minimal_construction(self) -> None:
        report = ParseabilityReport(parseable=True)
        assert report.parseable is True
        assert report.issues == ()

    def test_construction_with_issues(self) -> None:
        report = ParseabilityReport(
            parseable=False,
            issues=("contact email is not recoverable", "no recognizable section headers"),
        )
        assert report.parseable is False
        assert report.issues == ("contact email is not recoverable", "no recognizable section headers")

    def test_empty_issues_via_field(self) -> None:
        report = ParseabilityReport(parseable=True, issues=())
        assert report.issues == ()


class TestParseabilityReportFrozen:
    """Dataclass immutability."""

    def test_cannot_set_parseable(self) -> None:
        report = ParseabilityReport(parseable=True)
        with pytest.raises(AttributeError):
            report.parseable = False  # type: ignore[misc]

    def test_cannot_set_issues(self) -> None:
        report = ParseabilityReport(parseable=True)
        with pytest.raises(AttributeError):
            report.issues = ("x",)  # type: ignore[misc]


class TestParseabilityReportRequiresReview:
    """requires_review property mirrors parseable."""

    def test_parseable_does_not_require_review(self) -> None:
        report = ParseabilityReport(parseable=True)
        assert report.requires_review is False

    def test_not_parseable_requires_review(self) -> None:
        report = ParseabilityReport(parseable=False)
        assert report.requires_review is True

    def test_not_parseable_with_issues_requires_review(self) -> None:
        report = ParseabilityReport(
            parseable=False,
            issues=("contact email is not recoverable",),
        )
        assert report.requires_review is True


class TestParseabilityReportReason:
    """reason property returns appropriate message."""

    def test_parseable_reason(self) -> None:
        report = ParseabilityReport(parseable=True)
        assert report.reason == "Render is machine-readable."

    def test_not_parseable_default_reason(self) -> None:
        report = ParseabilityReport(parseable=False)
        assert report.reason == "Render text could not be recovered."

    def test_not_parseable_with_issues(self) -> None:
        report = ParseabilityReport(
            parseable=False,
            issues=("contact email is not recoverable", "no recognizable section headers"),
        )
        assert report.reason == "contact email is not recoverable; no recognizable section headers"

    def test_not_parseable_with_single_issue(self) -> None:
        report = ParseabilityReport(
            parseable=False,
            issues=("no recognizable section headers",),
        )
        assert report.reason == "no recognizable section headers"


class TestParseabilityReportEquality:
    """Equality and hashability of frozen dataclass."""

    def test_equal_reports(self) -> None:
        a = ParseabilityReport(parseable=True, issues=())
        b = ParseabilityReport(parseable=True, issues=())
        assert a == b

    def test_different_parseable(self) -> None:
        a = ParseabilityReport(parseable=True)
        b = ParseabilityReport(parseable=False)
        assert a != b

    def test_different_issues(self) -> None:
        a = ParseabilityReport(parseable=False, issues=("a",))
        b = ParseabilityReport(parseable=False, issues=("b",))
        assert a != b

    def test_hashable(self) -> None:
        a = ParseabilityReport(parseable=True)
        b = ParseabilityReport(parseable=True)
        assert hash(a) == hash(b)
        s = {a, b}
        assert len(s) == 1


# ===================================================================
# UploadHealthReport
# ===================================================================


class TestUploadHealthReportConstruction:
    """Frozen dataclass construction and defaults."""

    def test_minimal_construction(self) -> None:
        report = UploadHealthReport(verdict=UPLOAD_HEALTH_GOOD)
        assert report.verdict == UPLOAD_HEALTH_GOOD
        assert report.issues == ()

    def test_construction_with_issues(self) -> None:
        report = UploadHealthReport(
            verdict=UPLOAD_HEALTH_ISSUES,
            issues=("your name is not detectable in the text",),
        )
        assert report.verdict == UPLOAD_HEALTH_ISSUES
        assert report.issues == ("your name is not detectable in the text",)

    def test_unreadable_verdict(self) -> None:
        report = UploadHealthReport(
            verdict=UPLOAD_HEALTH_UNREADABLE,
            issues=("no recoverable text layer (the résumé may be rendered as an image)",),
        )
        assert report.verdict == UPLOAD_HEALTH_UNREADABLE


class TestUploadHealthReportParseable:
    """parseable property: only GOOD verdict counts as parseable."""

    def test_good_is_parseable(self) -> None:
        report = UploadHealthReport(verdict=UPLOAD_HEALTH_GOOD)
        assert report.parseable is True

    def test_issues_is_not_parseable(self) -> None:
        report = UploadHealthReport(verdict=UPLOAD_HEALTH_ISSUES)
        assert report.parseable is False

    def test_unreadable_is_not_parseable(self) -> None:
        report = UploadHealthReport(verdict=UPLOAD_HEALTH_UNREADABLE)
        assert report.parseable is False


class TestUploadHealthReportFrozen:
    """Dataclass immutability."""

    def test_cannot_set_verdict(self) -> None:
        report = UploadHealthReport(verdict=UPLOAD_HEALTH_GOOD)
        with pytest.raises(AttributeError):
            report.verdict = UPLOAD_HEALTH_ISSUES  # type: ignore[misc]

    def test_cannot_set_issues(self) -> None:
        report = UploadHealthReport(verdict=UPLOAD_HEALTH_GOOD)
        with pytest.raises(AttributeError):
            report.issues = ("x",)  # type: ignore[misc]


class TestUploadHealthReportEquality:
    """Equality and hashability of frozen dataclass."""

    def test_equal_reports(self) -> None:
        a = UploadHealthReport(verdict=UPLOAD_HEALTH_GOOD, issues=())
        b = UploadHealthReport(verdict=UPLOAD_HEALTH_GOOD, issues=())
        assert a == b

    def test_different_verdicts(self) -> None:
        a = UploadHealthReport(verdict=UPLOAD_HEALTH_GOOD)
        b = UploadHealthReport(verdict=UPLOAD_HEALTH_ISSUES)
        assert a != b

    def test_different_issues(self) -> None:
        a = UploadHealthReport(verdict=UPLOAD_HEALTH_ISSUES, issues=("a",))
        b = UploadHealthReport(verdict=UPLOAD_HEALTH_ISSUES, issues=("b",))
        assert a != b

    def test_hashable(self) -> None:
        a = UploadHealthReport(verdict=UPLOAD_HEALTH_GOOD)
        b = UploadHealthReport(verdict=UPLOAD_HEALTH_GOOD)
        assert hash(a) == hash(b)
        s = {a, b}
        assert len(s) == 1


# ===================================================================
# check_upload_health
# ===================================================================


class TestCheckUploadHealthEmptyText:
    """Empty or whitespace-only text → UNREADABLE."""

    def test_empty_string(self) -> None:
        result = check_upload_health(raw_text="")
        assert result.verdict == UPLOAD_HEALTH_UNREADABLE
        assert "recoverable text layer" in result.issues[0]
        assert not result.parseable

    def test_whitespace_only(self) -> None:
        result = check_upload_health(raw_text="   \n\t  ")
        assert result.verdict == UPLOAD_HEALTH_UNREADABLE

    def test_very_short_text(self) -> None:
        result = check_upload_health(raw_text="a" * 39)
        assert result.verdict == UPLOAD_HEALTH_UNREADABLE
        assert len(result.issues) == 1


class TestCheckUploadHealthGood:
    """Text with all required fields passes."""

    def test_full_name_email_phone_no_issues(self) -> None:
        text = "John Doe\n" + "word " * 50 + "\nsummary experience education"
        result = check_upload_health(
            raw_text=text,
            full_name="John Doe",
            email="john@example.com",
            phone="+1-555-0001",
        )
        assert result.verdict == UPLOAD_HEALTH_GOOD
        assert result.issues == ()
        assert result.parseable

    def test_email_in_text_only(self) -> None:
        text = "Jane Smith\nmy email: jane@work.com\n" + "word " * 50 + "\nskills experience"
        result = check_upload_health(
            raw_text=text,
            full_name="Jane Smith",
            phone="555-0100",
        )
        assert result.verdict == UPLOAD_HEALTH_GOOD
        assert result.issues == ()


class TestCheckUploadHealthMissingFields:
    """Missing name, email, or phone generates specific issues."""

    def test_missing_full_name(self) -> None:
        text = "word " * 50 + "\nsummary education skills"
        result = check_upload_health(
            raw_text=text,
            email="a@b.com",
            phone="555",
        )
        assert result.verdict == UPLOAD_HEALTH_ISSUES
        assert any("name" in i for i in result.issues)

    def test_missing_email_no_email_in_text(self) -> None:
        text = "John\n" + "word " * 50 + "\nsummary education"
        result = check_upload_health(
            raw_text=text,
            full_name="John",
            phone="555",
        )
        assert result.verdict == UPLOAD_HEALTH_ISSUES
        assert any("email" in i for i in result.issues)

    def test_missing_all_fields(self) -> None:
        text = "word " * 50 + "\nexperience education skills"
        result = check_upload_health(raw_text=text)
        assert result.verdict == UPLOAD_HEALTH_ISSUES
        issue_text = "; ".join(result.issues)
        assert "name" in issue_text
        assert "email" in issue_text
        assert "phone" in issue_text
        assert len(result.issues) >= 3

    def test_blank_full_name_whitespace_only(self) -> None:
        text = "word " * 50 + "\nskills experience\nanother@site.com"
        result = check_upload_health(raw_text=text, full_name="  ", email="test@x.com", phone="555")
        assert result.verdict == UPLOAD_HEALTH_ISSUES
        assert any("name" in i for i in result.issues)


class TestCheckUploadHealthLowTextLength:
    """Text between 40 and 149 chars triggers 'very little text' issue."""

    def test_text_below_150_no_other_issues(self) -> None:
        text = "a" * 100
        result = check_upload_health(
            raw_text=text,
            full_name="John",
            email="a@b.com",
            phone="555",
        )
        assert result.verdict == UPLOAD_HEALTH_ISSUES
        assert "very little text" in str(result.issues)

    def test_text_below_150_with_other_issues(self) -> None:
        text = "a" * 120
        result = check_upload_health(raw_text=text)
        assert result.verdict == UPLOAD_HEALTH_ISSUES
        assert "very little text" in str(result.issues)

    def test_text_just_above_150_no_length_issue(self) -> None:
        text = "John\n" + "x" * 160 + "\nskills education summary"
        result = check_upload_health(
            raw_text=text,
            full_name="John",
            email="a@b.com",
            phone="555",
        )
        issues_str = "; ".join(result.issues)
        assert "very little text" not in issues_str


class TestCheckUploadHealthSectionCues:
    """Missing section headers triggers an issue."""

    def test_no_section_cues(self) -> None:
        text = "John Doe\n" + "word " * 50
        result = check_upload_health(
            raw_text=text,
            full_name="John Doe",
            email="a@b.com",
            phone="555",
        )
        # 'word' does not match any SECTION_CUE
        assert result.verdict == UPLOAD_HEALTH_ISSUES
        assert any("section headers" in i for i in result.issues)

    def test_section_cue_present(self) -> None:
        text = "Jane\n" + "word " * 50 + "\nEDUCATION"
        result = check_upload_health(
            raw_text=text,
            full_name="Jane",
            email="a@b.com",
            phone="555",
        )
        # 'education' matches one of the cues (case-insensitive)
        assert not any("section headers" in i for i in result.issues)


class TestCheckUploadHealthPhoneNotInText:
    """Phone is only checked via the provided parameter, not text search."""

    def test_phone_in_text_but_not_provided_is_still_issue(self) -> None:
        text = "Call me at 555-1234\n" + "word " * 50 + "\nsummary experience"
        result = check_upload_health(
            raw_text=text,
            full_name="John",
            email="a@b.com",
        )
        # phone='' is default, and the check only looks at the phone parameter
        assert any("phone" in i for i in result.issues)


# ===================================================================
# check_render_parseability
# ===================================================================


class TestCheckRenderParseabilityEmptyText:
    """Empty, whitespace, or very short text → not parseable."""

    def test_empty_string(self) -> None:
        result = check_render_parseability("")
        assert result.parseable is False
        assert "recoverable text layer" in result.reason

    def test_whitespace_only(self) -> None:
        result = check_render_parseability("   \n  \t")
        assert result.parseable is False

    def test_short_text(self) -> None:
        result = check_render_parseability("a" * 39)
        assert result.parseable is False
        assert len(result.issues) == 1


class TestCheckRenderParseabilityGood:
    """Text with email and section cues passes."""

    def test_email_and_section_cues(self) -> None:
        text = "john@example.com\nExperience section with details\nEducation\nSkills"
        result = check_render_parseability(text)
        assert result.parseable is True
        assert result.issues == ()

    def test_email_and_single_cue(self) -> None:
        text = "contact@work.com\nWork History: software engineer"
        result = check_render_parseability(text)
        # 'work history' matches one of the SECTION_CUES
        assert result.parseable is True


class TestCheckRenderParseabilityNoEmail:
    """No email in text → issue."""

    def test_no_email_address(self) -> None:
        text = "John Doe\nExperience\nEducation\nSkills\n" + "word " * 20
        result = check_render_parseability(text)
        assert result.parseable is False
        assert any("email" in i for i in result.issues)

    def test_invalid_email_pattern(self) -> None:
        # The regex is [A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}
        text = "John Doe\nuser at example dot com\nExperience\n" + "word " * 20
        result = check_render_parseability(text)
        assert result.parseable is False
        assert any("email" in i for i in result.issues)


class TestCheckRenderParseabilityNoSections:
    """No section cues → issue."""

    def test_no_section_headers(self) -> None:
        text = "john@example.com\nThis is a short note without any experience, education, or skills sections."
        result = check_render_parseability(text)
        # The text contains the words 'experience', 'education', 'skills' inside a sentence
        # so they DO match the cues (case-insensitive). Let me use text without those words.
        assert result.parseable is True  # section cues found

    def test_truly_no_section_cues(self) -> None:
        # Use a text with email but no section-cue words
        text = "john@example.com\n" + "random word " * 20
        result = check_render_parseability(text)
        assert result.parseable is False
        assert any("section headers" in i for i in result.issues)


class TestCheckRenderParseabilityMultipleIssues:
    """Both missing email and missing sections produce combined issues."""

    def test_no_email_no_sections(self) -> None:
        text = "a" * 50
        result = check_render_parseability(text)
        assert result.parseable is False
        assert len(result.issues) >= 2
        assert any("email" in i for i in result.issues)
        assert any("section headers" in i for i in result.issues)

    def test_empty_and_short(self) -> None:
        # Already handled by early return, but sanity check
        for val in ("", "   ", "a" * 10, "a" * 39):
            result = check_render_parseability(val)
            assert result.parseable is False
            assert len(result.issues) == 1
            assert "recoverable text layer" in result.issues[0]

