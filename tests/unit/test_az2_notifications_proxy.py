"""AZ2 (#833-#838) — the notifications proxy dispatch/forward routing.

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

HANDLER = Path(__file__).resolve().parents[2] / "a0-applicant/api/notifications.py"


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

    spec = importlib.util.spec_from_file_location("_az2_notifications", HANDLER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_list_forwards_get(mod):
    seen = {}

    def fake(method, path, body=None, timeout=10):
        seen.update(method=method, path=path)
        return {"ok": True, "status": 200, "data": []}

    with patch.object(mod, "_forward", fake):
        r = mod.dispatch({"action": "list"})
    assert seen == {"method": "GET", "path": "/api/notifications?include_seen=false"}


def test_list_with_include_seen_passthrough(mod):
    seen = {}

    def fake(method, path, body=None, timeout=10):
        seen.update(method=method, path=path)
        return {"ok": True, "status": 200, "data": []}

    with patch.object(mod, "_forward", fake):
        mod.dispatch({"action": "list", "include_seen": True})
    assert seen == {"method": "GET", "path": "/api/notifications?include_seen=true"}


def test_seen_forwards_post(mod):
    seen = {}

    def fake(method, path, body=None, timeout=10):
        seen.update(method=method, path=path)
        return {"ok": True, "status": 200, "data": {}}

    with patch.object(mod, "_forward", fake):
        mod.dispatch({"action": "seen", "notification_id": "n123"})
    assert seen == {"method": "POST", "path": "/api/notifications/n123/seen"}


def test_deliver_now_forwards_post(mod):
    seen = {}

    def fake(method, path, body=None, timeout=10):
        seen.update(method=method, path=path, body=body)
        return {"ok": True, "status": 200, "data": {}}

    with patch.object(mod, "_forward", fake):
        mod.dispatch({"action": "deliver_now"})
    assert seen["method"] == "POST"
    assert seen["path"] == "/api/notifications/deliver-now"
    assert seen["body"] is None


def test_default_action_is_list(mod):
    seen = {}

    def fake(method, path, body=None, timeout=10):
        seen.update(method=method, path=path)
        return {"ok": True, "status": 200, "data": []}

    with patch.object(mod, "_forward", fake):
        r = mod.dispatch({"action": ""})
    assert seen == {"method": "GET", "path": "/api/notifications?include_seen=false"}


def test_default_action_when_no_action(mod):
    seen = {}

    def fake(method, path, body=None, timeout=10):
        seen.update(method=method, path=path)
        return {"ok": True, "status": 200, "data": []}

    with patch.object(mod, "_forward", fake):
        r = mod.dispatch({})
    assert seen == {"method": "GET", "path": "/api/notifications?include_seen=false"}


def test_seen_missing_notification_id(mod):
    r = mod.dispatch({"action": "seen"})
    assert r["ok"] is False and r["status"] == 400
    assert r["error"] == "notification_id required"


def test_unknown_action_is_rejected(mod):
    r = mod.dispatch({"action": "nuke"})
    assert r["ok"] is False and r["status"] == 400
    assert "unknown notifications action" in r["error"]
