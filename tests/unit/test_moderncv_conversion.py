"""Real docx->moderncv conversion tests (FR-RESUME-3/3a).

The conversion is GENUINE, not a passthrough: a parsed résumé is rendered into a
real moderncv ("banking") ``.tex`` source via the vendored Jinja2 template, with the
candidate's real sections/dates/skills, valid moderncv structure, LaTeX special
chars escaped, and em-dashes stripped (FR-RESUME-5). Hermetic: no TeX required.
"""

from __future__ import annotations

import pytest

from applicant.adapters.resume_parser.resume_parser import ResumeParser
from applicant.adapters.resume_tailoring.latex_tailor import LatexTailor
from applicant.adapters.resume_tailoring.moderncv_converter import (
    ModerncvConverter,
    latex_escape,
)
from applicant.adapters.storage.app_config_store import InMemoryAppConfigStore
from applicant.application.services.conversion_service import ConversionService

_RESUME_TEXT = """Jane Q. Smith
jane@example.com
+1 555 123 4567

Experience
Senior Engineer, Acme & Sons    Jan 2020 - Present
Junior Dev at Foo Inc    2017 - 2019

Education
B.S. Computer Science, State University    2013 - 2017

Skills
Python, SQL, 100% coverage, R&D
"""


@pytest.fixture
def converter() -> ModerncvConverter:
    return ModerncvConverter(resume_parser=ResumeParser())


def test_conversion_is_valid_moderncv_structure(converter):
    tex = converter.convert_text(_RESUME_TEXT).tex_source
    # The conversion produces a REAL moderncv document, not the raw résumé text.
    assert "\\documentclass[11pt,a4paper,sans]{moderncv}" in tex
    assert "\\moderncvstyle{banking}" in tex
    assert "\\begin{document}" in tex and "\\end{document}" in tex
    assert "\\makecvtitle" in tex


def test_conversion_carries_real_sections_dates_skills(converter):
    tex = converter.convert_text(_RESUME_TEXT).tex_source
    # Identity.
    assert "\\name{Jane}{Q. Smith}" in tex
    assert "jane@example.com" in tex
    # Work history with dates rendered as a moderncv \cventry.
    assert "Senior Engineer" in tex
    assert "Jan 2020 - Present" in tex
    assert "2017 - 2019" in tex
    assert "\\cventry{" in tex
    # Education + skills sections.
    assert "\\section{Education}" in tex
    assert "B.S. Computer Science" in tex
    assert "\\section{Skills}" in tex
    assert "Python" in tex and "SQL" in tex


def test_latex_special_chars_are_escaped(converter):
    tex = converter.convert_text(_RESUME_TEXT).tex_source
    # "Acme & Sons", "100% coverage", "R&D" must be escaped, never raw.
    assert "\\&" in tex
    assert "\\%" in tex
    assert "Acme & Sons" not in tex  # the unescaped ampersand must not survive
    assert "100% coverage" not in tex


def test_latex_escape_helper_strips_emdash_and_escapes():
    out = latex_escape("Led R&D — 50% growth")
    assert "—" not in out  # em-dash stripped (FR-RESUME-5)
    assert "\\&" in out and "\\%" in out


def test_latex_escape_backslash_is_single_pass_not_recursive():
    """FR-RESUME-3: a literal backslash escapes to \\textbackslash{} WITHOUT the
    introduced braces being re-escaped (single non-recursive pass)."""
    # Before the fix this produced an invalid, double-escaped string
    # (e.g. "a\\textbackslash\\{\\}b").
    assert latex_escape("a\\b") == "a\\textbackslash{}b"
    # Braces present in the SOURCE text are still escaped normally.
    assert latex_escape("100% {x}") == "100\\% \\{x\\}"
    # Backslash + braces together stay correct (no re-escaping cascade).
    assert latex_escape("\\{") == "\\textbackslash{}\\{"
    # Em-dash handling is unaffected (FR-RESUME-5).
    assert "—" not in latex_escape("a — b")


def test_conversion_is_emdash_free(converter):
    text = _RESUME_TEXT + "\nProfile: builder — shipper — closer\n"
    tex = converter.convert_text(text).tex_source
    assert "—" not in tex
    assert "–" not in tex


def test_conversion_does_not_fabricate_missing_sections(converter):
    # A minimal résumé with no education yields no Education section (truthful).
    tex = converter.convert_text("John Doe\njohn@x.com\n").tex_source
    assert "\\section{Education}" not in tex
    assert "\\section{Professional Experience}" not in tex
    assert "\\name{John}{Doe}" in tex


def test_service_preview_uses_real_conversion():
    svc = ConversionService(
        latex_tailor=LatexTailor(), config_store=InMemoryAppConfigStore()
    )
    preview = svc.build_preview("camp-1", _RESUME_TEXT)
    # The preview now exposes the genuinely converted .tex source (not passthrough).
    assert "\\documentclass[11pt,a4paper,sans]{moderncv}" in preview.tex_source
    assert "Senior Engineer" in preview.tex_source
    assert preview.page_count >= 1
