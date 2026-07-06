"""LatexTailor pure-logic + compile-seam coverage (FR-RESUME-3/4/5/8, FR-FONT-2).

Hermetic: NO real TeX engine. The em-dash post-filter, cover-letter builder,
page-fit / orphaned-title heuristics, and redline are exercised as pure transforms.
The compile seam (``_compile_pdf``/``_inspect_pdf``) is driven by mocking
``shutil.which`` + ``subprocess.run`` so the real-compile branch runs against a PDF
synthesized with pypdf (already a dependency) instead of a TeX install.
"""

from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path

from applicant.adapters.resume_tailoring import latex_tailor as latex_mod
from applicant.adapters.resume_tailoring.latex_tailor import (
    _LINES_PER_PAGE,
    LatexTailor,
)
from applicant.core.ids import ResumeVariantId, new_id
from applicant.core.rules.truthfulness import contains_emdash


# --- PDF synthesis helper (hermetic stand-in for a TeX compile) -------------
def _write_pdf(path: Path, *, pages: int = 1, embedded: bool = True) -> None:
    """Write a real PDF with ``pages`` pages; the first carries a font resource.

    When ``embedded`` is True the font descriptor carries a ``/FontFile2`` stream
    (exactly what the fidelity check requires); otherwise it is a name-only
    standard-14-style font with no font-file stream (NOT embedded).
    """
    from pypdf import PdfWriter
    from pypdf.generic import DictionaryObject, NameObject, StreamObject

    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=200, height=200)

    descriptor = DictionaryObject()
    descriptor[NameObject("/Type")] = NameObject("/FontDescriptor")
    if embedded:
        stream = StreamObject()
        stream.set_data(b"fake font program bytes")
        descriptor[NameObject("/FontFile2")] = writer._add_object(stream)

    font = DictionaryObject()
    font[NameObject("/Type")] = NameObject("/Font")
    font[NameObject("/Subtype")] = NameObject("/TrueType")
    font[NameObject("/FontDescriptor")] = writer._add_object(descriptor)

    fonts = DictionaryObject()
    fonts[NameObject("/F1")] = writer._add_object(font)
    resources = DictionaryObject()
    resources[NameObject("/Font")] = fonts
    writer.pages[0][NameObject("/Resources")] = resources

    with open(path, "wb") as fh:
        writer.write(fh)


# === cover letter (FR-RESUME-10) ===========================================
def test_build_cover_source_renders_one_page_cover_class():
    tailor = LatexTailor()
    source = tailor.build_cover_source(
        first_name="Ada",
        last_name="Lovelace",
        contact_line="ada@example.com",
        date="2026-06-17",
        company="Analytical Engines Inc",
        company_address="1 Babbage Way",
        body_paragraphs=["I am writing to apply.", "  ", "I build real things."],
        closing="Best,",
        signature="Ada Lovelace",
    )
    # Carries the cover.cls marker the fidelity check keys on (exactly one page).
    assert "\\documentclass[]{cover}" in source
    assert "\\begin{document}" in source and "\\end{document}" in source
    assert "\\namesection{Ada}{Lovelace}{ada@example.com}" in source
    assert "\\companyname{Analytical Engines Inc}" in source
    assert "\\closing{Best,}" in source
    assert "\\signature{Ada Lovelace}" in source
    # Blank/whitespace-only paragraphs are dropped; real ones become lettercontent.
    assert source.count("\\lettercontent{") == 2
    assert "\\lettercontent{I am writing to apply.}" in source

    # And the builder feeds the fidelity check a clean one-page source. The
    # explicit stub lane ("off") models the checks on the source; HONESTY: it
    # never claims a real artifact or a faithful match for a PDF it didn't build.
    stub = LatexTailor(render_mode="off")
    result = stub.render_artifact(ResumeVariantId(new_id()), source)
    assert result.page_count == 1
    assert result.fidelity_ok is True  # source-level checks all pass
    assert result.artifact_available is False
    assert "source-level check only" in result.notes
    assert "faithful match" not in result.notes


