"""AZ1-1 (#829) — Unit tests for the local-only awareness gate.

Tests the is_local_only() and filter_cloud_presets() pure functions
from _55_local_only_gate.py, plus source-level assertions for the
model_endpoints panel.
"""
from __future__ import annotations

import importlib.util
import os
import sys
import types
from pathlib import Path

import pytest

EXT_PATH = (
    Path(__file__).resolve().parents[2]
    / "a0-applicant/extensions/python/monologue_start/_55_local_only_gate.py"
)
PANEL_PATH = (
    Path(__file__).resolve().parents[2]
    / "a0-applicant/webui/model_endpoints.html"
)


@pytest.fixture()
def gate():
    """Load _55_local_only_gate.py with helpers.extension stubbed."""
    helpers = sys.modules.setdefault("helpers", types.ModuleType("helpers"))
    ext_mod = types.ModuleType("helpers.extension")

    class _Extension:
        def __init__(self, *a, **k):
            pass

    ext_mod.Extension = _Extension
    helpers.extension = ext_mod
    sys.modules["helpers.extension"] = ext_mod

    spec = importlib.util.spec_from_file_location("_az_local_only_gate", EXT_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestIsLocalOnly:
    def test_defaults_to_false_when_unset(self, gate, monkeypatch):
        monkeypatch.delenv("LLM_LOCAL_ONLY", raising=False)
        assert gate.is_local_only() is False

    def test_false_when_empty_string(self, gate, monkeypatch):
        monkeypatch.setenv("LLM_LOCAL_ONLY", "")
        assert gate.is_local_only() is False

    def test_true_for_lowercase_true(self, gate, monkeypatch):
        monkeypatch.setenv("LLM_LOCAL_ONLY", "true")
        assert gate.is_local_only() is True

    def test_true_for_uppercase_true(self, gate, monkeypatch):
        monkeypatch.setenv("LLM_LOCAL_ONLY", "TRUE")
        assert gate.is_local_only() is True

    def test_true_for_1(self, gate, monkeypatch):
        monkeypatch.setenv("LLM_LOCAL_ONLY", "1")
        assert gate.is_local_only() is True

    def test_true_for_yes(self, gate, monkeypatch):
        monkeypatch.setenv("LLM_LOCAL_ONLY", "yes")
        assert gate.is_local_only() is True


class TestFilterCloudPresets:
    def test_passthrough_when_not_local_only(self, gate):
        presets = [{"name": "A", "tier": "cloud-flash"}, {"name": "B", "tier": "local-fast"}]
        result = gate.filter_cloud_presets(presets, local_only=False)
        assert result == presets

    def test_drops_cloud_presets_when_local_only(self, gate):
        presets = [{"name": "A", "tier": "local-fast"}, {"name": "B", "tier": "cloud-flash"}, {"name": "C", "tier": "cloud-pro"}]
        result = gate.filter_cloud_presets(presets, local_only=True)
        names = [p["name"] for p in result]
        assert names == ["A"]
        assert len(result) == 1

    def test_keeps_all_when_no_cloud_presets(self, gate):
        presets = [{"name": "A", "tier": "local-fast"}]
        result = gate.filter_cloud_presets(presets, local_only=True)
        assert result == presets

    def test_empty_input_returns_empty(self, gate):
        assert gate.filter_cloud_presets([], local_only=True) == []
        assert gate.filter_cloud_presets([], local_only=False) == []


class TestModelEndpointsPanelSource:
    """Source-level assertions for model_endpoints.html."""

    @pytest.fixture(scope="class")
    def html(self) -> str:
        return PANEL_PATH.read_text(encoding="utf-8")

    def test_has_local_only_status_call(self, html):
        assert "local_only_status" in html

    def test_has_local_only_mode_text(self, html):
        assert "local-only mode" in html
