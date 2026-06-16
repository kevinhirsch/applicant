"""FontInstall contract (FR-FONT-1/2).

Architecture §6: every adapter ships a contract test. Proves the FontInstaller:

* satisfies the ``FontInstallPort`` protocol;
* detects fonts a document references (FR-FONT-1) by parsing fontspec directives;
* installs an uploaded font and reports it installed + refreshes the cache at
  runtime (FR-FONT-2) WITHOUT touching the real font dirs or shelling out;
* surfaces which required fonts are still missing (drives the upload prompt).
"""

from __future__ import annotations

import pytest

from applicant.adapters.fonts.font_installer import FontInstaller
from applicant.ports.driven.font_install import FontInstallPort, FontStatus


@pytest.mark.contract
class TestFontInstallerContract:
    @pytest.fixture
    def adapter(self) -> FontInstaller:
        return FontInstaller()

    def test_satisfies_port_protocol(self, adapter):
        assert isinstance(adapter, FontInstallPort)

    def test_detect_required_fonts_from_fontspec(self, adapter, tmp_path):
        # FR-FONT-1: detect fonts referenced by an uploaded resume source.
        doc = tmp_path / "resume.tex"
        doc.write_text(
            "\\setmainfont[Path=fonts/]{Lato-Lig}\n"
            "\\setsansfont{Raleway-ExtraLight}\n"
            "\\fontspec{Inconsolata}\n",
            encoding="utf-8",
        )
        found = adapter.detect_required_fonts(str(doc))
        assert "Lato" in found
        assert "Raleway" in found
        assert "Inconsolata" in found

    def test_detect_missing_document_is_safe(self, adapter):
        # No file -> nothing detected (safe; never raises).
        assert adapter.detect_required_fonts("/no/such/file.tex") == []

    def test_missing_fonts_excludes_bundled(self, adapter):
        # Bundled Lato/Raleway are present; an uploaded font is reported missing.
        missing = adapter.missing_fonts(["Lato", "Raleway", "Inconsolata"])
        assert missing == ["Inconsolata"]

    def test_install_font_marks_installed_and_refreshes_cache(self, adapter, tmp_path):
        # FR-FONT-2: install + runtime cache refresh (stubbed; no fc-cache shell-out).
        font = tmp_path / "Inconsolata.ttf"
        font.write_bytes(b"\x00\x01font-bytes")
        status = adapter.install_font(str(font), "Inconsolata")
        assert isinstance(status, FontStatus)
        assert status.installed is True
        assert status.name == "Inconsolata"
        # Now it is no longer reported missing.
        assert adapter.missing_fonts(["Inconsolata"]) == []
        assert any(f.name == "Inconsolata" for f in adapter.list_fonts())
