"""AZ2 — the attributes proxy dispatch/forward routing.

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

HANDLER = Path(__file__).resolve().parents[2] / "a0-applicant/api/attributes.py"


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

    spec = importlib.util.spec_from_file_location("_az2_attributes", HANDLER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_list_forwards_get(mod):
    seen = {}

    def fake(method, path, body=None, timeout=10):
        seen.update(method=method, path=path)
        return {"ok": True, "status": 200, "data": []}

    with patch.object(mod, "_forward", fake):
        mod.dispatch({"action": "list", "campaign_id": "c123"})
    assert seen == {"method": "GET", "path": "/api/attributes/c123"}


def test_list_default_campaign(mod):
    seen = {}

    def fake(method, path, body=None, timeout=10):
        seen.update(method=method, path=path)
        return {"ok": True, "status": 200, "data": []}

    with patch.object(mod, "_forward", fake):
        mod.dispatch({"action": "list"})
    assert seen == {"method": "GET", "path": "/api/attributes/__system__"}


def test_add_forwards_post(mod):
    seen = {}

    def fake(method, path, body=None, timeout=10):
        seen.update(method=method, path=path, body=body)
        return {"ok": True, "status": 201, "data": {"id": "a1"}}

    with patch.object(mod, "_forward", fake):
        mod.dispatch({"action": "add", "campaign_id": "c123", "name": "Name", "value": "Val"})
    assert seen["method"] == "POST"
    assert seen["path"] == "/api/attributes"
    assert seen["body"] == {"campaign_id": "c123", "name": "Name", "value": "Val", "is_sensitive": False}


def test_add_with_sensitive(mod):
    seen = {}

    def fake(method, path, body=None, timeout=10):
        seen.update(method=method, path=path, body=body)
        return {"ok": True, "status": 201, "data": {"id": "a1"}}

    with patch.object(mod, "_forward", fake):
        mod.dispatch({"action": "add", "campaign_id": "c123", "name": "Name", "value": "Val", "is_sensitive": True})
    assert seen["method"] == "POST"
    assert seen["path"] == "/api/attributes"
    assert seen["body"] == {"campaign_id": "c123", "name": "Name", "value": "Val", "is_sensitive": True}


def test_delete_forwards_delete(mod):
    seen = {}

    def fake(method, path, body=None, timeout=10):
        seen.update(method=method, path=path)
        return {"ok": True, "status": 200, "data": {}}

    with patch.object(mod, "_forward", fake):
        mod.dispatch({"action": "delete", "campaign_id": "c123", "attribute_id": "a1"})
    assert seen == {"method": "DELETE", "path": "/api/attributes/c123/a1"}


def test_delete_missing_attribute_id(mod):
    r = mod.dispatch({"action": "delete", "campaign_id": "c123"})
    assert r["ok"] is False and r["status"] == 400
    assert r["error"] == "attribute_id required"


def test_default_action_is_list(mod):
    seen = {}

    def fake(method, path, body=None, timeout=10):
        seen.update(method=method, path=path)
        return {"ok": True, "status": 200, "data": []}

    with patch.object(mod, "_forward", fake):
        mod.dispatch({"action": ""})
    assert seen == {"method": "GET", "path": "/api/attributes/__system__"}


def test_default_action_when_no_action(mod):
    seen = {}

    def fake(method, path, body=None, timeout=10):
        seen.update(method=method, path=path)
        return {"ok": True, "status": 200, "data": []}

    with patch.object(mod, "_forward", fake):
        mod.dispatch({})
    assert seen == {"method": "GET", "path": "/api/attributes/__system__"}


def test_unknown_action_rejected(mod):
    r = mod.dispatch({"action": "nuke"})
    assert r["ok"] is False and r["status"] == 400
    assert "unknown attributes action" in r["error"]
