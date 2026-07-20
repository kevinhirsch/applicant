"""AZ3 (#840) — the tracker proxy dispatch/forward routing.

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

HANDLER = Path(__file__).resolve().parents[2] / "a0-applicant/api/tracker.py"


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

    spec = importlib.util.spec_from_file_location("_az3_tracker", HANDLER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestTrackerProxy:
    """Hermetic dispatch tests for the tracker proxy."""

    def test_board_forwards_get(self, mod):
        seen = {}

        def fake(method, path, body=None, timeout=10):
            seen.update(method=method, path=path)
            return {"ok": True, "status": 200, "data": {"campaign_id": "c1", "applications": []}}

        with patch.object(mod, "_forward", fake):
            r = mod.dispatch({"action": "board", "campaign_id": "c1"})
        assert seen == {"method": "GET", "path": "/api/post-submission/c1"}

    def test_attention_forwards_get(self, mod):
        seen = {}

        def fake(method, path, body=None, timeout=10):
            seen.update(method=method, path=path)
            return {"ok": True, "status": 200, "data": {"campaign_id": "c1", "ghosted": [], "followups_due": []}}

        with patch.object(mod, "_forward", fake):
            r = mod.dispatch({"action": "attention", "campaign_id": "c1"})
        assert seen == {"method": "GET", "path": "/api/post-submission/c1/attention"}

    def test_default_is_board(self, mod):
        seen = {}

        def fake(method, path, body=None, timeout=10):
            seen.update(method=method, path=path)
            return {"ok": True, "status": 200, "data": {"applications": []}}

        with patch.object(mod, "_forward", fake):
            r = mod.dispatch({"action": ""})
        assert seen == {"method": "GET", "path": "/api/post-submission/__system__"}

    def test_default_when_no_action(self, mod):
        seen = {}

        def fake(method, path, body=None, timeout=10):
            seen.update(method=method, path=path)
            return {"ok": True, "status": 200, "data": {"applications": []}}

        with patch.object(mod, "_forward", fake):
            r = mod.dispatch({})
        assert seen == {"method": "GET", "path": "/api/post-submission/__system__"}

    def test_default_campaign_system(self, mod):
        seen = {}

        def fake(method, path, body=None, timeout=10):
            seen.update(method=method, path=path)
            return {"ok": True, "status": 200, "data": {"applications": []}}

        with patch.object(mod, "_forward", fake):
            r = mod.dispatch({"action": "board"})
        assert seen == {"method": "GET", "path": "/api/post-submission/__system__"}

    def test_unknown_action_rejected(self, mod):
        r = mod.dispatch({"action": "zoom"})
        assert r["ok"] is False and r["status"] == 400
        assert "unknown tracker action" in r["error"]
