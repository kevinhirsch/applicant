"""ATS-parseability proof (wtpar #681).

Hermetic tests proving the engine can produce ATS-parseable résumé output by
exercising the pure core rule ``check_render_parseability`` against realistic
rendered résumé text that exposes the key fields an ATS extracts: name, contact
(phone/email), experience, and education.
"""

from __future__ import annotations

import pytest

from applicant.core.rules.ats_parseability import (
    UPLOAD_HEALTH_GOOD,
    UPLOAD_HEALTH_ISSUES,
    UPLOAD_HEALTH_UNREADABLE,
    ParseabilityReport,
    UploadHealthReport,
    check_render_parseability,
    check_upload_health,
)


# ---------------------------------------------------------------------------
# Parallel-safety autouse fixture (existing project convention).
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clean_state() -> None:
    pass


# ===================================================================
# Realistic rendered-résumé fixtures (the output the engine produces)
# ===================================================================

#: A realistic rendered résumé text that any ATS should parse.
_REALISTIC_RESUME = """\
Jane Q Candidate
jane.candidate@example.com  |  +1 (415) 555-0199

Professional Summary

Experienced software engineer with 8+ years building scalable backend services
and data pipelines. Passionate about clean architecture and developer tooling.

Experience

Senior Software Engineer  |  Acme Corp, San Francisco, CA
Jan 2020 - Present
- Led the redesign of the core billing platform, reducing payment failures by 34%
- Architected a real-time event ingestion pipeline handling 50K events/second
- Mentored 4 junior engineers through structured onboarding and code reviews

Software Engineer  |  Beta Inc, Oakland, CA
Jun 2016 - Dec 2019
- Built RESTful microservices powering the customer-facing dashboard
- Migrated legacy monolith to a service-oriented architecture (SOA)
- Reduced CI pipeline runtime by 40% via parallel test execution

Education

B.S. Computer Science
State University, 2013 - 2017
GPA: 3.8 | Dean's List

Skills

Python, Go, FastAPI, PostgreSQL, Redis, Kubernetes, Docker, AWS
"""

#: A résumé text with NO email address and NO section-header cues — deliberately
#: avoids any word from ``_SECTION_CUES`` (experience, education, skills, summary,
#: projects, work history, employment) as a substring, but has >40 chars.
_RESUME_NO_ATS_FIELDS = (
    "Jordan Smith\n\n"
    "Worked on many different things across several different teams and roles "
    "over the years, building lots of software for clients using many tools and "
    "platforms consistently well every day for a long time."
)

#: Minimal text just below the ``_MIN_TEXT_CHARS`` floor (40 chars).
_RESUME_BELOW_FLOOR = "a" * 39


# ===================================================================
# check_render_parseability — the render-side self-check (engine output)
# ===================================================================


class TestWtparRenderParseabilityRealisticResume:
    """The engine MUST produce a résumé render whose text layer passes the ATS
    parseability self-check when it includes the key fields (name, contact,
    experience, education)."""

    def test_realistic_resume_with_all_fields_is_parseable(self) -> None:
        """A full realistic résumé with name, email, experience, and education
        MUST be flagged as parseable — proving the engine CAN produce output an
        ATS can extract."""
        result = check_render_parseability(_REALISTIC_RESUME)
        assert result.parseable is True, (
            f"Realistic resume should be ATS-parseable but got: {result.issues}"
        )
        assert result.issues == ()
        assert result.requires_review is False

    def test_realistic_resume_has_email_address(self) -> None:
        """The realistic fixture contains the email required for parsability."""
        assert "jane.candidate@example.com" in _REALISTIC_RESUME
        result = check_render_parseability(_REALISTIC_RESUME)
        assert result.parseable is True

    def test_realistic_resume_has_section_cues(self) -> None:
        """The realistic fixture contains 'experience' and 'education' section
        headers required for parsability."""
        lower = _REALISTIC_RESUME.lower()
        assert "experience" in lower
        assert "education" in lower
        result = check_render_parseability(_REALISTIC_RESUME)
        assert result.parseable is True


