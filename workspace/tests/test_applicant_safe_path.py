"""Unit tests for the shared safe-path helper (core/safe_path.py).

Hermetic: exercises the traversal/containment logic against a tmp base dir — no
network, no app boot. Guards the file-inclusion / path-traversal fix (G05).
"""

import importlib.util
import os

import pytest

# Load core/safe_path.py directly by file path. Importing it as ``core.safe_path``
# would execute ``core/__init__.py``, which eagerly wires the SQLAlchemy engine and
# needs a writable DB — irrelevant to this pure helper and absent in the gated run.
_SPEC = importlib.util.spec_from_file_location(
    "applicant_safe_path_under_test",
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "core", "safe_path.py"),
)
_safe_path = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_safe_path)

UnsafePathError = _safe_path.UnsafePathError
is_within_base = _safe_path.is_within_base
safe_filename = _safe_path.safe_filename
safe_join = _safe_path.safe_join


def test_safe_join_accepts_in_base_path(tmp_path):
    base = str(tmp_path)
    result = safe_join(base, "report.json")
    assert result == os.path.realpath(os.path.join(base, "report.json"))
    assert is_within_base(base, result)


def test_safe_join_accepts_nested_in_base_path(tmp_path):
    base = str(tmp_path)
    result = safe_join(base, "sub", "deep", "doc.txt")
    assert is_within_base(base, result)


def test_safe_join_rejects_parent_traversal(tmp_path):
    base = str(tmp_path / "data")
    os.makedirs(base, exist_ok=True)
    with pytest.raises(UnsafePathError):
        safe_join(base, "../../etc/passwd")


def test_safe_join_rejects_absolute_escape(tmp_path):
    base = str(tmp_path)
    with pytest.raises(UnsafePathError):
        safe_join(base, "/etc/passwd")


def test_safe_join_rejects_embedded_traversal(tmp_path):
    base = str(tmp_path)
    with pytest.raises(UnsafePathError):
        safe_join(base, "ok/../../../secret")


def test_safe_join_rejects_symlink_escape(tmp_path):
    base = tmp_path / "base"
    base.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("classified")
    link = base / "link"
    try:
        link.symlink_to(outside)
    except (OSError, NotImplementedError):  # pragma: no cover - platform without symlinks
        pytest.skip("symlinks not supported on this platform")
    # The realpath of base/link/secret.txt resolves into ``outside`` -> rejected.
    with pytest.raises(UnsafePathError):
        safe_join(str(base), "link", "secret.txt")


def test_safe_join_requires_a_component(tmp_path):
    with pytest.raises(UnsafePathError):
        safe_join(str(tmp_path))


def test_is_within_base_true_for_contained(tmp_path):
    assert is_within_base(str(tmp_path), str(tmp_path / "a" / "b"))


def test_is_within_base_false_for_escape(tmp_path):
    base = tmp_path / "base"
    base.mkdir()
    assert is_within_base(str(base), str(tmp_path / "elsewhere")) is False


def test_is_within_base_false_on_traversal_string(tmp_path):
    base = str(tmp_path / "base")
    assert is_within_base(base, os.path.join(base, "..", "..", "etc")) is False


def test_safe_filename_strips_directory_components():
    assert safe_filename("../../etc/passwd") == "passwd"
    assert safe_filename("/var/log/syslog") == "syslog"
    assert safe_filename("plain.txt") == "plain.txt"
    assert safe_filename("a\\b\\c.dat") == "c.dat"


def test_safe_filename_rejects_empty_and_dots():
    for bad in ("", "   ", ".", "..", "/", "../"):
        with pytest.raises(UnsafePathError):
            safe_filename(bad)
