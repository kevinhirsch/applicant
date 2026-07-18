import pytest
from unittest.mock import patch

from applicant.observability.capabilities import (
    _tex_status,
    _libreoffice_writer_present,
    _libreoffice_status,
    _fc_cache_status,
    _browser_status,
    _postgres_status,
    capability_status,
)


class TestTexStatus:
    """Detects lualatex or xelatex via shutil.which."""

    def test_lualatex_found(self):
        with patch("applicant.observability.capabilities.shutil.which") as mock_which:
            mock_which.side_effect = lambda name: f"/usr/bin/{name}" if name == "lualatex" else None
            result = _tex_status()
        assert result == "ok (/usr/bin/lualatex)"

    def test_xelatex_found(self):
        with patch("applicant.observability.capabilities.shutil.which") as mock_which:
            mock_which.side_effect = lambda name: f"/usr/bin/{name}" if name == "xelatex" else None
            result = _tex_status()
        assert result == "ok (/usr/bin/xelatex)"

    def test_not_found(self):
        with patch("applicant.observability.capabilities.shutil.which", return_value=None):
            result = _tex_status()
        assert result == "NOT FOUND (using stub PDF)"


class TestLibreofficeWriterPresent:
    """Checks whether the Writer component is installed alongside soffice."""

    def test_swriter_on_path(self):
        with patch("applicant.observability.capabilities.shutil.which") as mock_which:
            mock_which.side_effect = lambda name: f"/usr/bin/{name}" if name == "swriter" else None
            assert _libreoffice_writer_present("/usr/bin/soffice") is True

    def test_swriter_bin_in_program_dir(self):
        with patch("applicant.observability.capabilities.shutil.which", return_value=None):
            with patch("applicant.observability.capabilities.Path") as mock_path_cls:
                mock_path_instance = mock_path_cls.return_value
                mock_path_instance.resolve.return_value.parent = mock_path_instance
                (mock_path_instance / "swriter.bin").exists.return_value = True
                assert _libreoffice_writer_present("/usr/bin/soffice") is True

    def test_swriter_file_in_program_dir(self):
        with patch("applicant.observability.capabilities.shutil.which", return_value=None):
            with patch("applicant.observability.capabilities.Path") as mock_path_cls:
                mock_path_instance = mock_path_cls.return_value
                mock_path_instance.resolve.return_value.parent = mock_path_instance
                (mock_path_instance / "swriter.bin").exists.return_value = False
                (mock_path_instance / "swriter").exists.return_value = True
                assert _libreoffice_writer_present("/usr/bin/soffice") is True

    def test_not_found(self):
        with patch("applicant.observability.capabilities.shutil.which", return_value=None):
            with patch("applicant.observability.capabilities.Path") as mock_path_cls:
                mock_path_instance = mock_path_cls.return_value
                mock_path_instance.resolve.return_value.parent = mock_path_instance
                (mock_path_instance / "swriter.bin").exists.return_value = False
                (mock_path_instance / "swriter").exists.return_value = False
                assert _libreoffice_writer_present("/usr/bin/soffice") is False

    def test_resolve_raises_oserror(self):
        with patch("applicant.observability.capabilities.shutil.which", return_value=None):
            with patch("applicant.observability.capabilities.Path") as mock_path_cls:
                mock_path_instance = mock_path_cls.return_value
                mock_path_instance.resolve.side_effect = OSError
                assert _libreoffice_writer_present("/usr/bin/soffice") is False


class TestLibreofficeStatus:
    """Detects soffice/libreoffice and checks Writer component."""

    def test_not_found(self):
        with patch("applicant.observability.capabilities.shutil.which", return_value=None):
            result = _libreoffice_status()
        assert result == "NOT FOUND (using stub DOCX)"

    def test_ok(self):
        with patch("applicant.observability.capabilities.shutil.which") as mock_which:
            mock_which.side_effect = lambda name: (
                "/usr/bin/soffice" if name == "soffice" else (
                    "/usr/bin/swriter" if name == "swriter" else None
                )
            )
            result = _libreoffice_status()
        assert result == "ok (/usr/bin/soffice)"

    def test_degraded(self):
        with patch("applicant.observability.capabilities.shutil.which") as mock_which:
            mock_which.side_effect = lambda name: (
                "/usr/bin/soffice" if name == "soffice" else None
            )
            with patch("applicant.observability.capabilities.Path") as mock_path_cls:
                mock_path_instance = mock_path_cls.return_value
                mock_path_instance.resolve.return_value.parent = mock_path_instance
                (mock_path_instance / "swriter.bin").exists.return_value = False
                (mock_path_instance / "swriter").exists.return_value = False
                result = _libreoffice_status()
        assert result == (
            "DEGRADED (/usr/bin/soffice found, but the Writer component is missing"
            " — docx render broken)"
        )


