"""AZ3 (#842) — the ops proxy dispatch/forward routing.

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

HANDLER = Path(__file__).resolve().parents[2] / "a0-applicant/api/ops.py"


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

    spec = importlib.util.spec_from_file_location("_az3_ops", HANDLER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestOpsProxy:
    """Hermetic dispatch tests for the ops proxy."""

    def test_tools_forwards_get(self, mod):
        seen = {}

        def fake(method, path, body=None, timeout=10):
            seen.update(method=method, path=path)
            return {"ok": True, "status": 200, "data": {}}

        with patch.object(mod, "_forward", fake):
            r = mod.dispatch({"action": "tools"})
        assert seen["method"] == "GET"
        assert seen["path"] == "/api/admin/tools"

    def test_set_tool_forwards_post_with_body(self, mod):
        seen = {}

        def fake(method, path, body=None, timeout=10):
            seen.update(method=method, path=path, body=body)
            return {"ok": True, "status": 200, "data": {}}

        with patch.object(mod, "_forward", fake):
            r = mod.dispatch({"action": "set_tool", "tool_key": "search", "enabled": True})
        assert seen["method"] == "POST"
        assert seen["path"] == "/api/admin/tools/search?enabled=true"

    def test_set_tool_missing_tool_key_400(self, mod):
        r = mod.dispatch({"action": "set_tool"})
        assert r["ok"] is False
        assert r["status"] == 400
        assert "tool_key required" in r["error"]

    def test_history_forwards_get(self, mod):
        seen = {}

        def fake(method, path, body=None, timeout=10):
            seen.update(method=method, path=path)
            return {"ok": True, "status": 200, "data": {}}

        with patch.object(mod, "_forward", fake):
            r = mod.dispatch({"action": "history", "campaign_id": "camp1"})
        assert seen["method"] == "GET"
        assert seen["path"] == "/api/admin/history/camp1"

    def test_detections_forwards_get(self, mod):
        seen = {}

        def fake(method, path, body=None, timeout=10):
            seen.update(method=method, path=path)
            return {"ok": True, "status": 200, "data": {}}

        with patch.object(mod, "_forward", fake):
            r = mod.dispatch({"action": "detections", "campaign_id": "camp1"})
        assert seen["method"] == "GET"
        assert seen["path"] == "/api/admin/detections/camp1"

    def test_logs_forwards_get(self, mod):
        seen = {}

        def fake(method, path, body=None, timeout=10):
            seen.update(method=method, path=path)
            return {"ok": True, "status": 200, "data": {}}

        with patch.object(mod, "_forward", fake):
            r = mod.dispatch({"action": "logs"})
        assert seen["method"] == "GET"
        assert seen["path"] == "/api/admin/logs"

    def test_default_action_is_tools(self, mod):
        seen = {}

        def fake(method, path, body=None, timeout=10):
            seen.update(method=method, path=path)
            return {"ok": True, "status": 200, "data": {}}

        with patch.object(mod, "_forward", fake):
            r = mod.dispatch({"action": ""})
        assert seen["method"] == "GET"
        assert seen["path"] == "/api/admin/tools"

    def test_unknown_action_rejected(self, mod):
        r = mod.dispatch({"action": "nuke"})
        assert r["ok"] is False
        assert r["status"] == 400
        assert "unknown ops action" in r["error"]
