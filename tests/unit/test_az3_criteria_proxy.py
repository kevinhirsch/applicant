"""AZ3 (#840) — the criteria proxy dispatch/forward routing.

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

HANDLER = Path(__file__).resolve().parents[2] / "a0-applicant/api/criteria.py"


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

    spec = importlib.util.spec_from_file_location("_az3_criteria", HANDLER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(autouse=True)
def _reset_forward_calls():
    """Reset any state between tests — _forward is stateless, but ensures isolation."""
    yield


def test_view_forwards_get(mod):
    seen = {}

    def fake(method, path, body=None, timeout=10):
        seen.update(method=method, path=path)
        return {"ok": True, "status": 200, "data": {"criteria": []}}

    with patch.object(mod, "_forward", fake):
        r = mod.dispatch({"action": "view", "campaign_id": "c1"})
    assert seen == {"method": "GET", "path": "/api/criteria/c1"}


def test_signature_forwards_get(mod):
    seen = {}

    def fake(method, path, body=None, timeout=10):
        seen.update(method=method, path=path)
        return {"ok": True, "status": 200, "data": {}}

    with patch.object(mod, "_forward", fake):
        r = mod.dispatch({"action": "signature", "campaign_id": "c1"})
    assert seen == {"method": "GET", "path": "/api/criteria/c1/signature"}


def test_apply_learned_forwards_post(mod):
    seen = {}

    def fake(method, path, body=None, timeout=10):
        seen.update(method=method, path=path, body=body)
        return {"ok": True, "status": 200, "data": {}}

    adj = {"weight": 0.8, "threshold": 0.5}
    with patch.object(mod, "_forward", fake):
        r = mod.dispatch({
            "action": "apply_learned",
            "campaign_id": "c1",
            "adjustment": adj,
            "rationale": "test reason",
        })
    assert seen["method"] == "POST"
    assert seen["path"] == "/api/criteria/c1/learned"
    assert seen["body"] == {"adjustment": adj, "rationale": "test reason"}


def test_default_is_view(mod):
    seen = {}

    def fake(method, path, body=None, timeout=10):
        seen.update(method=method, path=path)
        return {"ok": True, "status": 200, "data": {}}

    with patch.object(mod, "_forward", fake):
        r = mod.dispatch({"action": ""})
    assert seen == {"method": "GET", "path": "/api/criteria/__system__"}


def test_default_when_no_action(mod):
    seen = {}

    def fake(method, path, body=None, timeout=10):
        seen.update(method=method, path=path)
        return {"ok": True, "status": 200, "data": {}}

    with patch.object(mod, "_forward", fake):
        r = mod.dispatch({})
    assert seen == {"method": "GET", "path": "/api/criteria/__system__"}


def test_default_campaign_system(mod):
    seen = {}

    def fake(method, path, body=None, timeout=10):
        seen.update(method=method, path=path)
        return {"ok": True, "status": 200, "data": {}}

    with patch.object(mod, "_forward", fake):
        r = mod.dispatch({"action": "view"})
    assert seen == {"method": "GET", "path": "/api/criteria/__system__"}


def test_unknown_action_rejected(mod):
    r = mod.dispatch({"action": "zoom"})
    assert r["ok"] is False and r["status"] == 400
    assert "unknown criteria action" in r["error"]
