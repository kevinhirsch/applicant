"""AZ1-2 (#830) — the OOBE onboarding proxy dispatch/forward routing.

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

HANDLER = Path(__file__).resolve().parents[2] / "a0-applicant/api/onboarding.py"


@pytest.fixture()
def onb():
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

    spec = importlib.util.spec_from_file_location("_az12_onb", HANDLER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_state_forwards_get_to_engine(onb):
    seen = {}

    def fake(method, path, body=None, timeout=10):
        seen.update(method=method, path=path)
        return {"ok": True, "status": 200, "data": {"sections_complete": ["identity"]}}

    with patch.object(onb, "_forward", fake):
        r = onb.dispatch({"campaign_id": "c1", "action": "state"})
    assert seen == {"method": "GET", "path": "/api/onboarding/c1"}
    assert r["data"]["sections_complete"] == ["identity"]


def test_section_forwards_post_with_body(onb):
    seen = {}

    def fake(method, path, body=None, timeout=10):
        seen.update(method=method, path=path, body=body)
        return {"ok": True, "status": 200, "data": {}}

    with patch.object(onb, "_forward", fake):
        onb.dispatch({"campaign_id": "c1", "action": "section",
                      "section": "identity", "data": {"name": "Jane"}})
    assert seen["method"] == "POST"
    assert seen["path"] == "/api/onboarding/c1/section"
    assert seen["body"] == {"section": "identity", "data": {"name": "Jane"}}


def test_complete_returns_engine_readiness_verbatim(onb):
    def fake(method, path, body=None, timeout=10):
        return {"ok": True, "status": 200,
                "data": {"apply_ready": False, "apply_missing": ["base_resume"]}}

    with patch.object(onb, "_forward", fake):
        r = onb.dispatch({"campaign_id": "c1", "action": "complete"})
    assert r["data"]["apply_missing"] == ["base_resume"]  # engine truth, not client-derived


def test_defaults_to_system_campaign_and_state(onb):
    seen = {}
    with patch.object(onb, "_forward", lambda *a, **k: seen.update(path=a[1]) or {"ok": True}):
        onb.dispatch({})
    assert seen["path"] == "/api/onboarding/__system__"


def test_unknown_action_is_rejected(onb):
    r = onb.dispatch({"action": "delete_everything"})
    assert r["ok"] is False and r["status"] == 400
