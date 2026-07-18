"""Tests for static file mounting (static_dir / mount_static)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from applicant.app.static import mount_static, static_dir


# ---- helpers ---------------------------------------------------------------


def _repo_root() -> Path:
    """The real repo root = 2 parents up from tests/unit/test_static.py."""
    return Path(__file__).resolve().parents[2]


@pytest.fixture(autouse=True)
def _reset_state():
    """No module-level mutable state to clear, but needed for parallel safety."""
    yield


# ---- static_dir ------------------------------------------------------------

class TestStaticDir:
    """static_dir() resolves relative paths and passes through absolute paths."""

    def test_relative_resolves_via_repo_root(self):
        """A relative path is joined to the repo root (3 parents up from static.py)."""
        result = static_dir("frontend/static")
        assert result == _repo_root() / "frontend" / "static"
        assert result.is_absolute()

    def test_relative_deep_path(self):
        """A relative path with parent traversal still resolves correctly."""
        result = static_dir("../static")
        assert result == _repo_root() / ".." / "static"

    def test_absolute_passes_through(self):
        """An absolute path is returned unchanged."""
        result = static_dir("/etc/static")
        assert result == Path("/etc/static")

    def test_dot_relative(self):
        """'.' resolves to the repo root."""
        result = static_dir(".")
        assert result == _repo_root() / "."

    def test_empty_string_resolves_to_repo_root(self):
        """An empty string resolves to the repo root (Path('') / '')."""
        result = static_dir("")
        assert result == _repo_root() / ""


# ---- mount_static ----------------------------------------------------------


class TestMountStatic:
    """mount_static() mounts or skips depending on directory existence."""

    def test_mounts_at_static_when_dir_exists(self, tmp_path: Path):
        """When the resolved directory exists, it is mounted at /static."""
        static_path = tmp_path / "frontend" / "static"
        static_path.mkdir(parents=True)

        app = MagicMock(spec=FastAPI)

        with patch("applicant.app.static.StaticFiles") as mock_sf:
            mock_sf.return_value = MagicMock()
            mount_static(app, str(static_path))

        mock_sf.assert_called_once_with(directory=str(static_path))
        app.mount.assert_called_once_with(
            "/static", mock_sf.return_value, name="static"
        )

    def test_skips_when_dir_does_not_exist(self, tmp_path: Path):
        """When the resolved directory does not exist, mount is not called."""
        non_existent = tmp_path / "does" / "not" / "exist"
        assert not non_existent.exists()

        app = MagicMock(spec=FastAPI)
        mount_static(app, str(non_existent))

        app.mount.assert_not_called()

    def test_uses_correct_static_files_args(self, tmp_path: Path):
        """StaticFiles is constructed with directory=str(static_dir)."""
        static_path = tmp_path / "assets"
        static_path.mkdir(parents=True)

        app = MagicMock(spec=FastAPI)

        with patch("applicant.app.static.StaticFiles") as mock_sf:
            mock_sf.return_value = MagicMock()
            mount_static(app, str(static_path))

        mock_sf.assert_called_once_with(directory=str(static_path))
        app.mount.assert_called_once_with(
            "/static", mock_sf.return_value, name="static"
        )

    def test_relative_path_dir_exists(self, tmp_path: Path, monkeypatch):
        """A relative path that resolves to an existing dir is mounted."""
        static_path = tmp_path / "static"
        static_path.mkdir(parents=True)

        monkeypatch.setattr(
            "applicant.app.static.static_dir",
            lambda _: static_path,
        )

        app = MagicMock(spec=FastAPI)

        with patch("applicant.app.static.StaticFiles") as mock_sf:
            mock_sf.return_value = MagicMock()
            mount_static(app, "frontend/static")

        mock_sf.assert_called_once_with(directory=str(static_path))
        app.mount.assert_called_once_with(
            "/static", mock_sf.return_value, name="static"
        )

    def test_skips_when_empty_string_dir_does_not_exist(self, monkeypatch):
        """An empty string resolves to a non-existent dir, so mount is not called."""
        from pathlib import Path
        monkeypatch.setattr(
            "applicant.app.static.static_dir",
            lambda _: Path("/nonexistent"),
        )
        app = MagicMock(spec=FastAPI)
        mount_static(app, "")
        app.mount.assert_not_called()

    def test_skips_when_absolute_path_does_not_exist(self):
        """An absolute path to a non-existent dir does not mount."""
        app = MagicMock(spec=FastAPI)
        mount_static(app, "/nonexistent/path")
        app.mount.assert_not_called()

    def test_path_with_symlink_dir_exists(self, tmp_path: Path):
        """A symlinked directory is detected as a dir and mounted."""
        real_dir = tmp_path / "real_static"
        real_dir.mkdir(parents=True)
        link_dir = tmp_path / "link_static"
        link_dir.symlink_to(real_dir, target_is_directory=True)

        assert link_dir.is_dir()

        app = MagicMock(spec=FastAPI)

        with patch("applicant.app.static.StaticFiles") as mock_sf:
            mock_sf.return_value = MagicMock()
            mount_static(app, str(link_dir))

        mock_sf.assert_called_once_with(directory=str(link_dir))
        app.mount.assert_called_once_with(
            "/static", mock_sf.return_value, name="static"
        )