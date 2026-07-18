"""Unit tests for font_installer adapter (FR-FONT-1/2)."""

import os
import zipfile
from pathlib import Path
import tempfile

import pytest

from applicant.adapters.fonts.font_installer import FontInstaller, _looks_like_font_name
from applicant.ports.driven.font_install import FontStatus


# No module-level mutable state to clear in font_installer,
# but an autouse fixture is required for xdist parallel safety.
@pytest.fixture(autouse=True)
def _font_installer_autouse():
    yield


@pytest.mark.unit
class TestLooksLikeFontName:
    """Tests for the _looks_like_font_name validation gate."""

    def test_valid_standard_names(self):
        assert _looks_like_font_name("Lato")
        assert _looks_like_font_name("Times New Roman")
        assert _looks_like_font_name("Segoe UI")
        assert _looks_like_font_name("Lato-Lig")
        assert _looks_like_font_name("A")

    def test_invalid_traversal(self):
        assert not _looks_like_font_name("../../evil")
        assert not _looks_like_font_name("sub/foo")
        assert not _looks_like_font_name("..")

    def test_invalid_empty(self):
        assert not _looks_like_font_name("")

    def test_invalid_too_long(self):
        assert not _looks_like_font_name("a" * 65)

    def test_invalid_control_chars(self):
        assert not _looks_like_font_name("abc\x00def")
        assert not _looks_like_font_name("abc\ndef")

    def test_invalid_whitespace_padded(self):
        assert not _looks_like_font_name(" Arial")
        assert not _looks_like_font_name("Arial ")

    def test_invalid_starting_with_dot_or_dash(self):
        assert not _looks_like_font_name(".HiddenFont")
        assert not _looks_like_font_name("-StartsWithDash")
        assert not _looks_like_font_name("_StartsWithUnderscore")

    def test_invalid_backslash(self):
        assert not _looks_like_font_name("evil\\path")


@pytest.mark.unit
class TestFontInstallerInit:
    """Tests for FontInstaller.__init__."""

    def test_sets_bundled_fonts(self):
        installer = FontInstaller(install_root="/tmp/nonexistent_test_dir_rescan_skip")
        assert "Lato" in installer._installed
        assert "Raleway" in installer._installed
        status = installer._installed["Lato"]
        assert status.installed is True
        assert status.environment == "bundled"

    def test_sets_install_root(self):
        installer = FontInstaller(install_root="/tmp/custom_install_root")
        assert installer._install_root == "/tmp/custom_install_root"


@pytest.mark.unit
class TestDetectRequiredFonts:
    """Tests for FontInstaller.detect_required_fonts."""

    def test_bogus_path_returns_empty_list(self):
        installer = FontInstaller()
        result = installer.detect_required_fonts("/tmp/nonexistent_path_123456")
        assert result == []

    def test_latex_source_detects_fonts(self):
        latex = r"""
        \setmainfont{Lato}
        \setsansfont{SourceSansPro}
        \fontspec{NotoSerif}
        \newfontfamily\headingfont{Ubuntu}
        """
        with tempfile.NamedTemporaryFile(mode="w", suffix=".tex", delete=False) as f:
            f.write(latex)
            fname = f.name
        try:
            installer = FontInstaller()
            result = installer.detect_required_fonts(fname)
            assert "Lato" in result
            assert "SourceSansPro" in result
            assert "NotoSerif" in result
            assert "Ubuntu" in result
        finally:
            os.unlink(fname)

    def test_docx_detects_fonts(self):
        font_table_xml = b"""<?xml version="1.0"?>
        <w:fonts xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
            <w:font w:name="CustomDocxFontA"/>
            <w:font w:name="CustomDocxFontB"/>
        </w:fonts>"""
        with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as f:
            fname = f.name
        try:
            with zipfile.ZipFile(fname, "w") as zf:
                zf.writestr("word/fontTable.xml", font_table_xml)
            installer = FontInstaller()
            result = installer.detect_required_fonts(fname)
            assert "CustomDocxFontA" in result
            assert "CustomDocxFontB" in result
        finally:
            os.unlink(fname)

    def test_docx_empty_font_table_falls_through_to_latex_scan(self):
        """When DOCX has no fonts in fontTable, falls through to LaTeX scan."""
        empty_xml = b"""<?xml version="1.0"?>
        <w:fonts xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"/>"""
        with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as f:
            fname = f.name
        try:
            with zipfile.ZipFile(fname, "w") as zf:
                zf.writestr("word/fontTable.xml", empty_xml)
            installer = FontInstaller()
            result = installer.detect_required_fonts(fname)
            assert result == []
        finally:
            os.unlink(fname)


