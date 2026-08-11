"""WT (#w1) — the dormant proxy dispatch/forward routing.

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

HANDLER = Path(__file__).resolve().parents[2] / "a0-applicant/api/dormant.py"


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

    spec = importlib.util.spec_from_file_location("_az_wt_dormant", HANDLER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestDormantProxy:
    """Hermetic dispatch tests for the dormant proxy."""

    def test_list_forwards_get(self, mod):
        seen = {}

        def fake(method, path, body=None, timeout=10):
            seen.update(method=method, path=path)
            return {"ok": True, "status": 200, "data": [{"key": "redline_surface", "name": "Redline Surface", "status": "live", "live_phase": "active"}]}

        with patch.object(mod, "_forward", fake):
            r = mod.dispatch({"action": "list"})
        assert seen == {"method": "GET", "path": "/api/dormant-surfaces"}
        assert r["ok"] is True
        assert r["data"][0]["key"] == "redline_surface"

    def test_default_action_is_list(self, mod):
        seen = {}

        def fake(method, path, body=None, timeout=10):
            seen.update(method=method, path=path)
            return {"ok": True, "status": 200, "data": []}

        with patch.object(mod, "_forward", fake):
            r = mod.dispatch({})
        assert seen == {"method": "GET", "path": "/api/dormant-surfaces"}
        assert r["ok"] is True

    def test_list_empty_input(self, mod):
        seen = {}

        def fake(method, path, body=None, timeout=10):
            seen.update(method=method, path=path)
            return {"ok": True, "status": 200, "data": []}

        with patch.object(mod, "_forward", fake):
            r = mod.dispatch(None)
        assert seen == {"method": "GET", "path": "/api/dormant-surfaces"}
        assert r["ok"] is True

    def test_unknown_action_returns_400(self, mod):
        r = mod.dispatch({"action": "unknown_action"})
        assert r["ok"] is False
        assert r["status"] == 400
        assert "unknown" in r["error"]

    def test_forward_error_envelope(self, mod):
        seen = {}

        def fake(method, path, body=None, timeout=10):
            seen.update(method=method, path=path)
            return {"ok": False, "status": 503, "error": "Service Unavailable"}

        with patch.object(mod, "_forward", fake):
            r = mod.dispatch({"action": "list"})
        assert r["ok"] is False
        assert r["status"] == 503
        assert r["error"] == "Service Unavailable"