def test_build_cover_source_strips_emdash_in_every_field():
    tailor = LatexTailor()
    source = tailor.build_cover_source(
        first_name="A—B",
        company="Foo — Bar",
        body_paragraphs=["Led a team — shipped a product"],
    )
    assert not contains_emdash(source)


def test_build_cover_source_escapes_latex_specials_in_body():
    """Regression: a cover body with LaTeX specials (%&$#_{}) must be ESCAPED so the
    xelatex compile cannot break on an unescaped char or unbalanced brace."""
    tailor = LatexTailor()
    source = tailor.build_cover_source(
        first_name="Jane",
        company="R&D Co_50% {Group}",
        body_paragraphs=["Saved 30% on cost & cut churn; ref #42 for the $1M_deal {2024}."],
    )
    # Every special char round-trips to its escaped form, not the raw literal.
    assert "30\\%" in source
    assert "\\&" in source
    assert "\\$" in source
    assert "\\_" in source
    assert "\\#" in source
    assert "\\{" in source and "\\}" in source
    # The recipient/company field is escaped on the same path as the résumé.
    assert "R\\&D Co\\_50\\% \\{Group\\}" in source
    # No UNescaped special survives in the body content (defensive sweep).
    body_line = next(ln for ln in source.splitlines() if "\\lettercontent{" in ln)
    inner = body_line[len("\\lettercontent{") : -1]
    for ch in ("%", "&", "$", "#"):
        # each occurrence of the special must be immediately preceded by a backslash
        idx = 0
        while (idx := inner.find(ch, idx)) != -1:
            assert inner[idx - 1] == "\\", f"unescaped {ch!r} in cover body"
            idx += 1


def test_build_cover_source_defaults_to_no_body():
    tailor = LatexTailor()
    source = tailor.build_cover_source(first_name="Solo")
    assert "\\lettercontent{" not in source  # body_paragraphs=None -> no content
    assert "\\closing{Sincerely,}" in source  # default closing


# === page-fit + orphan heuristics (FR-RESUME-4) ============================
def test_estimate_pages_empty_source_is_one_page():
    tailor = LatexTailor()
    # Only comments/blank lines -> no body -> still 1 page (never 0).
    assert tailor._estimate_pages("% just a comment\n\n   \n") == 1


def test_estimate_pages_uses_ceiling_of_body_lines():
    tailor = LatexTailor()
    body = "\n".join(f"line {i}" for i in range(_LINES_PER_PAGE + 1))
    # one over a full page -> ceil division -> 2 pages.
    assert tailor._estimate_pages(body) == 2


def test_expected_pages_cover_letter_is_one_even_when_long():
    tailor = LatexTailor()
    long_cover = "\\documentclass[]{cover}\n" + "\n".join(
        f"\\lettercontent{{para {i}}}" for i in range(_LINES_PER_PAGE * 2)
    )
    # A cover letter is contractually one page regardless of body length.
    assert tailor._expected_pages(long_cover) == 1


def test_expected_pages_namesection_marker_also_forces_one_page():
    tailor = LatexTailor()
    assert tailor._expected_pages("\\namesection{A}{B}{c}\nbody") == 1


def test_body_lines_skips_blank_and_comment_lines():
    tailor = LatexTailor()
    src = "real one\n% a comment\n   \n  % indented comment\nreal two\n"
    assert tailor._body_lines(src) == ["real one", "real two"]


def test_orphaned_title_flagged_when_section_near_page_bottom_unguarded():
    tailor = LatexTailor()
    # Pad to the bottom of page 1, then a \section with NO \needspace guard.
    filler = [f"body line {i}" for i in range(_LINES_PER_PAGE - 1)]
    lines = filler + ["\\section{Orphaned Skills}"]
    source = "\n".join(lines)
    orphans = tailor._orphaned_titles(source)
    assert "Orphaned Skills" in orphans

    # And it propagates to a failing fidelity check (resume body fits on 1 page so
    # page-fit itself passes, isolating the orphan signal).
    result = tailor.render_artifact(ResumeVariantId(new_id()), source)
    assert result.fidelity_ok is False
    assert "section heading may be stranded" in result.notes


