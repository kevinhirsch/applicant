"""ATS-parseability proof (P2-10) — integration only, real rendered PDFs.

Every existing ``ats_parseability``/parser test (``tests/unit/test_ats.py``,
``tests/bdd/steps/test_enh_spirit_steps.py``, ``tests/unit/test_cov_backlog_
resumehealth.py``) exercises ``check_render_parseability``/``ResumeParser``
against **source text handed to the check directly** — the compile/convert
boundary is always stubbed (no TeX/LibreOffice required), which is correct for
the hermetic default lane but stops short of the P2-10 claim: "generated PDFs
run through an open-source ATS parser; fields extract cleanly."

This module closes that gap: it renders a REAL PDF through each résumé path —
the LaTeX/moderncv primary path (``templates/latex/``) and the docx-XML
fallback path (``templates/docx/``, in-place OOXML edit) — and feeds the
resulting PDF FILE (not a text string) to the exact ``ResumeParser`` class the
engine uses to ingest an uploaded résumé (``adapters/resume_parser/
resume_parser.py``, itself built on ``pypdf`` text extraction — the same
text-layer approach real-world ATS ingestion pipelines use). That parser
recovering the contact block, section headers, and skills from a rendered PDF
is the citable "ATS-safe" evidence; ``core.rules.ats_parseability.
check_render_parseability`` (already wired into ``submission_service.
_verify_ats_parse`` pre-submit) is run over the same extracted text as a second,
independent confirmation.

Both render paths gate on a real system binary that ``shutil.which()`` may not
find in every environment (``docker/Dockerfile`` bakes both into the deploy
image; see CLAUDE.md's runtime-dependencies note) — each test is
``@pytest.mark.integration`` and self-skips when its binary is absent, exactly
like ``tests/integration/test_resume_render_real.py``. Honest split (see
``docs/proof/ats-parseability.md`` for a captured run + which lane executed
where):

* **docx path** — LibreOffice (``soffice``) is commonly present even on a bare
  container/CI box, so this test frequently runs in the SAME hermetic-looking
  lane as everything else (still gated ``integration`` so it never blocks the
  default `-m "not integration"` run).
* **LaTeX path** — needs xelatex/lualatex + moderncv/fontspec/fontawesome5,
  which is NOT baked into a bare dev container; it runs on the self-hosted
  Integration Lane (``.github/workflows/ci-integration.yml``, which verifies
  TeX is pre-baked on the runner) and skips everywhere else. A skip here is a
  signal the deployed engine image needs the dependency, not a pass (H-series:
  absence of a check must never render as a check — the assertions below only
  run for real when the artifact was actually produced).
"""

from __future__ import annotations

import shutil
import zipfile

import pytest

from applicant.adapters.resume_parser.resume_parser import ResumeParser
from applicant.adapters.resume_tailoring.docx_tailor import (
    DocxTailor,
    write_document_xml,
)
from applicant.adapters.resume_tailoring.latex_tailor import LatexTailor
from applicant.adapters.resume_tailoring.moderncv_converter import ModerncvConverter
from applicant.core.ids import ResumeVariantId, new_id
from applicant.core.rules.ats_parseability import check_render_parseability

_HAS_TEX = shutil.which("lualatex") or shutil.which("xelatex")
_HAS_SOFFICE = shutil.which("soffice") or shutil.which("libreoffice")

# A deliberately realistic multi-section résumé: contact block, two work-history
# entries (so the "cleaned up" tailored edit below targets a real one), education,
# and a skills line — the same shape ``_verify_ats_parse`` demands (name, work
# history, skills, contact) plus the section headers ``check_render_parseability``
# looks for.
_SAMPLE_RESUME = """Jane Q. Applicant
jane.applicant@example.com
+1 555 987 6543

Summary
Backend engineer who ships reliable systems.

Experience
Senior Backend Engineer, Acme Corp    Jan 2021 - Present
Built the payments platform serving 2M requests/day.
Software Engineer, Foo Industries    Jun 2017 - Dec 2020
Shipped the search-ranking service.

Education
B.S. Computer Science, State University    2013 - 2017

Skills
Python, PostgreSQL, Kubernetes, Terraform
"""


