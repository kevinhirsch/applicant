"""AZ2 (#837) — the chat proxy dispatch/forward routing.

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

HANDLER = Path(__file__).resolve().parents[2] / "a0-applicant/api/chat.py"


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

    spec = importlib.util.spec_from_file_location("_az2_chat", HANDLER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestChatProxy:
    """Hermetic dispatch tests for the chat proxy."""

    def test_send_forwards_post(self, mod):
        seen = {}

        def fake(method, path, body=None, timeout=10):
            seen.update(method=method, path=path, body=body)
            return {"ok": True, "status": 200, "data": {"message": "Hello!"}}

        with patch.object(mod, "_forward", fake):
            r = mod.dispatch({"action": "send", "campaign_id": "c1", "message": "Hi"})
        assert seen["method"] == "POST"
        assert seen["path"] == "/api/chat"
        assert seen["body"]["campaign_id"] == "c1"
        assert seen["body"]["message"] == "Hi"

    def test_confirm_forwards_post_with_name_value(self, mod):
        seen = {}

        def fake(method, path, body=None, timeout=10):
            seen.update(method=method, path=path, body=body)
            return {"ok": True, "status": 200, "data": {}}

        with patch.object(mod, "_forward", fake):
            r = mod.dispatch({"action": "confirm", "campaign_id": "c1", "name": "salary", "value": "120k"})
        assert seen["method"] == "POST"
        assert seen["path"] == "/api/chat/confirm"
        assert seen["body"]["campaign_id"] == "c1"
        assert seen["body"]["name"] == "salary"
        assert seen["body"]["value"] == "120k"

    def test_confirm_criteria_forwards_post_with_changes(self, mod):
        seen = {}

        def fake(method, path, body=None, timeout=10):
            seen.update(method=method, path=path, body=body)
            return {"ok": True, "status": 200, "data": {}}

        with patch.object(mod, "_forward", fake):
            r = mod.dispatch({"action": "confirm_criteria", "campaign_id": "c1", "changes": {"salary_floor": 100}})
        assert seen["method"] == "POST"
        assert seen["path"] == "/api/chat/confirm-criteria"
        assert seen["body"]["campaign_id"] == "c1"
        assert seen["body"]["changes"] == {"salary_floor": 100}

    def test_default_action_is_send(self, mod):
        seen = {}

        def fake(method, path, body=None, timeout=10):
            seen.update(method=method, path=path, body=body)
            return {"ok": True, "status": 200, "data": {"message": "ok"}}

        with patch.object(mod, "_forward", fake):
            r = mod.dispatch({"action": "", "message": "hello"})
        assert seen["method"] == "POST"
        assert seen["path"] == "/api/chat"
        assert seen["body"]["message"] == "hello"

    def test_default_when_no_action(self, mod):
        seen = {}

        def fake(method, path, body=None, timeout=10):
            seen.update(method=method, path=path, body=body)
            return {"ok": True, "status": 200, "data": {"message": "ok"}}

        with patch.object(mod, "_forward", fake):
            r = mod.dispatch({"message": "hello"})
        assert seen["method"] == "POST"
        assert seen["path"] == "/api/chat"

    def test_default_campaign_system(self, mod):
        seen = {}

        def fake(method, path, body=None, timeout=10):
            seen.update(method=method, path=path, body=body)
            return {"ok": True, "status": 200, "data": {"message": "ok"}}

        with patch.object(mod, "_forward", fake):
            r = mod.dispatch({"action": "send", "message": "hi"})
        assert seen["body"]["campaign_id"] == "__system__"

    def test_send_empty_message_returns_400(self, mod):
        r = mod.dispatch({"action": "send", "campaign_id": "c1", "message": ""})
        assert r["ok"] is False and r["status"] == 400
        assert "message required" in r["error"]

    def test_unknown_action_rejected(self, mod):
        r = mod.dispatch({"action": "zoom"})
        assert r["ok"] is False and r["status"] == 400
        assert "unknown chat action" in r["error"]
