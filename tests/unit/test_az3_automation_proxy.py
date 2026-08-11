"""AZ3 (#839) — the automation proxy dispatch/forward routing.

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

HANDLER = Path(__file__).resolve().parents[2] / "a0-applicant/api/automation.py"


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

    spec = importlib.util.spec_from_file_location("_az3_automation", HANDLER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestAutomationDispatch:
    """Pure dispatch tests for the automation proxy handler."""

    def test_get_forwards_get(self, mod):
        seen = {}

        def fake(method, path, body=None, timeout=10):
            seen.update(method=method, path=path)
            return {"ok": True, "status": 200, "data": {}}

        with patch.object(mod, "_forward", fake):
            r = mod.dispatch({"action": "get"})
        # The engine's setup router is mounted at prefix "/api/setup" (see
        # src/applicant/app/routers/setup.py's APIRouter(prefix="/api/setup", ...)
        # and its @router.get("/automation")), so the real forwarded path is
        # "/api/setup/automation" -- matching this proxy's own docstring/dispatch
        # code, which the "/api/automation" the assertion used to pin never was.
        assert seen == {"method": "GET", "path": "/api/setup/automation"}

    def test_set_forwards_put_with_body(self, mod):
        seen = {}

        def fake(method, path, body=None, timeout=10):
            seen.update(method=method, path=path, body=body)
            return {"ok": True, "status": 200, "data": {}}

        with patch.object(mod, "_forward", fake):
            r = mod.dispatch({"action": "set", "approval_timeout_days": 7})
        assert seen["method"] == "PUT"
        # See test_get_forwards_get: the engine's setup router prefix makes this
        # "/api/setup/automation", not "/api/automation".
        assert seen["path"] == "/api/setup/automation"
        assert seen["body"] == {"approval_timeout_days": 7}

    def test_set_sends_all_fields(self, mod):
        seen = {}

        def fake(method, path, body=None, timeout=10):
            seen.update(method=method, path=path, body=body)
            return {"ok": True, "status": 200, "data": {}}

        with patch.object(mod, "_forward", fake):
            r = mod.dispatch({
                "action": "set",
                "approval_timeout_days": 7,
                "scheduler_interval_seconds": 60.0,
                "ats_match_rate_floor": 0.5,
            })
        assert seen["body"] == {
            "approval_timeout_days": 7,
            "scheduler_interval_seconds": 60.0,
            "ats_match_rate_floor": 0.5,
        }

    def test_set_preserves_field_types(self, mod):
        seen = {}

        def fake(method, path, body=None, timeout=10):
            seen.update(method=method, path=path, body=body)
            return {"ok": True, "status": 200, "data": {}}

        with patch.object(mod, "_forward", fake):
            r = mod.dispatch({
                "action": "set",
                "approval_timeout_days": 7,
                "scheduler_interval_seconds": 60.0,
                "memory_write_approval": True,
                "allow_automated_accounts": False,
            })
        body = seen["body"]
        assert isinstance(body["approval_timeout_days"], int)
        assert isinstance(body["scheduler_interval_seconds"], float)
        assert isinstance(body["memory_write_approval"], bool)
        assert isinstance(body["allow_automated_accounts"], bool)
        assert body["memory_write_approval"] is True
        assert body["allow_automated_accounts"] is False

    def test_unknown_action_rejected(self, mod):
        r = mod.dispatch({"action": "nuke"})
        assert r["ok"] is False and r["status"] == 400
        assert "unknown automation action" in r["error"]

    def test_empty_action_falls_through(self, mod):
        r = mod.dispatch({})
        assert r["ok"] is False and r["status"] == 400
        assert "unknown automation action" in r["error"]
