"""AZ3 (FR-LOG-3) — the admin-logs proxy dispatch/forward routing.

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

HANDLER = Path(__file__).resolve().parents[2] / "a0-applicant/api/adminlogs.py"


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

    spec = importlib.util.spec_from_file_location("_az3_adminlogs", HANDLER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestAdminLogsProxy:
    """Hermetic dispatch tests for the admin-logs proxy."""

    def test_tail_forwards_get_with_default_limit(self, mod):
        seen = {}

        def fake(method, path, body=None, timeout=10):
            seen.update(method=method, path=path, body=body)
            return {"ok": True, "status": 200, "data": {}}

        with patch.object(mod, "_forward", fake):
            r = mod.dispatch({"action": "tail"})
        assert r["ok"] is True
        assert seen["method"] == "GET"
        assert seen["path"] == "/api/admin/logs?limit=200"

    def test_tail_with_limit_only(self, mod):
        seen = {}

        def fake(method, path, body=None, timeout=10):
            seen.update(method=method, path=path)
            return {"ok": True, "status": 200, "data": {}}

        with patch.object(mod, "_forward", fake):
            r = mod.dispatch({"action": "tail", "limit": 50})
        assert r["ok"] is True
        assert seen["path"] == "/api/admin/logs?limit=50"

    def test_tail_with_limit_and_since_seq(self, mod):
        seen = {}

        def fake(method, path, body=None, timeout=10):
            seen.update(method=method, path=path)
            return {"ok": True, "status": 200, "data": {}}

        with patch.object(mod, "_forward", fake):
            r = mod.dispatch({"action": "tail", "limit": 200, "since_seq": 41})
        assert r["ok"] is True
        assert seen["path"] == "/api/admin/logs?limit=200&since_seq=41"

    def test_tail_since_seq_none_omits_query_param(self, mod):
        seen = {}

        def fake(method, path, body=None, timeout=10):
            seen.update(method=method, path=path)
            return {"ok": True, "status": 200, "data": {}}

        with patch.object(mod, "_forward", fake):
            r = mod.dispatch({"action": "tail", "since_seq": None})
        assert seen["path"] == "/api/admin/logs?limit=200"
        assert "since_seq" not in seen["path"]

    def test_unknown_action_returns_400(self, mod):
        r = mod.dispatch({"action": "bogus"})
        assert r["ok"] is False
        assert r["status"] == 400
        assert "unknown" in r["error"]
