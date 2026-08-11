"""AZ3 (#840) — the compare proxy dispatch/forward routing.

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

HANDLER = Path(__file__).resolve().parents[2] / "a0-applicant/api/compare.py"


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

    spec = importlib.util.spec_from_file_location("_az3_compare", HANDLER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(autouse=True)
def _reset_forward_calls():
    """Reset any state between tests — _forward is stateless, but ensures isolation."""
    yield


def test_applications_forwards_post(mod):
    seen = {}

    def fake(method, path, body=None, timeout=10):
        seen.update(method=method, path=path, body=body)
        return {"ok": True, "status": 200, "data": {}}

    with patch.object(mod, "_forward", fake):
        r = mod.dispatch({"action": "applications", "ids": ["a1", "a2"], "campaign_id": "c1"})
    assert seen["method"] == "POST"
    assert seen["path"] == "/api/compare/applications?campaign_id=c1"
    assert seen["body"] == ["a1", "a2"]


def test_applications_without_campaign_id(mod):
    seen = {}

    def fake(method, path, body=None, timeout=10):
        seen.update(method=method, path=path, body=body)
        return {"ok": True, "status": 200, "data": {}}

    with patch.object(mod, "_forward", fake):
        r = mod.dispatch({"action": "applications", "ids": ["x", "y"]})
    assert seen["method"] == "POST"
    assert seen["path"] == "/api/compare/applications"
    assert seen["body"] == ["x", "y"]


def test_applications_uses_application_ids_key(mod):
    seen = {}

    def fake(method, path, body=None, timeout=10):
        seen.update(method=method, path=path, body=body)
        return {"ok": True, "status": 200, "data": {}}

    with patch.object(mod, "_forward", fake):
        r = mod.dispatch({"action": "applications", "application_ids": ["p1", "p2"]})
    assert seen["body"] == ["p1", "p2"]


def test_postings_forwards_post(mod):
    seen = {}

    def fake(method, path, body=None, timeout=10):
        seen.update(method=method, path=path, body=body)
        return {"ok": True, "status": 200, "data": {}}

    with patch.object(mod, "_forward", fake):
        r = mod.dispatch({"action": "postings", "ids": ["p1", "p2"], "campaign_id": "camp-x"})
    assert seen["method"] == "POST"
    assert seen["path"] == "/api/compare/postings?campaign_id=camp-x"
    assert seen["body"] == ["p1", "p2"]


def test_postings_without_campaign_id(mod):
    seen = {}

    def fake(method, path, body=None, timeout=10):
        seen.update(method=method, path=path, body=body)
        return {"ok": True, "status": 200, "data": {}}

    with patch.object(mod, "_forward", fake):
        r = mod.dispatch({"action": "postings", "ids": ["j1", "j2"]})
    assert seen["method"] == "POST"
    assert seen["path"] == "/api/compare/postings"
    assert seen["body"] == ["j1", "j2"]


def test_postings_uses_posting_ids_key(mod):
    seen = {}

    def fake(method, path, body=None, timeout=10):
        seen.update(method=method, path=path, body=body)
        return {"ok": True, "status": 200, "data": {}}

    with patch.object(mod, "_forward", fake):
        r = mod.dispatch({"action": "postings", "posting_ids": ["j1", "j2"]})
    assert seen["body"] == ["j1", "j2"]


def test_empty_ids_rejected(mod):
    r = mod.dispatch({"action": "applications", "ids": []})
    assert r["ok"] is False and r["status"] == 400
    assert "ids required" in r["error"]


def test_empty_ids_rejected_for_postings(mod):
    r = mod.dispatch({"action": "postings", "ids": []})
    assert r["ok"] is False and r["status"] == 400
    assert "ids required" in r["error"]


def test_default_is_applications(mod):
    seen = {}

    def fake(method, path, body=None, timeout=10):
        seen.update(method=method, path=path, body=body)
        return {"ok": True, "status": 200, "data": {}}

    with patch.object(mod, "_forward", fake):
        r = mod.dispatch({"ids": ["d1", "d2"]})
    assert seen["method"] == "POST"
    assert seen["path"] == "/api/compare/applications"


def test_unknown_action_rejected(mod):
    r = mod.dispatch({"action": "zoom"})
    assert r["ok"] is False and r["status"] == 400
    assert "unknown compare action" in r["error"]
