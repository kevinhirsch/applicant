"""AZ3 (#841) — the mind proxy dispatch/forward routing.

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

HANDLER = Path(__file__).resolve().parents[2] / "a0-applicant/api/mind.py"


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

    spec = importlib.util.spec_from_file_location("_az3_mind", HANDLER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_memory_forwards_get(mod):
    seen = {}

    def fake(method, path, body=None, timeout=10):
        seen.update(method=method, path=path)
        return {"ok": True, "status": 200, "data": {"environment": [], "user": [], "truncated": False}}

    with patch.object(mod, "_forward", fake):
        r = mod.dispatch({"action": "memory"})
    assert seen == {"method": "GET", "path": "/api/agent-memory"}


def test_skills_forwards_get(mod):
    seen = {}

    def fake(method, path, body=None, timeout=10):
        seen.update(method=method, path=path)
        return {"ok": True, "status": 200, "data": {"items": []}}

    with patch.object(mod, "_forward", fake):
        r = mod.dispatch({"action": "skills"})
    assert seen == {"method": "GET", "path": "/api/agent-memory/skills"}


def test_curation_forwards_get(mod):
    seen = {}

    def fake(method, path, body=None, timeout=10):
        seen.update(method=method, path=path)
        return {"ok": True, "status": 200, "data": {"count": 0, "items": []}}

    with patch.object(mod, "_forward", fake):
        r = mod.dispatch({"action": "curation"})
    assert seen == {"method": "GET", "path": "/api/agent-memory/curation"}


def test_approve_forwards_post_with_proposal_id(mod):
    seen = {}

    def fake(method, path, body=None, timeout=10):
        seen.update(method=method, path=path)
        return {"ok": True, "status": 200, "data": {"ok": True, "id": "p123"}}

    with patch.object(mod, "_forward", fake):
        r = mod.dispatch({"action": "approve", "proposal_id": "p123"})
    assert seen == {"method": "POST", "path": "/api/agent-memory/curation/p123/approve"}


def test_approve_missing_proposal_id(mod):
    r = mod.dispatch({"action": "approve"})
    assert r["ok"] is False and r["status"] == 400
    assert r["error"] == "proposal_id required"


def test_forget_forwards_post(mod):
    seen = {}

    def fake(method, path, body=None, timeout=10):
        seen.update(method=method, path=path, body=body)
        return {"ok": True, "status": 200, "data": {"ok": True, "applied": 0, "staged": 1}}

    with patch.object(mod, "_forward", fake):
        r = mod.dispatch({"action": "forget", "ref": "abc123", "text": "some note"})
    assert seen["method"] == "POST"
    assert seen["path"] == "/api/agent-memory/forget"
    assert seen["body"] == {"ref": "abc123", "text": "some note"}


def test_forget_passes_scope_and_campaign_id(mod):
    seen = {}

    def fake(method, path, body=None, timeout=10):
        seen.update(method=method, path=path, body=body)
        return {"ok": True, "status": 200, "data": {}}

    with patch.object(mod, "_forward", fake):
        r = mod.dispatch({"action": "forget", "ref": "r1", "scope": "env", "campaign_id": "c1"})
    assert seen["method"] == "POST"
    assert seen["path"] == "/api/agent-memory/forget"
    assert seen["body"] == {"ref": "r1", "scope": "env", "campaign_id": "c1"}


def test_forget_empty_body(mod):
    seen = {}

    def fake(method, path, body=None, timeout=10):
        seen.update(method=method, path=path, body=body)
        return {"ok": True, "status": 200, "data": {}}

    with patch.object(mod, "_forward", fake):
        r = mod.dispatch({"action": "forget"})
    assert seen["method"] == "POST"
    assert seen["path"] == "/api/agent-memory/forget"
    assert seen["body"] == {}


def test_default_is_memory(mod):
    seen = {}

    def fake(method, path, body=None, timeout=10):
        seen.update(method=method, path=path)
        return {"ok": True, "status": 200, "data": {}}

    with patch.object(mod, "_forward", fake):
        r = mod.dispatch({"action": ""})
    assert seen == {"method": "GET", "path": "/api/agent-memory"}


def test_default_when_no_action(mod):
    seen = {}

    def fake(method, path, body=None, timeout=10):
        seen.update(method=method, path=path)
        return {"ok": True, "status": 200, "data": {}}

    with patch.object(mod, "_forward", fake):
        r = mod.dispatch({})
    assert seen == {"method": "GET", "path": "/api/agent-memory"}


def test_unknown_action_rejected(mod):
    r = mod.dispatch({"action": "nuke"})
    assert r["ok"] is False and r["status"] == 400
    assert r["error"] == "unknown mind action 'nuke'"
