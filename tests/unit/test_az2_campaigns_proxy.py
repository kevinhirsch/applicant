"""AZ2 (#833-#838) — the campaigns proxy dispatch/forward routing.

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

HANDLER = Path(__file__).resolve().parents[2] / "a0-applicant/api/campaigns.py"


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

    spec = importlib.util.spec_from_file_location("_az2_campaigns", HANDLER)
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
    assert seen == {"method": "GET", "path": "/api/campaigns"}


def test_create_forwards_post_with_name(mod):
    seen = {}

    def fake(method, path, body=None, timeout=10):
        seen.update(method=method, path=path, body=body)
        return {"ok": True, "status": 201, "data": {"id": "c1"}}

    with patch.object(mod, "_forward", fake):
        mod.dispatch({"action": "create", "name": "My Campaign"})
    assert seen["method"] == "POST"
    assert seen["path"] == "/api/campaigns"
    assert seen["body"] == {"name": "My Campaign"}


def test_create_forwards_post_without_name(mod):
    seen = {}

    def fake(method, path, body=None, timeout=10):
        seen.update(method=method, path=path, body=body)
        return {"ok": True, "status": 201, "data": {"id": "c1"}}

    with patch.object(mod, "_forward", fake):
        mod.dispatch({"action": "create"})
    assert seen["method"] == "POST"
    assert seen["path"] == "/api/campaigns"
    assert seen["body"] == {"name": None}


def test_update_forwards_patch(mod):
    seen = {}

    def fake(method, path, body=None, timeout=10):
        seen.update(method=method, path=path, body=body)
        return {"ok": True, "status": 200, "data": {"id": "c123"}}

    with patch.object(mod, "_forward", fake):
        mod.dispatch({"action": "update", "campaign_id": "c123", "active": False})
    assert seen["method"] == "PATCH"
    assert seen["path"] == "/api/campaigns/c123"
    assert seen["body"] == {"active": False}


def test_update_partial_body_only_supplied_keys(mod):
    seen = {}

    def fake(method, path, body=None, timeout=10):
        seen.update(method=method, path=path, body=body)
        return {"ok": True, "status": 200, "data": {"id": "c123"}}

    with patch.object(mod, "_forward", fake):
        mod.dispatch({"action": "update", "campaign_id": "c123", "name": "NewName"})
    assert seen["method"] == "PATCH"
    assert seen["path"] == "/api/campaigns/c123"
    assert seen["body"] == {"name": "NewName"}


def test_clone_forwards_post_with_name(mod):
    seen = {}

    def fake(method, path, body=None, timeout=10):
        seen.update(method=method, path=path, body=body)
        return {"ok": True, "status": 201, "data": {"id": "c123"}}

    with patch.object(mod, "_forward", fake):
        mod.dispatch({"action": "clone", "campaign_id": "c123", "name": "Clone"})
    assert seen["method"] == "POST"
    assert seen["path"] == "/api/campaigns/c123/clone"
    assert seen["body"] == {"name": "Clone"}


def test_clone_forwards_post_without_name(mod):
    seen = {}

    def fake(method, path, body=None, timeout=10):
        seen.update(method=method, path=path, body=body)
        return {"ok": True, "status": 201, "data": {"id": "c123"}}

    with patch.object(mod, "_forward", fake):
        mod.dispatch({"action": "clone", "campaign_id": "c123"})
    assert seen["method"] == "POST"
    assert seen["path"] == "/api/campaigns/c123/clone"
    # When name is absent, body is {} which is falsy, so _forward gets body=None
    assert seen["body"] is None


def test_guardrails_forwards_get(mod):
    seen = {}

    def fake(method, path, body=None, timeout=10):
        seen.update(method=method, path=path)
        return {"ok": True, "status": 200, "data": {"today": {}, "monthly": {}}}

    with patch.object(mod, "_forward", fake):
        mod.dispatch({"action": "guardrails", "campaign_id": "c123"})
    assert seen == {"method": "GET", "path": "/api/campaigns/c123/guardrails"}


def test_default_action_is_list(mod):
    seen = {}

    def fake(method, path, body=None, timeout=10):
        seen.update(method=method, path=path)
        return {"ok": True, "status": 200, "data": []}

    with patch.object(mod, "_forward", fake):
        r = mod.dispatch({"action": ""})
    assert seen == {"method": "GET", "path": "/api/campaigns"}


def test_default_action_is_list_when_no_action(mod):
    seen = {}

    def fake(method, path, body=None, timeout=10):
        seen.update(method=method, path=path)
        return {"ok": True, "status": 200, "data": []}

    with patch.object(mod, "_forward", fake):
        r = mod.dispatch({})
    assert seen == {"method": "GET", "path": "/api/campaigns"}


def test_unknown_action_is_rejected(mod):
    r = mod.dispatch({"action": "nuke"})
    assert r["ok"] is False and r["status"] == 400
    assert "unknown campaigns action" in r["error"]


def test_update_missing_campaign_id(mod):
    r = mod.dispatch({"action": "update"})
    assert r["ok"] is False and r["status"] == 400
    assert r["error"] == "campaign_id required"


def test_clone_missing_campaign_id(mod):
    r = mod.dispatch({"action": "clone"})
    assert r["ok"] is False and r["status"] == 400
    assert r["error"] == "campaign_id required"


def test_guardrails_missing_campaign_id(mod):
    r = mod.dispatch({"action": "guardrails"})
    assert r["ok"] is False and r["status"] == 400
    assert r["error"] == "campaign_id required"
