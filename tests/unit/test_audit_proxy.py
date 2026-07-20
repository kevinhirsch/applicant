"""AZ2 (#842) — the audit proxy dispatch/forward routing.

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

HANDLER = Path(__file__).resolve().parents[2] / "a0-applicant/api/audit.py"


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

    spec = importlib.util.spec_from_file_location("_az3_audit", HANDLER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestAuditProxy:
    """Hermetic dispatch tests for the audit proxy."""

    def test_log_forwards_get(self, mod):
        seen = {}

        def fake(method, path, body=None, timeout=10):
            seen.update(method=method, path=path)
            return {"ok": True, "status": 200, "data": {"entries": []}}

        with patch.object(mod, "_forward", fake):
            r = mod.dispatch({"action": "log", "campaign_id": "c1"})
        assert seen == {"method": "GET", "path": "/api/admin/audit-log/c1/export.json"}
        assert r["ok"] is True

    def test_log_default_campaign_id(self, mod):
        seen = {}

        def fake(method, path, body=None, timeout=10):
            seen.update(method=method, path=path)
            return {"ok": True, "status": 200, "data": {"entries": []}}

        with patch.object(mod, "_forward", fake):
            r = mod.dispatch({"action": "log"})
        assert seen == {"method": "GET", "path": "/api/admin/audit-log/__system__/export.json"}

    def test_application_log_forwards_get(self, mod):
        seen = {}

        def fake(method, path, body=None, timeout=10):
            seen.update(method=method, path=path)
            return {"ok": True, "status": 200, "data": {"entries": []}}

        with patch.object(mod, "_forward", fake):
            r = mod.dispatch({"action": "application_log", "application_id": "app-1"})
        assert seen == {"method": "GET", "path": "/api/admin/audit-log/application/app-1/export.json"}

    def test_application_log_requires_app_id(self, mod):
        r = mod.dispatch({"action": "application_log"})
        assert r["ok"] is False and r["status"] == 400
        assert "application_id is required" in r["error"]

    def test_unknown_action_is_rejected(self, mod):
        r = mod.dispatch({"action": "nuke"})
        assert r["ok"] is False and r["status"] == 400
        assert "unknown audit action" in r["error"]