def test_orphaned_title_not_flagged_when_needspace_guarded():
    tailor = LatexTailor()
    filler = [f"body line {i}" for i in range(_LINES_PER_PAGE - 2)]
    lines = filler + ["\\needspace{4\\baselineskip}", "\\section{Guarded Skills}"]
    source = "\n".join(lines)
    assert tailor._orphaned_titles(source) == []


def test_orphaned_title_not_flagged_mid_page():
    tailor = LatexTailor()
    # A section near the top of the page is never an orphan risk.
    source = "intro\n\\section{Skills}\nPython\n"
    assert tailor._orphaned_titles(source) == []


# === render_artifact fidelity branches =====================================
def test_overlong_resume_fails_page_fit_with_honest_note():
    tailor = LatexTailor()
    body = "\n".join(f"\\item bullet {i}" for i in range(_LINES_PER_PAGE * 3))
    source = f"\\documentclass{{moderncv}}\n{body}\n"
    result = tailor.render_artifact(ResumeVariantId(new_id()), source)
    # Multi-page resume: estimate==expected so page-fit passes, count reported honestly.
    assert result.page_count > 1


def test_render_reports_emdash_survivor_defensively(monkeypatch):
    # Defensive guard: if normalize somehow left a dash, the check flags it.
    monkeypatch.setattr(latex_mod, "normalize_emdashes", lambda s: s)
    tailor = LatexTailor()
    result = tailor.render_artifact(ResumeVariantId(new_id()), "Engineer — lead")
    assert result.fidelity_ok is False
    assert "em-dash survived the post-filter" in result.notes


# === redline (FR-RESUME-8) =================================================
def test_redline_pure_insert_only_additions():
    tailor = LatexTailor()
    vid = ResumeVariantId(new_id())
    result = tailor.render_redline(vid, "line one", "line one\nline two")
    assert result.additions == ("line two",)
    assert result.subtractions == ()
    assert "redline-add" in result.rendered_html
    assert "redline-eq" in result.rendered_html  # equal line carried through


def test_redline_pure_delete_only_subtractions():
    tailor = LatexTailor()
    vid = ResumeVariantId(new_id())
    result = tailor.render_redline(vid, "keep\ndrop", "keep")
    assert result.subtractions == ("drop",)
    assert result.additions == ()
    assert "redline-sub" in result.rendered_html


def test_redline_escapes_html_special_chars():
    tailor = LatexTailor()
    vid = ResumeVariantId(new_id())
    result = tailor.render_redline(vid, "a & b < c", "x > y & z")
    # Both the add and the sub sides are HTML-escaped in the rendered diff.
    assert "&amp;" in result.rendered_html
    assert "&lt;" in result.rendered_html
    assert "&gt;" in result.rendered_html
    assert "< c" not in result.rendered_html  # raw '<' never leaks


def test_redline_normalizes_emdash_before_diffing():
    # An em-dash difference that normalizes away must NOT show as a content change.
    tailor = LatexTailor()
    vid = ResumeVariantId(new_id())
    result = tailor.render_redline(vid, "a, b", "a — b")
    assert result.additions == ()
    assert result.subtractions == ()


# === edit_source (FR-RESUME-3) =============================================
def test_edit_source_escapes_substituted_content_to_block_injection():
    # SECURITY: substituted CONTENT is LaTeX-escaped (anchors matched verbatim).
    tailor = LatexTailor()
    out = tailor.edit_source(
        "\\section{Skills}\nPLACEHOLDER",
        {"PLACEHOLDER": "100% & \\input{/etc/passwd}"},
    )
    # The dangerous control sequence is neutralized via escaping.
    assert "\\input{/etc/passwd}" not in out
    assert "\\%" in out and "\\&" in out
    assert "\\textbackslash{}input" in out


def test_edit_source_runs_emdash_filter_on_result():
    tailor = LatexTailor()
    out = tailor.edit_source("HOLE", {"HOLE": "fast — efficient"})
    assert not contains_emdash(out)


# === compile seam: real-compile branch driven hermetically =================
def test_inspect_pdf_counts_pages_and_detects_embedded_fonts():
    with tempfile.TemporaryDirectory() as d:
        pdf = Path(d) / "two_pages.pdf"
        _write_pdf(pdf, pages=2, embedded=True)
        page_count, fonts_embedded = LatexTailor._inspect_pdf(pdf)
        assert page_count == 2
        assert fonts_embedded is True


