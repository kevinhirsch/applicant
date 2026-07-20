"""AZ3 (#840) — the feedback proxy dispatch/forward routing.

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

HANDLER = Path(__file__).resolve().parents[2] / "a0-applicant/api/feedback.py"


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

    spec = importlib.util.spec_from_file_location("_az3_feedback", HANDLER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(autouse=True)
def _reset_forward_calls():
    """Reset any state between tests — _forward is stateless, but ensures isolation."""
    yield


def test_history_forwards_get(mod):
    seen = {}

    def fake(method, path, body=None, timeout=10):
        seen.update(method=method, path=path)
        return {"ok": True, "status": 200, "data": {"items": []}}

    with patch.object(mod, "_forward", fake):
        r = mod.dispatch({"action": "history", "campaign_id": "c1"})
    assert seen == {"method": "GET", "path": "/api/feedback/c1"}


def test_freetext_forwards_post(mod):
    seen = {}

    def fake(method, path, body=None, timeout=10):
        seen.update(method=method, path=path, body=body)
        return {"ok": True, "status": 201, "data": {}}

    with patch.object(mod, "_forward", fake):
        r = mod.dispatch({
            "action": "freetext",
            "campaign_id": "c1",
            "text": "good job",
            "criteria_delta": {"weight": 0.9},
        })
    assert seen["method"] == "POST"
    assert seen["path"] == "/api/feedback/freetext"
    assert seen["body"] == {
        "campaign_id": "c1",
        "text": "good job",
        "criteria_delta": {"weight": 0.9},
    }


def test_freetext_default_empty_criteria_delta(mod):
    seen = {}

    def fake(method, path, body=None, timeout=10):
        seen.update(method=method, path=path, body=body)
        return {"ok": True, "status": 201, "data": {}}

    with patch.object(mod, "_forward", fake):
        r = mod.dispatch({"action": "freetext", "campaign_id": "c1", "text": "hi"})
    assert seen["body"]["criteria_delta"] == {}


def test_survey_forwards_post(mod):
    seen = {}

    def fake(method, path, body=None, timeout=10):
        seen.update(method=method, path=path, body=body)
        return {"ok": True, "status": 201, "data": {}}

    answers = {"q1": "yes", "q2": "no"}
    with patch.object(mod, "_forward", fake):
        r = mod.dispatch({
            "action": "survey",
            "campaign_id": "c1",
            "answers": answers,
        })
    assert seen["method"] == "POST"
    assert seen["path"] == "/api/feedback/survey"
    assert seen["body"] == {"campaign_id": "c1", "answers": answers}


def test_survey_default_empty_answers(mod):
    seen = {}

    def fake(method, path, body=None, timeout=10):
        seen.update(method=method, path=path, body=body)
        return {"ok": True, "status": 201, "data": {}}

    with patch.object(mod, "_forward", fake):
        r = mod.dispatch({"action": "survey", "campaign_id": "c1"})
    assert seen["body"]["answers"] == {}


def test_default_is_history(mod):
    seen = {}

    def fake(method, path, body=None, timeout=10):
        seen.update(method=method, path=path)
        return {"ok": True, "status": 200, "data": {}}

    with patch.object(mod, "_forward", fake):
        r = mod.dispatch({"action": ""})
    assert seen == {"method": "GET", "path": "/api/feedback/__system__"}


def test_default_when_no_action(mod):
    seen = {}

    def fake(method, path, body=None, timeout=10):
        seen.update(method=method, path=path)
        return {"ok": True, "status": 200, "data": {}}

    with patch.object(mod, "_forward", fake):
        r = mod.dispatch({})
    assert seen == {"method": "GET", "path": "/api/feedback/__system__"}


def test_default_campaign_system(mod):
    seen = {}

    def fake(method, path, body=None, timeout=10):
        seen.update(method=method, path=path)
        return {"ok": True, "status": 200, "data": {}}

    with patch.object(mod, "_forward", fake):
        r = mod.dispatch({"action": "history"})
    assert seen == {"method": "GET", "path": "/api/feedback/__system__"}


def test_unknown_action_rejected(mod):
    r = mod.dispatch({"action": "zoom"})
    assert r["ok"] is False and r["status"] == 400
    assert "unknown feedback action" in r["error"]
