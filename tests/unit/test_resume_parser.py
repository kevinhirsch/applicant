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


# --- data-corruption regressions: wrong-offset degree split + work-history ---
# --- jamming/dropping (product-gaps: onboarding "Your profile" review) -------

#: A realistic 2-job resume with achievement bullets under each role and an
#: Associate degree whose field of study previously triggered a wrong-offset
#: split: "A.A. Computer Infor" / "mation Systems" (concatenating the two
#: reconstructs "A.A. Computer Information Systems" exactly), because the old
#: degree regex had no word boundaries and matched the "ma" bigram inside
#: "Infor-ma-tion" as a false M.A. hit.
_TWO_JOB_RESUME_WITH_BULLETS = """\
Jordan A. Sample
jordan.sample@example.com | (312) 555-0142

Experience:
Senior Support Engineer, Acme Corp    Jan 2021 - Present
Resolved over 200 customer escalations per quarter across enterprise accounts.
Automated the ticket-triage pipeline, cutting median response time by 40%.

IT Support Specialist, Globex Industries    Jun 2018 - Dec 2020
Maintained a 500-endpoint Windows/macOS fleet with 99.5% uptime.
Built a self-service password-reset tool adopted by the whole helpdesk team.

Education:
A.A. Computer Information Systems, Springfield Community College    2016 - 2018

Skills:
Python, SQL, Zendesk, Jira
"""


def test_education_degree_never_splits_a_word(parser, tmp_path):
    """Regression: 'A.A. Computer Information Systems' rendered as degree=
    'mation Systems' / institution='A.A. Computer Infor' -- a wrong-offset
    slice landing mid-word, not fuzzy AI error. The degree must come out whole
    and the institution must be the actual college name, not a fragment of
    the degree text."""
    p = tmp_path / "r.txt"
    p.write_text(_TWO_JOB_RESUME_WITH_BULLETS)
    parsed = parser.parse(str(p))
    assert len(parsed.education) == 1
    edu = parsed.education[0]
    assert edu.degree == "A.A. Computer Information Systems"
    assert edu.institution == "Springfield Community College"
    assert edu.start_year == "2016"
    assert edu.end_year == "2018"
    # The two concrete corrupt values from the bug report must never recur.
    assert edu.degree != "mation Systems"
    assert edu.institution != "A.A. Computer Infor"
    # Concatenating degree + institution must not reconstruct the full string
    # the way the old wrong-offset split did (proving neither field is a
    # truncated fragment of the other).
    assert edu.institution + edu.degree != "A.A. Computer Infor" + "mation Systems"


def test_degree_regex_does_not_false_positive_on_ordinary_words(parser, tmp_path):
    """Regression: the un-bounded old regex matched the bare 'ma'/'ms' bigram
    anywhere case-insensitively, so an achievement bullet like 'Maintained the
    fleet...' (contains 'ma') was misparsed as a bogus education entry."""
    resume = (
        "Experience:\n"
        "Senior Support Engineer, Acme Corp    Jan 2021 - Present\n"
        "Maintained the fleet with a team of five people.\n"
        "Managed vendor contracts and system upgrades.\n"
    )
    p = tmp_path / "r.txt"
    p.write_text(resume)
    parsed = parser.parse(str(p))
    assert parsed.education == ()
    # The lines stay attached to the job as achievements, not spliced away.
    assert len(parsed.work_history) == 1
    assert "Maintained the fleet with a team of five people." in parsed.work_history[0].achievements


def test_two_job_resume_yields_two_entries_with_separate_fields_and_bullets(parser, tmp_path):
    """Regression: work history jammed title+company into one field, dropped
    achievements (WorkHistoryEntry had no field for them), and a two-job resume
    produced only one entry. All three must now be fixed together."""
    p = tmp_path / "r.txt"
    p.write_text(_TWO_JOB_RESUME_WITH_BULLETS)
    parsed = parser.parse(str(p))

    assert len(parsed.work_history) == 2

    first, second = parsed.work_history
    assert first.title == "Senior Support Engineer"
    assert first.company == "Acme Corp"
    assert second.title == "IT Support Specialist"
    assert second.company == "Globex Industries"
    # Title and company are never the same field jammed together.
    for w in parsed.work_history:
        assert w.title and w.company
        assert w.title != w.company
        assert w.company not in w.title

    # Achievements/bullets survive and are attributed to the correct job.
    assert first.achievements == (
        "Resolved over 200 customer escalations per quarter across enterprise accounts.",
        "Automated the ticket-triage pipeline, cutting median response time by 40%.",
    )
    assert second.achievements == (
        "Maintained a 500-endpoint Windows/macOS fleet with 99.5% uptime.",
        "Built a self-service password-reset tool adopted by the whole helpdesk team.",
    )
    # No bullet leaks across the job boundary.
    assert not any("password-reset" in a for a in first.achievements)
    assert not any("escalations" in a for a in second.achievements)