def test_inspect_pdf_flags_non_embedded_font():
    with tempfile.TemporaryDirectory() as d:
        pdf = Path(d) / "name_only_font.pdf"
        _write_pdf(pdf, pages=1, embedded=False)
        page_count, fonts_embedded = LatexTailor._inspect_pdf(pdf)
        assert page_count == 1
        assert fonts_embedded is False


def _fake_engine(monkeypatch):
    """Make the engine 'present' so the real-compile branch runs."""
    monkeypatch.setattr(latex_mod.shutil, "which", lambda _name: "/usr/bin/lualatex")


def test_real_compile_inspects_produced_pdf(monkeypatch, tmp_path):
    _fake_engine(monkeypatch)

    def fake_run(cmd, cwd, env, capture_output, timeout, check):
        # Simulate a successful TeX compile by writing the expected resume.pdf.
        _write_pdf(Path(cwd) / "resume.pdf", pages=1, embedded=True)
        return subprocess.CompletedProcess(cmd, 0, b"", b"")

    monkeypatch.setattr(latex_mod.subprocess, "run", fake_run)
    tailor = LatexTailor(render_mode="on", output_dir=tmp_path)
    vid = ResumeVariantId(new_id())
    result = tailor.render_artifact(vid, "\\documentclass[]{cover}\n\\namesection{A}{B}{c}\nbody\n")

    # Real compile path: storage path points at the produced PDF, fidelity passes,
    # and ONLY here may the result claim a real artifact / faithful match.
    assert result.storage_path.endswith("resume.pdf")
    assert result.page_count == 1
    assert result.fidelity_ok is True
    assert result.artifact_available is True
    assert result.notes == "Looks like a faithful match."
    assert "no TeX engine available" not in result.notes


def test_real_compile_subprocess_error_degrades_to_stub(monkeypatch, tmp_path):
    _fake_engine(monkeypatch)

    def boom(*_a, **_k):
        raise subprocess.SubprocessError("engine crashed")

    monkeypatch.setattr(latex_mod.subprocess, "run", boom)
    tailor = LatexTailor(render_mode="on", output_dir=tmp_path)
    result = tailor.render_artifact(ResumeVariantId(new_id()), "\\section{Skills}\nPython\n")
    # Compile failed: synthetic storage path + estimate, fonts assumed embedded.
    assert result.storage_path == f"artifacts/{result.storage_path.split('/')[-1]}"
    assert result.page_count >= 1


def test_real_compile_missing_pdf_reports_render_failure(monkeypatch, tmp_path):
    _fake_engine(monkeypatch)

    def no_pdf(cmd, cwd, env, capture_output, timeout, check):
        # Engine "ran" but produced no PDF (e.g. fatal TeX error). This is the user's
        # actual symptom on the deploy image.
        return subprocess.CompletedProcess(cmd, 1, b"", b"! LaTeX Error")

    monkeypatch.setattr(latex_mod.subprocess, "run", no_pdf)
    tailor = LatexTailor(render_mode="on", output_dir=tmp_path)
    result = tailor.render_artifact(ResumeVariantId(new_id()), "\\section{Skills}\nPython\n")
    # No PDF -> honest "render failed" note, NOT a misleading "fonts not embedded" or
    # "no engine" claim, and white-labeled + actionable (rebuild).
    assert result.fidelity_ok is False
    assert "approximate preview" in result.notes
    assert "rebuild the engine" in result.notes.lower()
    assert "fonts in the rendered PDF are not embedded" not in result.notes
    assert "no TeX engine available" not in result.notes


def test_compile_requested_but_no_engine_degrades_cleanly(monkeypatch):
    # render_mode="on" forces compile but no engine on PATH -> white-labeled degrade.
    monkeypatch.setattr(latex_mod.shutil, "which", lambda _name: None)
    tailor = LatexTailor(render_mode="on")
    result = tailor.render_artifact(ResumeVariantId(new_id()), "\\section{S}\nbody\n")
    assert "approximate preview" in result.notes
    assert "rebuild the engine" in result.notes.lower()
    # The old misleading/jargon strings are gone.
    assert "no TeX engine available" not in result.notes
    assert "TeX" not in result.notes