class TestWtparRenderParseabilityMissingFields:
    """A résumé render missing key ATS fields MUST be flagged as unparseable."""

    def test_no_email_no_section_headers_fails(self) -> None:
        """A render with recoverable text but no email address and no
        section-header cues must be flagged as unparseable."""
        result = check_render_parseability(_RESUME_NO_ATS_FIELDS)
        assert result.parseable is False
        assert len(result.issues) >= 2
        assert any("email" in i for i in result.issues)
        assert any("section headers" in i for i in result.issues)
        assert result.requires_review is True

    def test_empty_text_returns_false(self) -> None:
        """An empty render returns unparseable with text-layer issue."""
        result = check_render_parseability("")
        assert result.parseable is False
        assert any("recoverable text layer" in i for i in result.issues)

    def test_below_minimum_char_count_fails(self) -> None:
        """A render below MIN_TEXT_CHARS (40) returns unparseable."""
        result = check_render_parseability(_RESUME_BELOW_FLOOR)
        assert result.parseable is False
        assert len(result.issues) == 1


class TestWtparRenderParseabilityEdgeCases:
    """Edge cases for the render parseability check."""

    def test_whitespace_only_fails(self) -> None:
        result = check_render_parseability("   \n  \t  ")
        assert result.parseable is False

    def test_email_but_no_section_cues_fails(self) -> None:
        text = "user@example.com\n" + "random word " * 20
        result = check_render_parseability(text)
        assert result.parseable is False
        assert any("section headers" in i for i in result.issues)

    def test_email_with_single_section_cue_passes(self) -> None:
        text = "contact@work.com\nWork History: senior engineer at big corp\n"
        result = check_render_parseability(text)
        assert result.parseable is True

class TestWtparParseabilityReport:
    """ParseabilityReport dataclass construction and properties."""

    def test_frozen_cannot_modify(self) -> None:
        r = ParseabilityReport(parseable=True)
        with pytest.raises(AttributeError):
            r.parseable = False  # type: ignore[misc]

    def test_requires_review_mirrors_not_parseable(self) -> None:
        assert ParseabilityReport(parseable=False).requires_review is True
        assert ParseabilityReport(parseable=True).requires_review is False

    def test_reason_default(self) -> None:
        assert ParseabilityReport(parseable=True).reason == "Render is machine-readable."
        assert ParseabilityReport(parseable=False).reason == "Render text could not be recovered."


# ===================================================================
# check_upload_health — upload-time health assessment (name/email/phone)
# ===================================================================


class TestWtparUploadHealthRealisticResume:
    """The upload-time health check also validates realistic ATS-extractable
    résumés at the onboarding gate (before any application runs)."""

    def test_realistic_resume_passes_upload_health(self) -> None:
        """A realistic résumé with name, email, phone, and section headers
        passes the upload health check (GOOD)."""
        result = check_upload_health(
            raw_text=_REALISTIC_RESUME,
            full_name="Jane Q Candidate",
            email="jane.candidate@example.com",
            phone="+1 (415) 555-0199",
        )
        assert result.verdict == UPLOAD_HEALTH_GOOD
        assert result.parseable is True
        assert result.issues == ()

    def test_realistic_resume_no_contact_fields_yields_issues(self) -> None:
        """Without providing contact parameters the realistic text still
        contains an email address (found via regex), so only name and phone
        issues appear."""
        result = check_upload_health(
            raw_text=_REALISTIC_RESUME,
        )
        assert result.verdict == UPLOAD_HEALTH_ISSUES
        issue_text = "; ".join(result.issues)
        assert "name" in issue_text
        assert "phone" in issue_text

    def test_resume_no_ats_fields_fails_upload_health(self) -> None:
        """A résumé without recoverable email, phone, or section headers
        but >40 chars gets issues flags."""
        result = check_upload_health(raw_text=_RESUME_NO_ATS_FIELDS)
        # The text has >39 chars but no email/phone/section cues
        assert result.verdict == UPLOAD_HEALTH_ISSUES
        assert len(result.issues) >= 1

    def test_empty_text_unreadable(self) -> None:
        result = check_upload_health(raw_text="")
        assert result.verdict == UPLOAD_HEALTH_UNREADABLE

    def test_very_short_text_unreadable(self) -> None:
        result = check_upload_health(raw_text="a" * 10)
        assert result.verdict == UPLOAD_HEALTH_UNREADABLE
