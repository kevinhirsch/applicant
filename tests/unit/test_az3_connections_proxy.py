"""AZ3-6 (#844) — the connections proxy dispatch/forward routing.

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

HANDLER = Path(__file__).resolve().parents[2] / "a0-applicant/api/connections.py"


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

    spec = importlib.util.spec_from_file_location("_az3_connections", HANDLER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestConnectionsDispatch:
    """Pure dispatch tests for the connections proxy handler."""

    def test_get_email_accounts_forwards(self, mod):
        seen = {}

        def fake(method, path, body=None, timeout=10):
            seen.update(method=method, path=path)
            return {"ok": True, "status": 200, "data": []}

        with patch.object(mod, "_forward", fake):
            r = mod.dispatch({"action": "get_email_accounts"})
        assert seen["method"] == "GET"
        assert seen["path"] == "/api/email/accounts"

    def test_add_email_account_forwards_provided_keys(self, mod):
        seen = {}

        def fake(method, path, body=None, timeout=10):
            seen.update(method=method, path=path, body=body)
            return {"ok": True, "status": 201, "data": {"id": "acct_1"}}

        with patch.object(mod, "_forward", fake):
            r = mod.dispatch({
                "action": "add_email_account",
                "name": "Work",
                "imap_host": "imap.gmail.com",
                "imap_port": 993,
                "imap_user": "test@example.com",
                "imap_password": "test-imap-pass",
                "imap_starttls": False,
                "smtp_host": "smtp.gmail.com",
                "smtp_port": 465,
                "smtp_user": "test@example.com",
                "smtp_password": "test-smtp-pass",
                "from_address": "test@example.com",
            })
        assert seen["method"] == "POST"
        assert seen["path"] == "/api/email/accounts"
        assert seen["body"]["name"] == "Work"
        assert seen["body"]["imap_password"] == "test-imap-pass"
        assert seen["body"]["smtp_password"] == "test-smtp-pass"
        assert seen["body"]["imap_host"] == "imap.gmail.com"

    def test_add_email_account_only_provided_keys(self, mod):
        seen = {}

        def fake(method, path, body=None, timeout=10):
            seen.update(method=method, path=path, body=body)
            return {"ok": True, "status": 201, "data": {}}

        with patch.object(mod, "_forward", fake):
            r = mod.dispatch({
                "action": "add_email_account",
                "name": "Minimal",
            })
        assert seen["body"] == {"name": "Minimal"}

    def test_update_email_account_requires_account_id(self, mod):
        r = mod.dispatch({"action": "update_email_account"})
        assert r["ok"] is False and r["status"] == 400
        assert "account_id" in r["error"]

    def test_update_email_account_forwards_with_id(self, mod):
        seen = {}

        def fake(method, path, body=None, timeout=10):
            seen.update(method=method, path=path, body=body)
            return {"ok": True, "status": 200, "data": {}}

        with patch.object(mod, "_forward", fake):
            r = mod.dispatch({
                "action": "update_email_account",
                "account_id": "42",
                "name": "Updated",
                "imap_password": "test-new-pass",
            })
        assert seen["method"] == "PUT"
        assert seen["path"] == "/api/email/accounts/42"
        assert seen["body"] == {"name": "Updated", "imap_password": "test-new-pass"}

    def test_delete_email_account_requires_account_id(self, mod):
        r = mod.dispatch({"action": "delete_email_account"})
        assert r["ok"] is False and r["status"] == 400
        assert "account_id" in r["error"]

    def test_delete_email_account_forwards(self, mod):
        seen = {}

        def fake(method, path, body=None, timeout=10):
            seen.update(method=method, path=path)
            return {"ok": True, "status": 204, "data": {}}

        with patch.object(mod, "_forward", fake):
            r = mod.dispatch({"action": "delete_email_account", "account_id": "7"})
        assert seen["method"] == "DELETE"
        assert seen["path"] == "/api/email/accounts/7"

    def test_test_email_account_with_account_id(self, mod):
        seen = {}

        def fake(method, path, body=None, timeout=10):
            seen.update(method=method, path=path, body=body)
            return {"ok": True, "status": 200, "data": {"sent": True}}

        with patch.object(mod, "_forward", fake):
            r = mod.dispatch({"action": "test_email_account", "account_id": "10"})
        assert seen["method"] == "POST"
        assert seen["path"] == "/api/email/accounts/test"
        assert seen["body"] == {"account_id": "10"}

    def test_test_email_account_with_inline_creds(self, mod):
        seen = {}

        def fake(method, path, body=None, timeout=10):
            seen.update(method=method, path=path, body=body)
            return {"ok": True, "status": 200, "data": {"sent": True}}

        with patch.object(mod, "_forward", fake):
            r = mod.dispatch({
                "action": "test_email_account",
                "imap_host": "imap.test.com",
                "imap_user": "u",
                "imap_password": "test-pass",
            })
        assert seen["body"] == {
            "imap_host": "imap.test.com",
            "imap_user": "u",
            "imap_password": "test-pass",
        }

    def test_get_calendar_config_forwards(self, mod):
        seen = {}

        def fake(method, path, body=None, timeout=10):
            seen.update(method=method, path=path)
            return {"ok": True, "status": 200, "data": {}}

        with patch.object(mod, "_forward", fake):
            r = mod.dispatch({"action": "get_calendar_config"})
        assert seen["method"] == "GET"
        assert seen["path"] == "/api/calendar/config"

    def test_set_calendar_config_forwards(self, mod):
        seen = {}

        def fake(method, path, body=None, timeout=10):
            seen.update(method=method, path=path, body=body)
            return {"ok": True, "status": 200, "data": {}}

        with patch.object(mod, "_forward", fake):
            r = mod.dispatch({
                "action": "set_calendar_config",
                "url": "https://caldav.example.com",
                "username": "test@example.com",
                "password": "test-caldav-pass",
            })
        assert seen["method"] == "POST"
        assert seen["path"] == "/api/calendar/config"
        assert seen["body"]["url"] == "https://caldav.example.com"
        assert seen["body"]["password"] == "test-caldav-pass"
        assert seen["body"]["username"] == "test@example.com"

    def test_set_calendar_config_only_provided_keys(self, mod):
        seen = {}

        def fake(method, path, body=None, timeout=10):
            seen.update(method=method, path=path, body=body)
            return {"ok": True, "status": 200, "data": {}}

        with patch.object(mod, "_forward", fake):
            r = mod.dispatch({
                "action": "set_calendar_config",
                "password": "test-pass-only",
            })
        assert seen["body"] == {"password": "test-pass-only"}

    def test_test_calendar_config_forwards(self, mod):
        seen = {}

        def fake(method, path, body=None, timeout=10):
            seen.update(method=method, path=path, body=body)
            return {"ok": True, "status": 200, "data": {}}

        with patch.object(mod, "_forward", fake):
            r = mod.dispatch({
                "action": "test_calendar_config",
                "url": "https://caldav.example.com",
                "password": "test-caldav-pass",
            })
        assert seen["method"] == "POST"
        assert seen["path"] == "/api/calendar/test"
        assert seen["body"]["password"] == "test-caldav-pass"

    def test_unknown_action_rejected(self, mod):
        r = mod.dispatch({"action": "nuke"})
        assert r["ok"] is False and r["status"] == 400
        assert "unknown connections action" in r["error"]