def test_real_compile_page_mismatch_fails_page_fit(monkeypatch, tmp_path):
    # A cover letter (expected==1) that really compiles to 2 pages fails page-fit:
    # this is the "looks fine in source is not acceptable" guarantee in action.
    _fake_engine(monkeypatch)

    def two_pages(cmd, cwd, env, capture_output, timeout, check):
        _write_pdf(Path(cwd) / "resume.pdf", pages=2, embedded=True)
        return subprocess.CompletedProcess(cmd, 0, b"", b"")

    monkeypatch.setattr(latex_mod.subprocess, "run", two_pages)
    tailor = LatexTailor(render_mode="on", output_dir=tmp_path)
    source = "\\documentclass[]{cover}\n\\namesection{A}{B}{c}\nbody\n"
    result = tailor.render_artifact(ResumeVariantId(new_id()), source)
    assert result.page_count == 2  # honest compiled count
    assert result.fidelity_ok is False
    assert "rendered 2 page(s), expected 1" in result.notes


def test_inspect_pdf_ignores_pages_without_resources():
    # A blank page carries no /Resources; the font check skips it (stays embedded).
    with tempfile.TemporaryDirectory() as d:
        from pypdf import PdfWriter

        pdf = Path(d) / "blank.pdf"
        writer = PdfWriter()
        writer.add_blank_page(width=200, height=200)
        with open(pdf, "wb") as fh:
            writer.write(fh)
        page_count, fonts_embedded = LatexTailor._inspect_pdf(pdf)
        assert page_count == 1
        assert fonts_embedded is True  # no fonts to disprove embedding


def test_inspect_pdf_ignores_resources_without_font_dict():
    # A page can carry /Resources with no /Font entry -> skipped (stays embedded).
    with tempfile.TemporaryDirectory() as d:
        from pypdf import PdfWriter
        from pypdf.generic import DictionaryObject, NameObject

        pdf = Path(d) / "no_font.pdf"
        writer = PdfWriter()
        writer.add_blank_page(width=200, height=200)
        resources = DictionaryObject()
        resources[NameObject("/ProcSet")] = NameObject("/PDF")  # resources, but no /Font
        writer.pages[0][NameObject("/Resources")] = resources
        with open(pdf, "wb") as fh:
            writer.write(fh)
        page_count, fonts_embedded = LatexTailor._inspect_pdf(pdf)
        assert page_count == 1
        assert fonts_embedded is True


def test_font_is_embedded_false_for_non_dict_shape():
    # A font object that is not dict-like cannot prove embedding -> NOT embedded.
    assert latex_mod._font_is_embedded(object()) is False
    assert latex_mod._font_is_embedded("not a font") is False


def test_real_compile_writes_source_and_uses_output_dir(monkeypatch, tmp_path):
    _fake_engine(monkeypatch)
    captured = {}

    def fake_run(cmd, cwd, env, capture_output, timeout, check):
        captured["cwd"] = cwd
        captured["env"] = env
        captured["source"] = (Path(cwd) / "resume.tex").read_text(encoding="utf-8")
        _write_pdf(Path(cwd) / "resume.pdf", pages=1, embedded=True)
        return subprocess.CompletedProcess(cmd, 0, b"", b"")

    monkeypatch.setattr(latex_mod.subprocess, "run", fake_run)
    tailor = LatexTailor(render_mode="on", output_dir=tmp_path)
    vid = ResumeVariantId(new_id())
    tailor.render_artifact(vid, "\\section{Skills}\nPython, SQL\n")

    # The .tex source was written into a per-variant dir under output_dir.
    assert captured["source"].startswith("\\section{Skills}")
    assert str(tmp_path) in captured["cwd"]
    assert str(vid) in captured["cwd"]
    # The compile env preserves PATH (vendored TEXINPUTS prepended).
    assert "TEXINPUTS" in captured["env"]
    assert os.path.sep in captured["env"]["PATH"]
