"""Font upload/management flow tests (FR-FONT-1/2).

Covers required-font detection, missing-font reporting, install + runtime
cache-refresh (stubbed fc-cache boundary; confined real FS copy), and
confirm-once-installed. No fontconfig / system-wide writes.
"""

from __future__ import annotations

import pytest

from applicant.adapters.fonts.font_installer import FontInstaller
from applicant.application.services.font_service import FontService


@pytest.fixture
def installer(tmp_path) -> FontInstaller:
    return FontInstaller(install_root=str(tmp_path / "fonts"))


@pytest.fixture
def service(installer) -> FontService:
    return FontService(installer)


def test_detect_required_fonts(installer, tmp_path):
    doc = tmp_path / "resume.tex"
    doc.write_text(
        "\\setmainfont{Lato-Lig}\n\\fontspec{Inconsolata}\n", encoding="utf-8"
    )
    found = installer.detect_required_fonts(str(doc))
    assert "Lato" in found
    assert "Inconsolata" in found


def test_missing_font_reporting_excludes_bundled_and_system(service, tmp_path):
    doc = tmp_path / "resume.tex"
    doc.write_text(
        "\\setmainfont{Lato}\n\\setsansfont{Calibri}\n\\fontspec{Inconsolata}\n",
        encoding="utf-8",
    )
    report = service.report_for_document(str(doc))
    assert "Inconsolata" in report.missing
    assert "Lato" not in report.missing  # bundled
    assert "Calibri" not in report.missing  # system font


def test_install_copies_into_confined_dir_and_refreshes_cache(installer, tmp_path):
    font = tmp_path / "Inconsolata.ttf"
    font.write_bytes(b"\x00\x01font-bytes")
    assert installer.cache_refresh_count == 0
    status = installer.install_font(str(font), "Inconsolata")
    assert status.installed is True
    # Real, confined copy happened (no system-wide write).
    installed_dir = tmp_path / "fonts"
    assert any(p.name.startswith("Inconsolata") for p in installed_dir.iterdir())
    # The (stubbed) fc-cache refresh ran exactly once.
    assert installer.cache_refresh_count == 1


def test_install_cannot_escape_confined_dir(installer, tmp_path):
    font = tmp_path / "evil.ttf"
    font.write_bytes(b"\x00")
    # A path-traversal name is sanitized; the file stays inside the confined dir.
    installer.install_font(str(font), "../../../etc/evil")
    installed_dir = tmp_path / "fonts"
    files = list(installed_dir.iterdir())
    assert files and all(p.parent == installed_dir for p in files)


def test_confirm_once_installed(service, tmp_path):
    font = tmp_path / "Inconsolata.ttf"
    font.write_bytes(b"\x00\x01")
    report = service.install(str(font), "Inconsolata")
    assert "Inconsolata" in report.installed
    # No longer reported missing on a fresh report.
    again = service.report_for_fonts(["Inconsolata"])
    assert again.missing == []


def test_installs_persist_across_restart(tmp_path):
    root = str(tmp_path / "fonts")
    inst1 = FontInstaller(install_root=root)
    font = tmp_path / "Inconsolata.ttf"
    font.write_bytes(b"\x00\x01")
    inst1.install_font(str(font), "Inconsolata")
    # New installer over same confined dir = restart; rescans installed fonts.
    inst2 = FontInstaller(install_root=root)
    assert inst2.missing_fonts(["Inconsolata"]) == []
