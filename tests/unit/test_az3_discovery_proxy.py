"""AZ3 (#844) — the discovery-sources proxy dispatch/forward routing.

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

HANDLER = Path(__file__).resolve().parents[2] / "a0-applicant/api/discovery.py"


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

    spec = importlib.util.spec_from_file_location("_az3_discovery", HANDLER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(autouse=True)
def _reset_forward_calls():
    """Reset any state between tests — _forward is stateless, but ensures isolation."""
    yield


@pytest.fixture(autouse=True)
def _clear_cache():
    yield


def test_list_forwards_get(mod):
    seen = {}

    def fake(method, path, body=None, timeout=10):
        seen.update(method=method, path=path)
        return {"ok": True, "status": 200, "data": {"items": []}}

    with patch.object(mod, "_forward", fake):
        r = mod.dispatch({"action": "list", "campaign_id": "c1"})
    assert seen == {"method": "GET", "path": "/api/discovery-sources/c1"}


def test_set_forwards_put(mod):
    seen = {}

    def fake(method, path, body=None, timeout=10):
        seen.update(method=method, path=path, body=body)
        return {"ok": True, "status": 200, "data": {}}

    with patch.object(mod, "_forward", fake):
        r = mod.dispatch({"action": "set", "campaign_id": "c1", "source_key": "jobspy", "enabled": True})
    assert seen["method"] == "PUT"
    assert seen["path"] == "/api/discovery-sources/c1/jobspy"
    assert seen["body"] == {"enabled": True}


def test_default_is_list(mod):
    seen = {}

    def fake(method, path, body=None, timeout=10):
        seen.update(method=method, path=path)
        return {"ok": True, "status": 200, "data": {}}

    with patch.object(mod, "_forward", fake):
        r = mod.dispatch({"action": ""})
    assert seen == {"method": "GET", "path": "/api/discovery-sources/__system__"}


def test_default_when_no_action(mod):
    seen = {}

    def fake(method, path, body=None, timeout=10):
        seen.update(method=method, path=path)
        return {"ok": True, "status": 200, "data": {}}

    with patch.object(mod, "_forward", fake):
        r = mod.dispatch({})
    assert seen == {"method": "GET", "path": "/api/discovery-sources/__system__"}


def test_default_campaign_system(mod):
    seen = {}

    def fake(method, path, body=None, timeout=10):
        seen.update(method=method, path=path)
        return {"ok": True, "status": 200, "data": {}}

    with patch.object(mod, "_forward", fake):
        r = mod.dispatch({"action": "list"})
    assert seen == {"method": "GET", "path": "/api/discovery-sources/__system__"}


def test_set_missing_source_key(mod):
    r = mod.dispatch({"action": "set", "campaign_id": "c1"})
    assert r["ok"] is False and r["status"] == 400
    assert "source_key required" in r["error"]


def test_unknown_action_rejected(mod):
    r = mod.dispatch({"action": "zoom"})
    assert r["ok"] is False and r["status"] == 400
    assert "unknown discovery action" in r["error"]
