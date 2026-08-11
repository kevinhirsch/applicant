"""AZ3 (#842) — the research proxy dispatch/forward routing.

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

HANDLER = Path(__file__).resolve().parents[2] / "a0-applicant/api/research.py"


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

    spec = importlib.util.spec_from_file_location("_az3_research", HANDLER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestResearchProxy:
    """Hermetic dispatch tests for the research proxy."""

    def test_cached_forwards_get(self, mod):
        seen = {}

        def fake(method, path, body=None, timeout=10):
            seen.update(method=method, path=path)
            return {"ok": True, "status": 200, "data": {"campaign_id": "c1", "report": {}}}

        with patch.object(mod, "_forward", fake):
            r = mod.dispatch({"action": "cached", "campaign_id": "c1"})
        assert seen["method"] == "GET"
        assert seen["path"] == "/api/research/c1/cached"

    def test_budget_forwards_get(self, mod):
        seen = {}

        def fake(method, path, body=None, timeout=10):
            seen.update(method=method, path=path)
            return {"ok": True, "status": 200, "data": {"campaign_id": "c1", "available": True}}

        with patch.object(mod, "_forward", fake):
            r = mod.dispatch({"action": "budget", "campaign_id": "c1"})
        assert seen == {"method": "GET", "path": "/api/research/c1/budget"}

    def test_run_forwards_post_with_body(self, mod):
        seen = {}

        def fake(method, path, body=None, timeout=10):
            seen.update(method=method, path=path, body=body)
            return {"ok": True, "status": 200, "data": {"campaign_id": "c1", "report": {}}}

        with patch.object(mod, "_forward", fake):
            r = mod.dispatch({
                "action": "run",
                "campaign_id": "c1",
                "query": "AI trends",
                "company": "Acme",
                "role": "engineer",
                "force": True,
            })
        assert seen["method"] == "POST"
        assert seen["path"] == "/api/research/c1/run"
        assert seen["body"]["query"] == "AI trends"
        assert seen["body"]["company"] == "Acme"
        assert seen["body"]["role"] == "engineer"
        assert seen["body"]["force"] is True

    def test_default_is_cached(self, mod):
        seen = {}

        def fake(method, path, body=None, timeout=10):
            seen.update(method=method, path=path)
            return {"ok": True, "status": 200, "data": {}}

        with patch.object(mod, "_forward", fake):
            r = mod.dispatch({"action": ""})
        assert seen == {"method": "GET", "path": "/api/research/__system__/cached"}

    def test_default_when_no_action(self, mod):
        seen = {}

        def fake(method, path, body=None, timeout=10):
            seen.update(method=method, path=path)
            return {"ok": True, "status": 200, "data": {}}

        with patch.object(mod, "_forward", fake):
            r = mod.dispatch({})
        assert seen == {"method": "GET", "path": "/api/research/__system__/cached"}

    def test_default_campaign_system(self, mod):
        seen = {}

        def fake(method, path, body=None, timeout=10):
            seen.update(method=method, path=path)
            return {"ok": True, "status": 200, "data": {}}

        with patch.object(mod, "_forward", fake):
            r = mod.dispatch({"action": "cached"})
        assert seen == {"method": "GET", "path": "/api/research/__system__/cached"}

    def test_unknown_action_rejected(self, mod):
        r = mod.dispatch({"action": "zoom"})
        assert r["ok"] is False and r["status"] == 400
        assert "unknown research action" in r["error"]
