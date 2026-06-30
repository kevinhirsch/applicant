"""Auto-enable real compile/convert when the engine is present (FR-RESUME-4).

Production previously hard-disabled the real render (``allow_compile=False`` /
``allow_convert=False``), so it always used the line-count estimate and ASSUMED
fonts embedded. The engines now default to ``render_mode="auto"``: the real
compile/convert auto-enables when the engine binary is on PATH at runtime, and
degrades to the deterministic stub when absent — keeping the hermetic lane green.

Hermetic: PATH lookups are mocked at the marked seam; no TeX/LibreOffice required.
"""

from __future__ import annotations

from pathlib import Path

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


def test_default_lane_latex_stays_stub_without_tex(monkeypatch):
    """With no TeX engine on PATH the default auto tailor uses the stub.

    The PATH lookup is mocked so this stays deterministic whether or not the host
    actually has a TeX engine installed (the deploy image does)."""
    from applicant.core.ids import ResumeVariantId, new_id

    monkeypatch.setattr(latex_mod.shutil, "which", lambda _name: None)
    tailor = LatexTailor()  # default render_mode="auto"
    result = tailor.render_artifact(
        ResumeVariantId(new_id()), "\\section{Skills}\nPython, SQL\n"
    )
    # Stub path: estimate-based page count, no "no TeX engine" soft error.
    assert result.page_count >= 1
    assert "no TeX engine available" not in result.notes


# --- degradation messaging (the user-reported regression) -------------------
# The user saw the misleading note "compile requested but no TeX engine available"
# even though TeX WAS installed (the deploy image bakes it in): the real compile was
# enabled but produced no PDF. These tests pin the corrected, white-labeled, actionable
# messaging for both the "engine ran but failed" and the "no engine installed" cases —
# and prove the stale jargon strings are gone.

# Codename / FR-jargon denylist mirrored from the white-label CI check + spec jargon
# that must never reach a user-facing note.
_BANNED_NOTE_SUBSTRINGS = (
    "no TeX engine available",
    "convert requested but no LibreOffice/Word available",
    "compile requested",
    "FR-",
    "NFR-",
    "TeX",
    "LibreOffice",
    "xelatex",
    "lualatex",
)


def _assert_white_labeled(notes: str) -> None:
    for banned in _BANNED_NOTE_SUBSTRINGS:
        assert banned not in notes, f"user-facing note leaked {banned!r}: {notes!r}"


def test_latex_compile_failure_is_honest_and_white_labeled(monkeypatch, tmp_path):
    """Engine present + enabled but the compile yields no PDF -> honest, actionable note.

    This is exactly the user's symptom: a present TeX engine but no PDF. The note must
    NOT claim "no TeX engine available", must not flag a bogus "fonts not embedded",
    and must be white-labeled + tell the user what to do (rebuild)."""
    from applicant.core.ids import ResumeVariantId, new_id

    # A TeX engine IS on PATH (so the real compile is enabled)...
    monkeypatch.setattr(
        latex_mod.shutil,
        "which",
        lambda name: f"/usr/bin/{name}" if name in ("lualatex", "xelatex") else None,
    )
    # ...but every compile invocation produces no PDF (simulate the deploy-image failure).
    monkeypatch.setattr(latex_mod.subprocess, "run", lambda *a, **k: None)

    tailor = LatexTailor(render_mode="auto", output_dir=tmp_path)
    assert tailor._allow_compile is True
    result = tailor.render_artifact(
        ResumeVariantId(new_id()), "\\section{Skills}\nPython, SQL\n"
    )
    assert result.fidelity_ok is False
    # Honest: it's a render failure, not a missing-engine or font-embedding problem.
    assert "approximate preview" in result.notes
    assert "rebuild the engine" in result.notes.lower()
    assert "fonts in the rendered PDF are not embedded" not in result.notes
    _assert_white_labeled(result.notes)


def test_latex_no_engine_degrades_cleanly(monkeypatch, tmp_path):
    """RESUME_RENDER=on but no engine installed -> clean, white-labeled degrade note."""
    from applicant.core.ids import ResumeVariantId, new_id

    monkeypatch.setattr(latex_mod.shutil, "which", lambda _name: None)
    tailor = LatexTailor(render_mode="on", output_dir=tmp_path)  # forced, but no engine
    result = tailor.render_artifact(
        ResumeVariantId(new_id()), "\\section{Skills}\nPython, SQL\n"
    )
    assert result.fidelity_ok is False
    assert "approximate preview" in result.notes
    _assert_white_labeled(result.notes)


