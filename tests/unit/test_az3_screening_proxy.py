"""AZ2 (#842) — the screening proxy dispatch/forward routing.

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

HANDLER = Path(__file__).resolve().parents[2] / "a0-applicant/api/screening.py"


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

    spec = importlib.util.spec_from_file_location("_az3_screening", HANDLER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestScreeningProxy:
    """Hermetic dispatch tests for the screening proxy."""

    def test_library_forwards_get(self, mod):
        seen = {}

        def fake(method, path, body=None, timeout=10):
            seen.update(method=method, path=path)
            return {"ok": True, "status": 200, "data": {"campaign_id": "c1", "items": []}}

        with patch.object(mod, "_forward", fake):
            r = mod.dispatch({"action": "library", "campaign_id": "c1"})
        assert seen == {"method": "GET", "path": "/api/documents/screening-answer-library/c1"}
        assert r["ok"] is True

    def test_library_default_campaign_id(self, mod):
        seen = {}

        def fake(method, path, body=None, timeout=10):
            seen.update(method=method, path=path)
            return {"ok": True, "status": 200, "data": {"campaign_id": "__system__", "items": []}}

        with patch.object(mod, "_forward", fake):
            r = mod.dispatch({"action": "library"})
        assert seen == {"method": "GET", "path": "/api/documents/screening-answer-library/__system__"}

    def test_generate_forwards_post(self, mod):
        seen = {}

        def fake(method, path, body=None, timeout=10):
            seen.update(method=method, path=path, body=body)
            return {"ok": True, "status": 201, "data": {"id": "sa-1", "type": "factual", "approved": False, "content": "..."}}

        with patch.object(mod, "_forward", fake):
            r = mod.dispatch({
                "action": "generate",
                "campaign_id": "c1",
                "application_id": "app-1",
                "question": "Why do you want to work here?",
            })
        assert seen["method"] == "POST"
        assert seen["path"] == "/api/documents/screening-answer"
        assert seen["body"] == {"campaign_id": "c1", "application_id": "app-1", "question": "Why do you want to work here?"}

    def test_generate_passes_all_fields(self, mod):
        seen = {}

        def fake(method, path, body=None, timeout=10):
            seen.update(method=method, path=path, body=body)
            return {"ok": True, "status": 201, "data": {"id": "sa-2"}}

        with patch.object(mod, "_forward", fake):
            r = mod.dispatch({
                "action": "generate",
                "campaign_id": "c2",
                "application_id": "app-2",
                "question": "Notice period?",
                "true_source": "source",
                "essay": False,
                "explicit_answer": "2 weeks",
            })
        assert seen["body"] == {
            "campaign_id": "c2",
            "application_id": "app-2",
            "question": "Notice period?",
            "true_source": "source",
            "essay": False,
            "explicit_answer": "2 weeks",
        }

    def test_default_action_is_library(self, mod):
        seen = {}

        def fake(method, path, body=None, timeout=10):
            seen.update(method=method, path=path)
            return {"ok": True, "status": 200, "data": {"campaign_id": "__system__", "items": []}}

        with patch.object(mod, "_forward", fake):
            r = mod.dispatch({"action": ""})
        assert seen == {"method": "GET", "path": "/api/documents/screening-answer-library/__system__"}

    def test_default_action_when_no_action(self, mod):
        seen = {}

        def fake(method, path, body=None, timeout=10):
            seen.update(method=method, path=path)
            return {"ok": True, "status": 200, "data": {"campaign_id": "__system__", "items": []}}

        with patch.object(mod, "_forward", fake):
            r = mod.dispatch({})
        assert seen["method"] == "GET"
        assert seen["path"] == "/api/documents/screening-answer-library/__system__"

    def test_unknown_action_is_rejected(self, mod):
        r = mod.dispatch({"action": "nuke"})
        assert r["ok"] is False and r["status"] == 400
        assert "unknown screening action" in r["error"]
