"""LaTeX compile env preservation + conservative font-embedding (FR-RESUME-4).

Hermetic: no TeX engine needed. ``_compile_env`` is pure given an engine path;
``_font_is_embedded`` runs on lightweight fake pypdf font dicts.
"""

from __future__ import annotations

import os

from applicant.adapters.resume_tailoring.latex_tailor import (
    LatexTailor,
    _font_is_embedded,
)


def test_compile_env_preserves_os_environ_and_texinputs(monkeypatch):
    monkeypatch.setenv("HOME", "/home/user")
    monkeypatch.setenv("TEXMFVAR", "/home/user/.texmf-var")
    monkeypatch.setenv("TEXINPUTS", "/pre-existing:")
    monkeypatch.setenv("PATH", "/usr/local/bin:/usr/bin")

    tailor = LatexTailor()
    env = tailor._compile_env("/opt/tex/bin/lualatex")

    # os.environ is preserved (HOME / TEXMFVAR survive).
    assert env["HOME"] == "/home/user"
    assert env["TEXMFVAR"] == "/home/user/.texmf-var"
    # Vendored dirs prepended; pre-existing TEXINPUTS kept; trailing ':' retained.
    assert env["TEXINPUTS"].startswith(str(tailor._template_root / "OpenFonts"))
    assert "OpenFonts" in env["TEXINPUTS"] and "cover" in env["TEXINPUTS"]
    assert env["TEXINPUTS"].endswith("/pre-existing:")
    # PATH keeps the engine dir AND the inherited PATH.
    assert env["PATH"].startswith("/opt/tex/bin")
    assert "/usr/bin" in env["PATH"]
    # The real process env is not mutated.
    assert os.environ["TEXINPUTS"] == "/pre-existing:"


def test_compile_env_without_preexisting_texinputs(monkeypatch):
    monkeypatch.delenv("TEXINPUTS", raising=False)
    tailor = LatexTailor()
    env = tailor._compile_env("/opt/tex/bin/xelatex")
    # Trailing ':' (from the vendored prefix) preserves the default search tree.
    assert env["TEXINPUTS"].endswith(":")


class _FakeRef:
    def __init__(self, obj):
        self._obj = obj

    def get_object(self):
        return self._obj


def test_font_not_embedded_when_descriptor_lacks_fontfile():
    # A subsetted/external font: descriptor present but no FontFile stream.
    descriptor = {"/Flags": 4}
    font = {"/FontDescriptor": _FakeRef(descriptor)}
    assert _font_is_embedded(font) is False


def test_font_not_embedded_when_no_descriptor():
    # Standard-14 base font referenced by name only -> NOT embedded.
    font = {"/BaseFont": "/Helvetica"}
    assert _font_is_embedded(font) is False


def test_font_embedded_with_fontfile_stream():
    descriptor = {"/FontFile2": object()}
    font = {"/FontDescriptor": _FakeRef(descriptor)}
    assert _font_is_embedded(font) is True


def test_composite_font_requires_all_descendants_embedded():
    good = {"/FontDescriptor": _FakeRef({"/FontFile3": object()})}
    bad = {"/FontDescriptor": _FakeRef({})}
    composite = {"/DescendantFonts": [_FakeRef(good), _FakeRef(bad)]}
    assert _font_is_embedded(composite) is False
