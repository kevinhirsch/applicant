"""AZ2 (#833-#838) — the agent-runs (activity/daily-loop) proxy dispatch/forward routing.

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

HANDLER = Path(__file__).resolve().parents[2] / "a0-applicant/api/agent_runs.py"


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

    spec = importlib.util.spec_from_file_location("_az2_agent_runs", HANDLER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_status_forwards_get(mod):
    seen = {}

    def fake(method, path, body=None, timeout=10):
        seen.update(method=method, path=path)
        return {"ok": True, "status": 200, "data": {"running": True}}

    with patch.object(mod, "_forward", fake):
        r = mod.dispatch({"action": "status", "campaign_id": "c123"})
    assert seen == {"method": "GET", "path": "/api/agent-runs/c123/status"}


def test_intent_forwards_get(mod):
    seen = {}

    def fake(method, path, body=None, timeout=10):
        seen.update(method=method, path=path)
        return {"ok": True, "status": 200, "data": {"intent": "test"}}

    with patch.object(mod, "_forward", fake):
        r = mod.dispatch({"action": "intent", "campaign_id": "c123"})
    assert seen == {"method": "GET", "path": "/api/agent-runs/c123/intent"}


def test_list_forwards_get(mod):
    seen = {}

    def fake(method, path, body=None, timeout=10):
        seen.update(method=method, path=path)
        return {"ok": True, "status": 200, "data": {"runs": []}}

    with patch.object(mod, "_forward", fake):
        r = mod.dispatch({"action": "list", "campaign_id": "c123"})
    assert seen == {"method": "GET", "path": "/api/agent-runs/c123"}


def test_run_forwards_post(mod):
    seen = {}

    def fake(method, path, body=None, timeout=10):
        seen.update(method=method, path=path, body=body)
        return {"ok": True, "status": 201, "data": {"run_id": "r1"}}

    with patch.object(mod, "_forward", fake):
        r = mod.dispatch({"action": "run", "campaign_id": "c123"})
    assert seen["method"] == "POST"
    assert seen["path"] == "/api/agent-runs/c123/run"
    # No body for run
    assert seen["body"] is None


def test_pause_forwards_post(mod):
    seen = {}

    def fake(method, path, body=None, timeout=10):
        seen.update(method=method, path=path, body=body)
        return {"ok": True, "status": 200, "data": {"paused": True}}

    with patch.object(mod, "_forward", fake):
        r = mod.dispatch({"action": "pause", "campaign_id": "c123"})
    assert seen["method"] == "POST"
    assert seen["path"] == "/api/agent-runs/c123/pause"
    assert seen["body"] is None


def test_resume_forwards_post(mod):
    seen = {}

    def fake(method, path, body=None, timeout=10):
        seen.update(method=method, path=path, body=body)
        return {"ok": True, "status": 200, "data": {"running": True}}

    with patch.object(mod, "_forward", fake):
        r = mod.dispatch({"action": "resume", "campaign_id": "c123"})
    assert seen["method"] == "POST"
    assert seen["path"] == "/api/agent-runs/c123/resume"
    assert seen["body"] is None


def test_default_action_is_status(mod):
    seen = {}

    def fake(method, path, body=None, timeout=10):
        seen.update(method=method, path=path)
        return {"ok": True, "status": 200, "data": {"running": True}}

    with patch.object(mod, "_forward", fake):
        r = mod.dispatch({"action": ""})
    assert seen == {"method": "GET", "path": "/api/agent-runs/__system__/status"}


def test_default_action_is_status_when_no_action(mod):
    seen = {}

    def fake(method, path, body=None, timeout=10):
        seen.update(method=method, path=path)
        return {"ok": True, "status": 200, "data": {"running": True}}

    with patch.object(mod, "_forward", fake):
        r = mod.dispatch({})
    assert seen == {"method": "GET", "path": "/api/agent-runs/__system__/status"}


def test_default_campaign_id_is_system(mod):
    seen = {}

    def fake(method, path, body=None, timeout=10):
        seen.update(method=method, path=path)
        return {"ok": True, "status": 200, "data": {}}

    with patch.object(mod, "_forward", fake):
        r = mod.dispatch({"action": "status"})
    assert seen == {"method": "GET", "path": "/api/agent-runs/__system__/status"}


def test_unknown_action_is_rejected(mod):
    r = mod.dispatch({"action": "nuke"})
    assert r["ok"] is False and r["status"] == 400
    assert "unknown agent-runs action" in r["error"]
