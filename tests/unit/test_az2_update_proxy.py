"""AZ2 (#841) — the update-proxy dispatch/forward routing.

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

HANDLER = Path(__file__).resolve().parents[2] / "a0-applicant/api/update_panel.py"


@pytest.fixture()
def upd():
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

    spec = importlib.util.spec_from_file_location("_az2_upd", HANDLER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_status_forwards_get(upd):
    seen = {}

    def fake(method, path, body=None, timeout=10):
        seen.update(method=method, path=path)
        return {"ok": True, "status": 200, "data": {"state": "idle", "updater_available": True}}

    with patch.object(upd, "_forward", fake):
        r = upd.dispatch({"action": "status"})
    assert seen == {"method": "GET", "path": "/api/update"}
    assert r["data"]["state"] == "idle"


def test_trigger_forwards_post(upd):
    seen = {}

    def fake(method, path, body=None, timeout=10):
        seen.update(method=method, path=path)
        return {"ok": True, "status": 200, "data": {"started": True, "message": "Update requested"}}

    with patch.object(upd, "_forward", fake):
        r = upd.dispatch({"action": "trigger"})
    assert seen == {"method": "POST", "path": "/api/update/trigger"}
    assert r["data"]["started"] is True


def test_default_action_is_status(upd):
    seen = {}

    def fake(method, path, body=None, timeout=10):
        seen.update(method=method, path=path)
        return {"ok": True, "status": 200, "data": {"state": "idle"}}

    with patch.object(upd, "_forward", fake):
        upd.dispatch({})
    assert seen["path"] == "/api/update"
    assert seen["method"] == "GET"


def test_unknown_action_is_rejected(upd):
    r = upd.dispatch({"action": "reboot"})
    assert r["ok"] is False and r["status"] == 400


def test_class_api_handler_wraps_dispatch(upd):
    """Verify the UpdatePanel class's process() delegates to dispatch()."""
    seen = {}

    def fake(method, path, body=None, timeout=10):
        seen.update(method=method, path=path)
        return {"ok": True, "status": 200, "data": {"state": "idle"}}

    with patch.object(upd, "_forward", fake):
        panel = upd.UpdatePanel()
        import asyncio
        r = asyncio.run(panel.process({}, None))
    assert seen["path"] == "/api/update"
    assert r["ok"] is True