def test_latex_compile_env_keeps_path_and_adds_writable_cache(monkeypatch, tmp_path):
    """The compile env must NOT strip PATH, and must give TeX a writable cache.

    The classic silent-degradation bug is a subprocess env without /usr/bin on PATH
    (binary not found) or an unwritable HOME/TEXMFVAR (first-run cache build aborts,
    no PDF). Assert both are handled."""
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    tailor = LatexTailor(render_mode="auto", output_dir=tmp_path)
    work = tmp_path / "work"
    work.mkdir()
    env = tailor._compile_env("/usr/bin/lualatex", work)
    # PATH preserves the engine dir AND the inherited system path (binary findable).
    assert "/usr/bin" in env["PATH"]
    # A writable cache is provided so the first-run font/format cache build can't abort.
    for key in ("HOME", "TEXMFVAR", "TEXMFCACHE"):
        assert env[key]
        assert Path(env[key]).is_dir()


def test_latex_falls_back_to_other_engine(monkeypatch, tmp_path):
    """If the preferred engine fails, the adapter tries the other one before degrading."""
    from applicant.core.ids import ResumeVariantId, new_id

    monkeypatch.setattr(
        latex_mod.shutil,
        "which",
        lambda name: f"/usr/bin/{name}" if name in ("lualatex", "xelatex") else None,
    )
    calls: list[str] = []

    def fake_run(cmd, *a, **k):
        calls.append(cmd[0])
        # Only the SECOND engine "produces" a PDF.
        if len(calls) >= 2:
            (Path(k["cwd"]) / "resume.pdf").write_bytes(b"%PDF-1.4\n%%EOF\n")
        return None

    monkeypatch.setattr(latex_mod.subprocess, "run", fake_run)
    # Force a degenerate inspect so we don't need pypdf to parse the stub bytes.
    monkeypatch.setattr(
        LatexTailor, "_inspect_pdf", staticmethod(lambda _p: (1, True))
    )
    tailor = LatexTailor(render_mode="auto", output_dir=tmp_path)
    result = tailor.render_artifact(ResumeVariantId(new_id()), "\\section{Skills}\nPython\n")
    # Both engines were tried; the second produced the PDF (no degrade note).
    assert len(calls) == 2
    assert "approximate preview" not in result.notes


def test_docx_convert_failure_is_honest_and_white_labeled(monkeypatch, tmp_path):
    """soffice present + enabled but convert yields no PDF -> honest, white-labeled note."""
    from applicant.core.ids import ResumeVariantId, new_id

    # soffice IS present, and we feed a real .docx path so the convert is attempted...
    src = tmp_path / "base.docx"
    src.write_bytes(b"PK\x03\x04stub-docx")  # existence + .docx suffix is enough here
    monkeypatch.setattr(
        docx_mod.shutil,
        "which",
        lambda name: "/usr/bin/soffice" if name in ("soffice", "libreoffice") else None,
    )
    # ...but the convert never produces a PDF.
    monkeypatch.setattr(docx_mod.subprocess, "run", lambda *a, **k: None)

    tailor = DocxTailor(render_mode="auto", output_dir=tmp_path)
    result = tailor.render_artifact(ResumeVariantId(new_id()), str(src))
    assert result.fidelity_ok is False
    assert "approximate preview" in result.notes
    _assert_white_labeled(result.notes)


def test_docx_convert_accepts_str_output_dir(monkeypatch, tmp_path):
    """Regression: output_dir injected as a str must not raise AttributeError on
    .mkdir() — DocxTailor wraps it with Path(...) defensively."""
    from applicant.core.ids import ResumeVariantId, new_id

    src = tmp_path / "base.docx"
    src.write_bytes(b"PK\x03\x04stub-docx")
    monkeypatch.setattr(
        docx_mod.shutil,
        "which",
        lambda name: "/usr/bin/soffice" if name in ("soffice", "libreoffice") else None,
    )
    monkeypatch.setattr(docx_mod.subprocess, "run", lambda *a, **k: None)

    out = tmp_path / "out"
    # output_dir is a STRING, not a Path — would previously raise AttributeError.
    tailor = DocxTailor(render_mode="auto", output_dir=str(out))
    result = tailor.render_artifact(ResumeVariantId(new_id()), str(src))
    # The convert ran (no crash) and the str output dir was created.
    assert out.is_dir()
    assert result.fidelity_ok is False  # no PDF produced -> honest degrade, not a crash
