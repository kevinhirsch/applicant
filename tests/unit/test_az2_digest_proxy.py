"""AZ2 — the digest proxy dispatch/forward routing.

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

HANDLER = Path(__file__).resolve().parents[2] / "a0-applicant/api/digest.py"


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

    spec = importlib.util.spec_from_file_location("_az2_digest", HANDLER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_get_forwards_get(mod):
    seen = {}

    def fake(method, path, body=None, timeout=10):
        seen.update(method=method, path=path)
        return {"ok": True, "status": 200, "data": {}}

    with patch.object(mod, "_forward", fake):
        mod.dispatch({"action": "get", "campaign_id": "c123"})
    assert seen == {"method": "GET", "path": "/api/digest/c123"}


def test_get_with_default_campaign(mod):
    seen = {}

    def fake(method, path, body=None, timeout=10):
        seen.update(method=method, path=path)
        return {"ok": True, "status": 200, "data": {}}

    with patch.object(mod, "_forward", fake):
        mod.dispatch({"action": "get"})
    assert seen == {"method": "GET", "path": "/api/digest/__system__"}


def test_recap_forwards_get(mod):
    seen = {}

    def fake(method, path, body=None, timeout=10):
        seen.update(method=method, path=path)
        return {"ok": True, "status": 200, "data": {}}

    with patch.object(mod, "_forward", fake):
        mod.dispatch({"action": "recap", "campaign_id": "c123"})
    assert seen == {"method": "GET", "path": "/api/digest/c123/weekly-recap"}


def test_approve_forwards_post(mod):
    seen = {}

    def fake(method, path, body=None, timeout=10):
        seen.update(method=method, path=path, body=body)
        return {"ok": True, "status": 200, "data": {}}

    with patch.object(mod, "_forward", fake):
        mod.dispatch({"action": "approve", "application_id": "a1"})
    assert seen["method"] == "POST"
    assert seen["path"] == "/api/digest/applications/a1/approve"
    assert seen["body"] is None


def test_decline_forwards_post(mod):
    seen = {}

    def fake(method, path, body=None, timeout=10):
        seen.update(method=method, path=path, body=body)
        return {"ok": True, "status": 200, "data": {}}

    with patch.object(mod, "_forward", fake):
        mod.dispatch({"action": "decline", "application_id": "a1", "reason": "bad fit"})
    assert seen["method"] == "POST"
    assert seen["path"] == "/api/digest/applications/a1/decline"
    assert seen["body"] == {"feedback_text": "bad fit"}


def test_default_action_is_get(mod):
    seen = {}

    def fake(method, path, body=None, timeout=10):
        seen.update(method=method, path=path)
        return {"ok": True, "status": 200, "data": {}}

    with patch.object(mod, "_forward", fake):
        r = mod.dispatch({"action": ""})
    assert seen == {"method": "GET", "path": "/api/digest/__system__"}


def test_default_action_when_no_action(mod):
    seen = {}

    def fake(method, path, body=None, timeout=10):
        seen.update(method=method, path=path)
        return {"ok": True, "status": 200, "data": {}}

    with patch.object(mod, "_forward", fake):
        r = mod.dispatch({})
    assert seen == {"method": "GET", "path": "/api/digest/__system__"}


def test_missing_campaign_resolves_to_active_campaign(mod):
    seen = []
    campaigns = [
        {"id": "c_old", "active": False},
        {"id": "e827b520afcf4018ad48152b06e1ee84", "active": True},
        {"id": "c_other", "active": False},
    ]

    def fake(method, path, body=None, timeout=10):
        seen.append((method, path))
        if path == "/api/campaigns":
            return {"ok": True, "status": 200, "data": campaigns}
        return {"ok": True, "status": 200, "data": {}}

    with patch.object(mod, "_forward", fake):
        r = mod.dispatch({"action": "get"})
    assert r == {"ok": True, "status": 200, "data": {}}
    assert seen[0] == ("GET", "/api/campaigns")
    assert seen[-1] == ("GET", "/api/digest/e827b520afcf4018ad48152b06e1ee84")


def test_active_campaign_resolution_is_cached(mod):
    seen = []

    def fake(method, path, body=None, timeout=10):
        seen.append((method, path))
        if path == "/api/campaigns":
            return {"ok": True, "status": 200, "data": [{"id": "c1", "active": True}]}
        return {"ok": True, "status": 200, "data": {}}

    with patch.object(mod, "_forward", fake):
        mod.dispatch({"action": "get"})
        mod.dispatch({"action": "get"})
    assert seen[0] == ("GET", "/api/campaigns")
    assert seen[1] == ("GET", "/api/digest/c1")
    assert seen[2] == ("GET", "/api/digest/c1")
    assert seen.count(("GET", "/api/campaigns")) == 1


def test_approve_missing_application_id(mod):
    r = mod.dispatch({"action": "approve"})
    assert r["ok"] is False and r["status"] == 400
    assert r["error"] == "application_id required"


def test_decline_missing_application_id(mod):
    r = mod.dispatch({"action": "decline"})
    assert r["ok"] is False and r["status"] == 400
    assert r["error"] == "application_id required"


def test_unknown_action_is_rejected(mod):
    r = mod.dispatch({"action": "xyz"})
    assert r["ok"] is False and r["status"] == 400
    assert "unknown digest action" in r["error"]
