"""AZ2 (#842) — the vault proxy dispatch/forward routing.

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

HANDLER = Path(__file__).resolve().parents[2] / "a0-applicant/api/vault.py"


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

    spec = importlib.util.spec_from_file_location("_az3_vault", HANDLER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestVaultProxy:
    """Hermetic dispatch tests for the vault proxy."""

    def test_list_forwards_get(self, mod):
        seen = {}

        def fake(method, path, body=None, timeout=10):
            seen.update(method=method, path=path)
            return {"ok": True, "status": 200, "data": {"campaign_id": "c1", "tenants": ["google"]}}

        with patch.object(mod, "_forward", fake):
            r = mod.dispatch({"action": "list", "campaign_id": "c1"})
        assert seen == {"method": "GET", "path": "/api/credentials/c1/tenants"}
        assert r["ok"] is True

    def test_list_default_campaign_id(self, mod):
        seen = {}

        def fake(method, path, body=None, timeout=10):
            seen.update(method=method, path=path)
            return {"ok": True, "status": 200, "data": {"campaign_id": "__system__", "tenants": []}}

        with patch.object(mod, "_forward", fake):
            r = mod.dispatch({"action": "list"})
        assert seen == {"method": "GET", "path": "/api/credentials/__system__/tenants"}

    def test_add_forwards_post(self, mod):
        seen = {}

        def fake(method, path, body=None, timeout=10):
            seen.update(method=method, path=path, body=body)
            return {"ok": True, "status": 201, "data": {"campaign_id": "c1", "tenant_key": "google", "source": "manual"}}

        with patch.object(mod, "_forward", fake):
            r = mod.dispatch({
                "action": "add",
                "campaign_id": "c1",
                "tenant_key": "google",
                "username": "user@example.com",
                "secret": "s3cret",
            })
        assert seen["method"] == "POST"
        assert seen["path"] == "/api/credentials"
        assert seen["body"] == {"campaign_id": "c1", "tenant_key": "google", "username": "user@example.com", "secret": "s3cret"}

    def test_account_forwards_get(self, mod):
        seen = {}

        def fake(method, path, body=None, timeout=10):
            seen.update(method=method, path=path)
            return {"ok": True, "status": 200, "data": {"google": True, "predefined_account": False}}

        with patch.object(mod, "_forward", fake):
            r = mod.dispatch({"action": "account"})
        assert seen == {"method": "GET", "path": "/api/credentials/account"}

    def test_bank_account_forwards_post(self, mod):
        seen = {}

        def fake(method, path, body=None, timeout=10):
            seen.update(method=method, path=path, body=body)
            return {"ok": True, "status": 201, "data": {"kind": "google", "scope": "global"}}

        with patch.object(mod, "_forward", fake):
            r = mod.dispatch({
                "action": "bank_account",
                "kind": "google",
                "username": "user",
                "secret": "s3cret",
            })
        assert seen["method"] == "POST"
        assert seen["path"] == "/api/credentials/account"
        assert seen["body"] == {"kind": "google", "username": "user", "secret": "s3cret"}

    def test_rotate_key_forwards_post(self, mod):
        seen = {}

        def fake(method, path, body=None, timeout=10):
            seen.update(method=method, path=path)
            return {"ok": True, "status": 200, "data": {"rotated": True, "records": 5}}

        with patch.object(mod, "_forward", fake):
            r = mod.dispatch({"action": "rotate_key"})
        assert seen == {"method": "POST", "path": "/api/credentials/rotate-key"}

    def test_unknown_action_is_rejected(self, mod):
        r = mod.dispatch({"action": "nuke"})
        assert r["ok"] is False and r["status"] == 400
        assert "unknown vault action" in r["error"]