def _assert_recovers_expected_fields(parsed) -> None:
    """The citable claim: identity, work history, and skills survive the render."""
    assert parsed.full_name, "no name recovered from the rendered PDF"
    assert parsed.email == "jane.applicant@example.com"
    assert parsed.skills, "no skills recovered from the rendered PDF"
    assert any("python" in s.lower() for s in parsed.skills)
    assert parsed.work_history, "no work history recovered from the rendered PDF"
    assert any("Senior Backend Engineer" in w.title for w in parsed.work_history)


@pytest.mark.integration
@pytest.mark.skipif(not _HAS_SOFFICE, reason="No LibreOffice (soffice) installed.")
def test_docx_rendered_pdf_round_trips_through_the_deterministic_parser(tmp_path):
    """docx fallback path: build -> tailor-edit -> real soffice PDF -> parse.

    Builds a base .docx, edits its ``word/document.xml`` in place with the SAME
    ``DocxTailor.edit_document_xml`` production uses for a tailoring pass,
    converts it to a real PDF with LibreOffice headless, then hands that PDF
    FILE to ``ResumeParser`` — the same class ``OnboardingService`` uses on an
    uploaded résumé and ``submission_service._verify_ats_parse`` demands before
    a generated résumé is allowed to reach final submit.
    """
    import docx

    d = docx.Document()
    for line in _SAMPLE_RESUME.splitlines():
        d.add_paragraph(line)
    src = tmp_path / "base.docx"
    d.save(str(src))

    with zipfile.ZipFile(str(src)) as zf:
        xml = zf.read("word/document.xml").decode("utf-8")
    edited = DocxTailor().edit_document_xml(xml, {"Foo Industries": "Bar Industries"})
    out_docx = tmp_path / "tailored.docx"
    write_document_xml(str(src), str(out_docx), edited)

    adapter = DocxTailor(allow_convert=True, output_dir=tmp_path)
    result = adapter.render_artifact(ResumeVariantId(new_id()), str(out_docx))
    if not result.artifact_available:
        pytest.skip(
            f"LibreOffice present but produced no real PDF in this environment: {result.notes}"
        )

    assert result.fidelity_ok, result.notes
    parsed = ResumeParser().parse(result.storage_path)
    _assert_recovers_expected_fields(parsed)
    # The tailoring edit survived the docx -> PDF -> text round trip.
    assert "Bar Industries" in parsed.raw_text
    assert "Foo Industries" not in parsed.raw_text

    report = check_render_parseability(parsed.raw_text)
    assert report.parseable, report.reason


@pytest.mark.integration
@pytest.mark.skipif(not _HAS_TEX, reason="No TeX engine (lualatex/xelatex) installed.")
def test_latex_rendered_pdf_round_trips_through_the_deterministic_parser(tmp_path):
    """LaTeX primary path (moderncv): convert -> real xelatex/lualatex PDF -> parse.

    The parsed sample résumé is templated into a real moderncv ``.tex`` source
    (``ModerncvConverter``, hermetic), compiled with the real TeX engine
    (``LatexTailor(allow_compile=True)``), and the resulting PDF FILE is fed to
    the same ``ResumeParser`` as the docx test above.
    """
    converter = ModerncvConverter(resume_parser=ResumeParser())
    tex_source = converter.convert_text(_SAMPLE_RESUME).tex_source

    adapter = LatexTailor(allow_compile=True, output_dir=tmp_path)
    result = adapter.render_artifact(ResumeVariantId(new_id()), tex_source)
    if not result.artifact_available:
        pytest.skip(f"TeX present but produced no real PDF in this environment: {result.notes}")

    assert result.fidelity_ok, result.notes
    parsed = ResumeParser().parse(result.storage_path)
    _assert_recovers_expected_fields(parsed)

    report = check_render_parseability(parsed.raw_text)
    assert report.parseable, report.reason
