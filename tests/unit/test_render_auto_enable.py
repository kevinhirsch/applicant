"""Auto-enable real compile/convert when the engine is present (FR-RESUME-4).

Production previously hard-disabled the real render (``allow_compile=False`` /
``allow_convert=False``), so it always used the line-count estimate and ASSUMED
fonts embedded. The engines now default to ``render_mode="auto"``: the real
compile/convert auto-enables when the engine binary is on PATH at runtime, and
degrades to the deterministic stub when absent — keeping the hermetic lane green.

Hermetic: PATH lookups are mocked at the marked seam; no TeX/LibreOffice required.
"""

from __future__ import annotations

from applicant.adapters.resume_tailoring import docx_tailor as docx_mod
from applicant.adapters.resume_tailoring import latex_tailor as latex_mod
from applicant.adapters.resume_tailoring.docx_tailor import DocxTailor
from applicant.adapters.resume_tailoring.latex_tailor import LatexTailor


def test_latex_auto_off_when_no_engine(monkeypatch):
    monkeypatch.setattr(latex_mod.shutil, "which", lambda _name: None)
    tailor = LatexTailor(render_mode="auto")
    # No TeX engine -> the real compile is NOT enabled (degrade to estimate stub).
    assert tailor._allow_compile is False


def test_latex_auto_on_when_engine_present(monkeypatch):
    monkeypatch.setattr(
        latex_mod.shutil,
        "which",
        lambda name: "/usr/bin/lualatex" if name in ("lualatex", "xelatex") else None,
    )
    tailor = LatexTailor(render_mode="auto")
    # A TeX engine on PATH -> the real compile-and-inspect path auto-enables.
    assert tailor._allow_compile is True


def test_latex_off_mode_never_compiles(monkeypatch):
    monkeypatch.setattr(latex_mod.shutil, "which", lambda _name: "/usr/bin/lualatex")
    assert LatexTailor(render_mode="off")._allow_compile is False
    # Back-compat: allow_compile=False maps to "off".
    assert LatexTailor(allow_compile=False)._allow_compile is False


def test_latex_on_mode_forces_compile(monkeypatch):
    monkeypatch.setattr(latex_mod.shutil, "which", lambda _name: None)
    assert LatexTailor(render_mode="on")._allow_compile is True
    assert LatexTailor(allow_compile=True)._allow_compile is True


def test_docx_auto_off_when_no_soffice(monkeypatch):
    monkeypatch.setattr(docx_mod.shutil, "which", lambda _name: None)
    assert DocxTailor(render_mode="auto")._allow_convert is False


def test_docx_auto_on_when_soffice_present(monkeypatch):
    monkeypatch.setattr(
        docx_mod.shutil,
        "which",
        lambda name: "/usr/bin/soffice" if name in ("soffice", "libreoffice") else None,
    )
    assert DocxTailor(render_mode="auto")._allow_convert is True


def test_default_lane_latex_stays_stub_without_tex():
    """In the real hermetic env (no TeX) the default auto tailor uses the stub."""
    from applicant.core.ids import ResumeVariantId, new_id

    tailor = LatexTailor()  # default render_mode="auto"
    result = tailor.render_artifact(
        ResumeVariantId(new_id()), "\\section{Skills}\nPython, SQL\n"
    )
    # Stub path: estimate-based page count, no "no TeX engine" soft error.
    assert result.page_count >= 1
    assert "no TeX engine available" not in result.notes
