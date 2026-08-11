"""AZ2 (#842) — the easy-apply proxy dispatch/forward routing.

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

HANDLER = Path(__file__).resolve().parents[2] / "a0-applicant/api/easy_apply.py"


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

    spec = importlib.util.spec_from_file_location("_test_easy_apply", HANDLER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestEasyApplyProxy:
    """Hermetic dispatch tests for the easy-apply proxy."""

    def test_status_forwards_get(self, mod):
        seen = {}

        def fake(method, path, body=None, timeout=10):
            seen.update(method=method, path=path)
            return {"ok": True, "status": 200, "data": {"campaign_id": "c1", "posting_id": "p1", "title": "Engineer"}}

        with patch.object(mod, "_forward", fake):
            r = mod.dispatch({"action": "status", "campaign_id": "c1", "posting_id": "p1"})
        assert seen == {"method": "GET", "path": "/api/easy-apply/c1/p1"}
        assert r["ok"] is True

    def test_status_default_campaign_id(self, mod):
        seen = {}

        def fake(method, path, body=None, timeout=10):
            seen.update(method=method, path=path)
            return {"ok": True, "status": 200, "data": {"campaign_id": "__system__", "posting_id": "__default__", "items": []}}

        with patch.object(mod, "_forward", fake):
            r = mod.dispatch({"action": "status", "posting_id": "p1"})
        assert seen == {"method": "GET", "path": "/api/easy-apply/__system__/p1"}

    def test_status_default_posting_id(self, mod):
        seen = {}

        def fake(method, path, body=None, timeout=10):
            seen.update(method=method, path=path)
            return {"ok": True, "status": 200, "data": {"campaign_id": "__system__", "posting_id": "__default__"}}

        with patch.object(mod, "_forward", fake):
            r = mod.dispatch({"action": "status", "campaign_id": "c1"})
        assert seen == {"method": "GET", "path": "/api/easy-apply/c1/__default__"}

    def test_default_action_is_status(self, mod):
        seen = {}

        def fake(method, path, body=None, timeout=10):
            seen.update(method=method, path=path)
            return {"ok": True, "status": 200, "data": {"campaign_id": "__system__", "posting_id": "__default__"}}

        with patch.object(mod, "_forward", fake):
            r = mod.dispatch({"action": ""})
        assert seen == {"method": "GET", "path": "/api/easy-apply/__system__/__default__"}

    def test_default_action_when_no_action(self, mod):
        seen = {}

        def fake(method, path, body=None, timeout=10):
            seen.update(method=method, path=path)
            return {"ok": True, "status": 200, "data": {"campaign_id": "__system__", "posting_id": "__default__"}}

        with patch.object(mod, "_forward", fake):
            r = mod.dispatch({})
        assert seen["method"] == "GET"
        assert seen["path"] == "/api/easy-apply/__system__/__default__"

    def test_unknown_action_is_rejected(self, mod):
        r = mod.dispatch({"action": "nuke"})
        assert r["ok"] is False and r["status"] == 400
        assert "unknown easy-apply action" in r["error"]
