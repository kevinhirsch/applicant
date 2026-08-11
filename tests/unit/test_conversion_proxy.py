"""AZ2 (#842) — the conversion proxy dispatch/forward routing.

The proxy is an a0-applicant api handler that runs in the A0 shell, so we load just its
module with the framework imports stubbed and exercise the pure ``dispatch`` routing.
"""
from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path
from unittest.mock import patch

import pytest

HANDLER = Path(__file__).resolve().parents[2] / "a0-applicant/api/conversion.py"


@pytest.fixture()
def mod():
    api = types.ModuleType("helpers.api")

    class _AH:
        def __init__(self, *a, **k):
            pass

    api.ApiHandler = _AH
    helpers = sys.modules.setdefault("helpers", types.ModuleType("helpers"))
    helpers.api = api
    sys.modules["helpers.api"] = api
    flask = sys.modules.setdefault("flask", types.ModuleType("flask"))
    flask.Request = object

    spec = importlib.util.spec_from_file_location("_az2_conversion", HANDLER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestConversionProxy:
    """Hermetic dispatch tests for the conversion proxy."""

    def test_engine_forwards_get(self, mod):
        seen = {}

        def fake(method, path, body=None, timeout=10):
            seen.update(method=method, path=path)
            return {"ok": True, "status": 200, "data": {"campaign_id": "c1", "engine": "latex"}}

        with patch.object(mod, "_forward", fake):
            r = mod.dispatch({"action": "engine", "campaign_id": "c1"})
        assert seen == {"method": "GET", "path": "/api/conversion/c1/engine"}
        assert r["ok"] is True

    def test_preview_forwards_post(self, mod):
        seen = {}

        def fake(method, path, body=None, timeout=10):
            seen.update(method=method, path=path, body=body)
            return {"ok": True, "status": 200, "data": {"campaign_id": "c1", "artifact_available": False}}

        with patch.object(mod, "_forward", fake):
            r = mod.dispatch({"action": "preview", "campaign_id": "c1"})
        assert seen["method"] == "POST"
        assert seen["path"] == "/api/conversion/c1/preview"
        assert seen["body"] == {"campaign_id": "c1"}

    def test_preview_passes_source(self, mod):
        seen = {}

        def fake(method, path, body=None, timeout=10):
            seen.update(method=method, path=path, body=body)
            return {"ok": True, "status": 200, "data": {"campaign_id": "c1", "artifact_available": True}}

        with patch.object(mod, "_forward", fake):
            r = mod.dispatch({"action": "preview", "campaign_id": "c1", "source": "\\documentclass{article}"})
        assert seen["body"] == {"campaign_id": "c1", "source": "\\documentclass{article}"}

    def test_accept_forwards_post(self, mod):
        seen = {}

        def fake(method, path, body=None, timeout=10):
            seen.update(method=method, path=path)
            return {"ok": True, "status": 200, "data": {"campaign_id": "c1", "engine": "latex"}}

        with patch.object(mod, "_forward", fake):
            r = mod.dispatch({"action": "accept", "campaign_id": "c1"})
        assert seen == {"method": "POST", "path": "/api/conversion/c1/accept"}
        assert r["ok"] is True

    def test_reject_forwards_post(self, mod):
        seen = {}

        def fake(method, path, body=None, timeout=10):
            seen.update(method=method, path=path)
            return {"ok": True, "status": 200, "data": {"campaign_id": "c1", "engine": "docx"}}

        with patch.object(mod, "_forward", fake):
            r = mod.dispatch({"action": "reject", "campaign_id": "c1"})
        assert seen == {"method": "POST", "path": "/api/conversion/c1/reject"}
        assert r["ok"] is True

    def test_missing_campaign_id_rejected(self, mod):
        r = mod.dispatch({"action": "engine"})
        assert r["ok"] is False and r["status"] == 400
        assert "campaign_id is required" in r["error"]

    def test_unknown_action_is_rejected(self, mod):
        r = mod.dispatch({"action": "nuke", "campaign_id": "c1"})
        assert r["ok"] is False and r["status"] == 400
        assert "unknown conversion action" in r["error"]
