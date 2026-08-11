"""MAT-2 (#44): a bare résumé section header must never be picked as a factual
screening answer (observed live: a CVS application's screening answer was just
"PROFESSIONAL EXPERIENCE")."""

import pytest

from applicant.application.services.material_service import _is_resume_section_header


@pytest.mark.unit
class TestResumeSectionHeaderGuard:
    def test_bare_section_headers_are_flagged(self):
        for h in (
            "PROFESSIONAL EXPERIENCE",
            "professional experience",
            "  CERTIFICATIONS  ",
            "Education",
            "Skills:",
            "Work History",
            "SUMMARY",
        ):
            assert _is_resume_section_header(h), h

    def test_real_answer_lines_are_not_flagged(self):
        for a in (
            "I led three US-based Scrum teams at Wells Fargo",
            "10 years in regulated finance and insurance",
            "Scrum Master",  # a role/title, not a section header
            "CSP-SM, A-CSM, SAFe 6 SSM, KMP",
            "Yes, I am authorized to work in the United States",
            "",
        ):
            assert not _is_resume_section_header(a), a
