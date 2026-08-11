"""AZ3 (#839) — the channels proxy dispatch/forward routing.

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

HANDLER = Path(__file__).resolve().parents[2] / "a0-applicant/api/channels.py"


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

    spec = importlib.util.spec_from_file_location("_az3_channels", HANDLER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestChannelsDispatch:
    """Pure dispatch tests for the channels proxy handler."""

    def test_test_action_forwards_to_channels_test(self, mod):
        seen = {}

        def fake(method, path, body=None, timeout=10):
            seen.update(method=method, path=path, body=body)
            return {"ok": True, "status": 200, "data": {"sent": True}}

        with patch.object(mod, "_forward", fake):
            r = mod.dispatch({"action": "test", "channel": "discord"})
        assert seen["method"] == "POST"
        assert seen["path"] == "/api/setup/channels/test"
        assert seen["body"] == {"channel": "discord"}

    def test_test_action_no_channel(self, mod):
        seen = {}

        def fake(method, path, body=None, timeout=10):
            seen.update(method=method, path=path, body=body)
            return {"ok": True, "status": 200, "data": {"sent": True}}

        with patch.object(mod, "_forward", fake):
            r = mod.dispatch({"action": "test"})
        assert seen["body"] == {}

    def test_set_quiet_hours_forwards(self, mod):
        seen = {}

        def fake(method, path, body=None, timeout=10):
            seen.update(method=method, path=path, body=body)
            return {"ok": True, "status": 204, "data": {}}

        with patch.object(mod, "_forward", fake):
            r = mod.dispatch({
                "action": "set_quiet_hours",
                "enabled": True,
                "start": "22:00",
                "end": "07:00",
                "tz": "America/New_York",
                "discord_respects_quiet": True,
                "email_respects_quiet": False,
            })
        assert seen["method"] == "POST"
        assert seen["path"] == "/api/setup/channels/quiet-hours"
        assert seen["body"] == {
            "enabled": True,
            "start": "22:00",
            "end": "07:00",
            "tz": "America/New_York",
            "discord_respects_quiet": True,
            "email_respects_quiet": False,
        }

    def test_set_quiet_hours_partial(self, mod):
        """Only include fields present in input."""
        seen = {}

        def fake(method, path, body=None, timeout=10):
            seen.update(method=method, path=path, body=body)
            return {"ok": True, "status": 204, "data": {}}

        with patch.object(mod, "_forward", fake):
            r = mod.dispatch({
                "action": "set_quiet_hours",
                "enabled": False,
            })
        assert seen["body"] == {"enabled": False}
        assert "start" not in seen["body"]
        assert "end" not in seen["body"]

    def test_get_action_forwards_get(self, mod):
        seen = {}

        def fake(method, path, body=None, timeout=10):
            seen.update(method=method, path=path)
            return {"ok": True, "status": 200, "data": {}}

        with patch.object(mod, "_forward", fake):
            r = mod.dispatch({"action": "get"})
        assert seen == {"method": "GET", "path": "/api/setup/channels"}

    def test_unknown_action_rejected(self, mod):
        r = mod.dispatch({"action": "nuke"})
        assert r["ok"] is False and r["status"] == 400
        assert "unknown channels action" in r["error"]