class TestFcCacheStatus:
    """Detects fc-cache via shutil.which."""

    def test_found(self):
        with patch("applicant.observability.capabilities.shutil.which", return_value="/usr/bin/fc-cache"):
            result = _fc_cache_status()
        assert result == "ok (/usr/bin/fc-cache)"

    def test_not_found(self):
        with patch("applicant.observability.capabilities.shutil.which", return_value=None):
            result = _fc_cache_status()
        assert result == "NOT FOUND (font-cache refresh skipped)"


class TestBrowserStatus:
    """Reports browser capability based on BROWSER_REAL flag and binary presence."""

    def test_disabled(self):
        result = _browser_status(False)
        assert result == "disabled (BROWSER_REAL not set — using in-memory fake)"

    def test_camoufox_found(self):
        with patch("applicant.observability.capabilities.shutil.which") as mock_which:
            def side_effect(name):
                if name in ("camoufox", "camoufox-browser"):
                    return "/usr/local/bin/camoufox"
                return None
            mock_which.side_effect = side_effect
            result = _browser_status(True)
        assert result == "ok (camoufox: /usr/local/bin/camoufox)"

    def test_chrome_found(self):
        with patch("applicant.observability.capabilities.shutil.which") as mock_which:
            def side_effect(name):
                if name in ("google-chrome", "chromium", "chrome"):
                    return "/usr/bin/google-chrome"
                return None
            mock_which.side_effect = side_effect
            result = _browser_status(True)
        assert result == "ok (chrome/chromium: /usr/bin/google-chrome)"

    def test_not_found(self):
        with patch("applicant.observability.capabilities.shutil.which", return_value=None):
            result = _browser_status(True)
        assert result == "NOT FOUND (BROWSER_REAL=true but no camoufox/chrome binary on PATH)"


class TestPostgresStatus:
    """Reports Postgres reachability based on engine object."""

    def test_connected(self):
        result = _postgres_status(object())
        assert result == "ok (connected)"

    def test_not_reachable(self):
        result = _postgres_status(None)
        assert result == "NOT REACHABLE (using in-memory storage)"


class TestCapabilityStatus:
    """capability_status returns the expected dict shape with all 5 keys."""

    def test_all_not_found(self):
        with patch("applicant.observability.capabilities.shutil.which", return_value=None):
            result = capability_status()
        assert isinstance(result, dict)
        assert set(result.keys()) == {"tex", "libreoffice", "fc_cache", "browser", "postgres"}
        assert result["tex"] == "NOT FOUND (using stub PDF)"
        assert result["libreoffice"] == "NOT FOUND (using stub DOCX)"
        assert result["fc_cache"] == "NOT FOUND (font-cache refresh skipped)"
        assert result["browser"] == "disabled (BROWSER_REAL not set — using in-memory fake)"
        assert result["postgres"] == "NOT REACHABLE (using in-memory storage)"

    def test_all_ok(self):
        with patch("applicant.observability.capabilities.shutil.which") as mock_which:
            def side_effect(name):
                lookup = {
                    "lualatex": "/usr/bin/lualatex",
                    "soffice": "/usr/bin/soffice",
                    "swriter": "/usr/bin/swriter",
                    "fc-cache": "/usr/bin/fc-cache",
                    "camoufox": "/usr/local/bin/camoufox",
                    "google-chrome": None,
                    "chromium": None,
                    "chrome": None,
                }
                return lookup.get(name)
            mock_which.side_effect = side_effect
            result = capability_status(browser_real=True, postgres_engine=object())
        assert isinstance(result, dict)
        assert set(result.keys()) == {"tex", "libreoffice", "fc_cache", "browser", "postgres"}
        assert "ok" in result["tex"]
        assert "ok" in result["libreoffice"]
        assert "ok" in result["fc_cache"]
        assert "disabled" not in result["browser"]
        assert "ok" in result["browser"]
        assert result["postgres"] == "ok (connected)"