def test_contact_fields_still_parse_alongside_fixed_extraction(parser, tmp_path):
    """The parsing fixes above must not regress plain identity extraction."""
    p = tmp_path / "r.txt"
    p.write_text(_TWO_JOB_RESUME_WITH_BULLETS)
    parsed = parser.parse(str(p))
    assert parsed.full_name == "Jordan A. Sample"
    assert parsed.email == "jordan.sample@example.com"
    assert "555" in parsed.phone
    assert "Python" in parsed.skills


def test_work_history_title_company_not_jammed_multispace_columns(parser, tmp_path):
    """Regression: a plain-text export using fixed-width columns (spaces, not
    ', '/' at '/tab) jammed 'Title     Company' into ONE field with company
    left empty."""
    resume = (
        "Experience:\n"
        "Senior Support Engineer     Acme Corp    Jan 2021 - Present\n"
        "Resolved customer escalations.\n"
        "IT Support Specialist     Globex Industries    Jun 2018 - Dec 2020\n"
        "Maintained the fleet.\n"
    )
    p = tmp_path / "r.txt"
    p.write_text(resume)
    parsed = parser.parse(str(p))
    assert len(parsed.work_history) == 2
    first, second = parsed.work_history
    assert first.title == "Senior Support Engineer"
    assert first.company == "Acme Corp"
    assert second.title == "IT Support Specialist"
    assert second.company == "Globex Industries"


def test_slash_style_numeric_dates_do_not_drop_the_second_job(parser, tmp_path):
    """Regression: 'MM/YYYY' dates (a very common template format) didn't
    match the date-range regex at all, so the SECOND job's line never matched
    and the whole entry silently vanished -- a two-job resume yielded one
    entry."""
    resume = (
        "Experience:\n"
        "Senior Support Engineer, Acme Corp    01/2021 - Present\n"
        "Resolved customer escalations.\n"
        "IT Support Specialist, Globex Industries    06/2018 - 12/2020\n"
        "Maintained the fleet.\n"
    )
    p = tmp_path / "r.txt"
    p.write_text(resume)
    parsed = parser.parse(str(p))
    assert len(parsed.work_history) == 2
    first, second = parsed.work_history
    assert first.company == "Acme Corp"
    assert first.start_date == "01/2021"
    assert second.company == "Globex Industries"
    assert second.start_date == "06/2018"
    assert second.end_date == "12/2020"


def test_work_history_heading_variant_is_recognized(parser, tmp_path):
    """Regression: a 'Work History:' heading (not in the recognized-heading
    list) fell through to whole-document fallback scanning, which spliced an
    unrelated education line in as a bogus THIRD work-history entry."""
    resume = (
        "Jordan Sample\n"
        "jordan@example.com\n\n"
        "Work History:\n"
        "Senior Support Engineer, Acme Corp    Jan 2021 - Present\n"
        "Resolved customer escalations.\n"
        "IT Support Specialist, Globex Industries    Jun 2018 - Dec 2020\n"
        "Maintained the fleet.\n\n"
        "Education:\n"
        "A.A. Computer Information Systems, Springfield Community College    2016 - 2018\n"
    )
    p = tmp_path / "r.txt"
    p.write_text(resume)
    parsed = parser.parse(str(p))
    assert len(parsed.work_history) == 2
    assert {w.company for w in parsed.work_history} == {"Acme Corp", "Globex Industries"}
    assert len(parsed.education) == 1
    assert parsed.education[0].degree == "A.A. Computer Information Systems"