@pytest.mark.unit
class TestMissingFonts:
    """Tests for FontInstaller.missing_fonts."""

    def test_bundled_fonts_not_missing(self):
        installer = FontInstaller()
        result = installer.missing_fonts(["Lato", "Raleway"])
        assert result == []

    def test_system_fonts_not_missing(self):
        installer = FontInstaller()
        result = installer.missing_fonts(["Arial", "Times New Roman"])
        assert result == []

    def test_unknown_fonts_are_missing(self):
        installer = FontInstaller()
        result = installer.missing_fonts(["UnknownFontX", "MissingFontY"])
        assert "UnknownFontX" in result
        assert "MissingFontY" in result

    def test_mixed_known_and_unknown(self):
        installer = FontInstaller()
        result = installer.missing_fonts(["Lato", "Arial", "CustomZ"])
        assert "Lato" not in result
        assert "Arial" not in result
        assert "CustomZ" in result
        assert len(result) == 1

    def test_traversal_names_are_filtered_out(self):
        installer = FontInstaller()
        result = installer.missing_fonts(["../../evil", "SafeFont"])
        assert "SafeFont" in result
        assert "../../evil" not in result


@pytest.mark.unit
class TestInstallFont:
    """Tests for FontInstaller.install_font."""

    def test_copies_font_to_install_root(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            src_file = os.path.join(tmpdir, "test_font.ttf")
            Path(src_file).write_text("fake font binary data")
            install_root = os.path.join(tmpdir, "fonts")
            installer = FontInstaller(install_root=install_root)

            status = installer.install_font(src_file, "TestFont")

            assert status.name == "TestFont"
            assert status.installed is True
            dest_file = os.path.join(install_root, "TestFont.ttf")
            assert os.path.isfile(dest_file)
            assert open(dest_file).read() == "fake font binary data"

    def test_updates_installed_dict(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            src_file = os.path.join(tmpdir, "font.ttf")
            Path(src_file).write_text("data")
            installer = FontInstaller(install_root=os.path.join(tmpdir, "fonts"))
            installer.install_font(src_file, "NewCustomFont")
            assert "NewCustomFont" in installer._installed
            assert installer._installed["NewCustomFont"].name == "NewCustomFont"
            assert installer._installed["NewCustomFont"].installed is True

    def test_rejects_invalid_name(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            src_file = os.path.join(tmpdir, "font.ttf")
            Path(src_file).write_text("data")
            installer = FontInstaller(install_root=os.path.join(tmpdir, "fonts"))
            with pytest.raises(ValueError, match="Invalid font name"):
                installer.install_font(src_file, "../../evil")

    def test_increments_cache_refresh_count(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            src_file = os.path.join(tmpdir, "font.ttf")
            Path(src_file).write_text("data")
            installer = FontInstaller(install_root=os.path.join(tmpdir, "fonts"))
            assert installer.cache_refresh_count == 0
            installer.install_font(src_file, "CacheTest")
            assert installer.cache_refresh_count == 1


@pytest.mark.unit
class TestIsInstalled:
    """Tests for FontInstaller._is_installed."""

    def test_bundled_font_returns_true(self):
        installer = FontInstaller()
        assert installer._is_installed("Lato")
        assert installer._is_installed("Raleway")

    def test_system_font_not_installed_returns_false(self):
        installer = FontInstaller()
        assert not installer._is_installed("Arial")

    def test_newly_installed_font_returns_true(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            src_file = os.path.join(tmpdir, "test.ttf")
            Path(src_file).write_text("data")
            installer = FontInstaller(install_root=os.path.join(tmpdir, "fonts"))
            assert not installer._is_installed("NewFont")
            installer.install_font(src_file, "NewFont")
            assert installer._is_installed("NewFont")

    def test_root_name_split_matches_with_hyphen_variant(self):
        """Lato-Bold should match installed 'Lato' via root split."""
        installer = FontInstaller()
        assert installer._is_installed("Lato-Bold")


@pytest.mark.unit
class TestListFonts:
    """Tests for FontInstaller.list_fonts."""

    def test_returns_bundled_fonts(self):
        installer = FontInstaller()
        fonts = installer.list_fonts()
        names = {f.name for f in fonts}
        assert "Lato" in names
        assert "Raleway" in names

    def test_filters_out_invalid_names_defense_in_depth(self):
        installer = FontInstaller()
        installer._installed["../../evil"] = FontStatus(
            name="../../evil", installed=True, environment="test"
        )
        fonts = installer.list_fonts()
        names = {f.name for f in fonts}
        assert "../../evil" not in names
        assert "Lato" in names
