"""AZ2 (#836) — the takeover proxy dispatch/forward routing.

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

HANDLER = Path(__file__).resolve().parents[2] / "a0-applicant/api/takeover.py"


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

    spec = importlib.util.spec_from_file_location("_az2_takeover", HANDLER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestTakeoverProxy:
    """Hermetic dispatch tests for the takeover proxy."""

    def test_default_is_sessions(self, mod):
        """No action defaults to sessions."""
        seen = {}

        def fake(method, path, body=None, timeout=10):
            seen.update(method=method, path=path)
            return {"ok": True, "status": 200, "data": {}}

        with patch.object(mod, "_forward", fake):
            r = mod.dispatch({})
        assert seen["method"] == "GET"
        assert seen["path"] == "/api/remote/sessions"

    def test_sessions_forwards_get(self, mod):
        seen = {}

        def fake(method, path, body=None, timeout=10):
            seen.update(method=method, path=path)
            return {"ok": True, "status": 200, "data": {}}

        with patch.object(mod, "_forward", fake):
            r = mod.dispatch({"action": "sessions"})
        assert seen["method"] == "GET"
        assert seen["path"] == "/api/remote/sessions"

    def test_view_url_forwards_get(self, mod):
        seen = {}

        def fake(method, path, body=None, timeout=10):
            seen.update(method=method, path=path)
            return {"ok": True, "status": 200, "data": {}}

        with patch.object(mod, "_forward", fake):
            r = mod.dispatch({"action": "view_url", "session_id": "sess1"})
        assert seen["method"] == "GET"
        assert seen["path"] == "/api/remote/sessions/sess1/view-url"

    def test_takeover_forwards_post(self, mod):
        seen = {}

        def fake(method, path, body=None, timeout=10):
            seen.update(method=method, path=path)
            return {"ok": True, "status": 204, "data": {}}

        with patch.object(mod, "_forward", fake):
            r = mod.dispatch({"action": "takeover", "session_id": "sess1"})
        assert seen["method"] == "POST"
        assert seen["path"] == "/api/remote/sessions/sess1/takeover"

    def test_resume_2fa_forwards_post(self, mod):
        seen = {}

        def fake(method, path, body=None, timeout=10):
            seen.update(method=method, path=path)
            return {"ok": True, "status": 200, "data": {}}

        with patch.object(mod, "_forward", fake):
            r = mod.dispatch({"action": "resume_2fa", "application_id": "app1"})
        assert seen["method"] == "POST"
        assert seen["path"] == "/api/remote/applications/app1/continue-two-factor"

    def test_resume_account_forwards_post(self, mod):
        seen = {}

        def fake(method, path, body=None, timeout=10):
            seen.update(method=method, path=path)
            return {"ok": True, "status": 200, "data": {}}

        with patch.object(mod, "_forward", fake):
            r = mod.dispatch({"action": "resume_account", "application_id": "app1"})
        assert seen["method"] == "POST"
        assert seen["path"] == "/api/remote/applications/app1/resume-account-step"

    def test_resume_detection_forwards_post(self, mod):
        seen = {}

        def fake(method, path, body=None, timeout=10):
            seen.update(method=method, path=path)
            return {"ok": True, "status": 200, "data": {}}

        with patch.object(mod, "_forward", fake):
            r = mod.dispatch({"action": "resume_detection", "application_id": "app1"})
        assert seen["method"] == "POST"
        assert seen["path"] == "/api/remote/applications/app1/resume-detection-step"

    def test_handoff_forwards_get(self, mod):
        seen = {}

        def fake(method, path, body=None, timeout=10):
            seen.update(method=method, path=path)
            return {"ok": True, "status": 200, "data": {}}

        with patch.object(mod, "_forward", fake):
            r = mod.dispatch({"action": "handoff", "application_id": "app1"})
        assert seen["method"] == "GET"
        assert seen["path"] == "/api/remote/applications/app1/emergency-handoff"

    def test_final_approval_forwards_post(self, mod):
        seen = {}

        def fake(method, path, body=None, timeout=10):
            seen.update(method=method, path=path, body=body)
            return {"ok": True, "status": 202, "data": {}}

        with patch.object(mod, "_forward", fake):
            r = mod.dispatch({"action": "final_approval", "application_id": "app1", "mode": "agent"})
        assert seen["method"] == "POST"
        assert seen["path"] == "/api/remote/applications/app1/request-final-approval"

    def test_view_url_requires_session_id(self, mod):
        r = mod.dispatch({"action": "view_url"})
        assert not r["ok"]
        assert r["status"] == 400
        assert "session_id" in r.get("error", "")

    def test_takeover_requires_session_id(self, mod):
        r = mod.dispatch({"action": "takeover"})
        assert not r["ok"]
        assert r["status"] == 400
        assert "session_id" in r.get("error", "")

    def test_resume_2fa_requires_application_id(self, mod):
        r = mod.dispatch({"action": "resume_2fa"})
        assert not r["ok"]
        assert r["status"] == 400
        assert "application_id" in r.get("error", "")

    def test_resume_account_requires_application_id(self, mod):
        r = mod.dispatch({"action": "resume_account"})
        assert not r["ok"]
        assert r["status"] == 400
        assert "application_id" in r.get("error", "")

    def test_resume_detection_requires_application_id(self, mod):
        r = mod.dispatch({"action": "resume_detection"})
        assert not r["ok"]
        assert r["status"] == 400
        assert "application_id" in r.get("error", "")

    def test_handoff_requires_application_id(self, mod):
        r = mod.dispatch({"action": "handoff"})
        assert not r["ok"]
        assert r["status"] == 400
        assert "application_id" in r.get("error", "")

    def test_final_approval_requires_application_id(self, mod):
        r = mod.dispatch({"action": "final_approval"})
        assert not r["ok"]
        assert r["status"] == 400
        assert "application_id" in r.get("error", "")

    def test_final_approval_requires_mode(self, mod):
        r = mod.dispatch({"action": "final_approval", "application_id": "app1"})
        assert not r["ok"]
        assert r["status"] == 400
        assert "mode" in r.get("error", "")

    def test_final_approval_requires_valid_mode(self, mod):
        r = mod.dispatch({"action": "final_approval", "application_id": "app1", "mode": "invalid"})
        assert not r["ok"]
        assert r["status"] == 400
        assert "mode" in r.get("error", "")

    def test_final_approval_agent_mode(self, mod):
        seen = {}
        def fake(method, path, body=None, timeout=10):
            seen.update(method=method, path=path, body=body)
            return {"ok": True, "status": 202, "data": {}}
        with patch.object(mod, "_forward", fake):
            r = mod.dispatch({"action": "final_approval", "application_id": "app1", "mode": "agent"})
        assert seen["method"] == "POST"
        assert seen["path"] == "/api/remote/applications/app1/request-final-approval"
        assert seen["body"] == {"mode": "agent"}

    def test_final_approval_self_mode(self, mod):
        seen = {}
        def fake(method, path, body=None, timeout=10):
            seen.update(method=method, path=path, body=body)
            return {"ok": True, "status": 202, "data": {}}
        with patch.object(mod, "_forward", fake):
            r = mod.dispatch({"action": "final_approval", "application_id": "app1", "mode": "self"})
        assert seen["method"] == "POST"
        assert seen["path"] == "/api/remote/applications/app1/request-final-approval"
        assert seen["body"] == {"mode": "self"}

    def test_unknown_action(self, mod):
        r = mod.dispatch({"action": "nonsense"})
        assert not r["ok"]
        assert r["status"] == 400
        assert "nonsense" in r.get("error", "")
