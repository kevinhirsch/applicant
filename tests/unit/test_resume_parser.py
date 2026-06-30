"""ResumeParser extraction tests (FR-ONBOARD-3, FR-ATTR-1).

Hermetic: builds a tiny .docx in-test with python-docx and a .txt resume, then
asserts identity / work-history / education / skills extraction and font detection.
No external files or services required.
"""

from __future__ import annotations

import pytest

from applicant.adapters.resume_parser.resume_parser import ResumeParser

_TXT_RESUME = """\
Jane Q Candidate
jane@example.com | +1 (415) 555-0199

Experience:
Senior Engineer at Acme Corp    Jan 2020 - Present
Software Engineer at Globex     Jun 2017 - Dec 2019

Education:
B.S. Computer Science, State University    2013 - 2017

Skills:
Python, SQL, FastAPI, Docker
"""


@pytest.fixture
def parser() -> ResumeParser:
    return ResumeParser()


def test_skills_split_on_middledot_and_keep_parenthetical_groups(parser, tmp_path):
    """Regression: a '·'-delimited skills line with a parenthetical sub-list and a
    following Certifications heading must NOT produce junk skills like 'SQL · Postgres',
    'AWS (EKS', 'Lambda)' or capture the 'Certifications' heading as a skill."""
    resume = (
        "Jane Q Candidate\n"
        "jane@example.com\n\n"
        "Skills:\n"
        "Python, Go, SQL · Postgres, Redis · Kubernetes, Docker, AWS (EKS, RDS, Lambda)\n\n"
        "Certifications:\n"
        "AWS Certified Solutions Architect\n"
    )
    p = tmp_path / "resume.txt"
    p.write_text(resume, encoding="utf-8")
    skills = parser.parse(str(p)).skills

    # Clean atomic skills are recovered across both comma and middle-dot separators.
    for want in ("Python", "Go", "SQL", "Postgres", "Redis", "Kubernetes", "Docker"):
        assert want in skills, f"{want!r} missing from {skills}"
    # The parenthetical sub-list stays one token, not shredded.
    assert "AWS (EKS, RDS, Lambda)" in skills
    # No junk from the old comma/middle-dot shredding.
    for junk in ("SQL · Postgres", "AWS (EKS", "Lambda)", "RDS"):
        assert junk not in skills, f"junk {junk!r} leaked into {skills}"
    # The Certifications heading is a section boundary, not a skill.
    assert "Certifications" not in skills
    assert not any("Certified Solutions Architect" in s for s in skills)


def test_parse_txt_extracts_identity(parser, tmp_path):
    p = tmp_path / "resume.txt"
    p.write_text(_TXT_RESUME, encoding="utf-8")
    parsed = parser.parse(str(p))
    assert parsed.full_name == "Jane Q Candidate"
    assert parsed.email == "jane@example.com"
    assert "555" in parsed.phone


def test_parse_txt_extracts_work_history_with_dates(parser, tmp_path):
    p = tmp_path / "resume.txt"
    p.write_text(_TXT_RESUME, encoding="utf-8")
    parsed = parser.parse(str(p))
    titles = {w.title for w in parsed.work_history}
    assert "Senior Engineer" in titles
    companies = {w.company for w in parsed.work_history}
    assert "Acme Corp" in companies
    # Dates preserved (Workday-critical).
    first = next(w for w in parsed.work_history if w.title == "Senior Engineer")
    assert "2020" in first.start_date
    assert "Present" in first.end_date


def test_parse_txt_parenthesized_dates_no_dangling_bracket(parser, tmp_path):
    """A 'Title - Company (2020-Present)' line must not leak the '(' into the
    company. Regression: the date regex matched inside the parens, leaving the
    opening bracket dangling so the company rendered as 'Acme Corp (' in the
    compiled moderncv résumé (FR-RESUME-3)."""
    resume = (
        "Experience:\n"
        "Staff Software Engineer - Acme Corp (2020-Present)\n"
        "Senior Software Engineer - Globex (2016-2020)\n"
    )
    p = tmp_path / "resume.txt"
    p.write_text(resume, encoding="utf-8")
    parsed = parser.parse(str(p))
    companies = {w.company for w in parsed.work_history}
    assert "Acme Corp" in companies
    assert "Globex" in companies
    # No company carries a stray bracket or separator.
    for w in parsed.work_history:
        assert not w.company.endswith(("(", "[", "{", "-"))
        assert "(" not in w.company
        assert w.title == w.title.strip()


def test_parse_txt_extracts_education_and_skills(parser, tmp_path):
    p = tmp_path / "resume.txt"
    p.write_text(_TXT_RESUME, encoding="utf-8")
    parsed = parser.parse(str(p))
    assert any("B.S" in e.degree for e in parsed.education)
    assert "Python" in parsed.skills
    assert "FastAPI" in parsed.skills


def test_parse_docx_built_in_test(parser, tmp_path):
    docx = pytest.importorskip("docx")
    doc = docx.Document()
    doc.add_paragraph("John Doe")
    doc.add_paragraph("john@doe.dev")
    doc.add_paragraph("Experience:")
    doc.add_paragraph("Lead Developer at Initech    Mar 2018 - Present")
    doc.add_paragraph("Education:")
    doc.add_paragraph("M.S. Data Science, MIT    2015 - 2017")
    doc.add_paragraph("Skills:")
    doc.add_paragraph("Go, Rust, Kubernetes")
    path = tmp_path / "resume.docx"
    doc.save(str(path))

    parsed = parser.parse(str(path))
    assert parsed.full_name == "John Doe"
    assert parsed.email == "john@doe.dev"
    assert any(w.company == "Initech" for w in parsed.work_history)
    assert any("M.S" in e.degree for e in parsed.education)
    assert "Go" in parsed.skills


def test_parse_docx_detects_declared_fonts(parser, tmp_path):
    docx = pytest.importorskip("docx")
    doc = docx.Document()
    style = doc.styles["Normal"]
    style.font.name = "Inconsolata"
    doc.add_paragraph("Some body text")
    path = tmp_path / "fonted.docx"
    doc.save(str(path))
    parsed = parser.parse(str(path))
    assert "Inconsolata" in parsed.detected_fonts


def test_parse_missing_file_is_safe(parser):
    parsed = parser.parse("/no/such/file.txt")
    assert parsed.full_name == ""
    assert parsed.work_history == ()


_DATE_ON_NEXT_LINE_RESUME = """\
Jane Q Candidate
jane@example.com

Experience:
Senior Engineer, Acme Corp
2021 - Present
Led the platform team and shipped the billing rewrite.

Software Engineer, Globex
2017 - 2019
Built internal tooling.

Education:
M.S. Computer Science
2015 - 2017
State University
"""


def test_work_entry_title_company_survive_date_on_next_line(parser, tmp_path):
    """Regression: 'Title, Company' on one line with the date range on the NEXT line
    must NOT drop the title/company (would render '\\cventry{2021 - Present}{}{}...')."""
    p = tmp_path / "r.txt"
    p.write_text(_DATE_ON_NEXT_LINE_RESUME)
    parsed = parser.parse(str(p))
    titles = {w.title for w in parsed.work_history}
    companies = {w.company for w in parsed.work_history}
    assert "Senior Engineer" in titles
    assert "Acme Corp" in companies
    assert "Software Engineer" in titles
    assert "Globex" in companies
    senior = next(w for w in parsed.work_history if w.title == "Senior Engineer")
    assert senior.start_date == "2021"
    assert senior.end_date.lower() == "present"
    # No entry may have an empty title (the date-only line attributed to a real entry).
    assert all(w.title for w in parsed.work_history)


def test_education_year_range_on_next_line_is_not_dropped(parser, tmp_path):
    """Regression: a degree with its year range on the FOLLOWING line keeps the dates."""
    p = tmp_path / "r.txt"
    p.write_text(_DATE_ON_NEXT_LINE_RESUME)
    parsed = parser.parse(str(p))
    assert any("M.S" in e.degree for e in parsed.education)
    edu = next(e for e in parsed.education if "M.S" in e.degree)
    assert edu.start_year == "2015"
    assert edu.end_year == "2017"
