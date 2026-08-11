# Copyright 2025 Kevin Hirsch — MIT License
"""EPIC STEALTH — stealth proxy dispatch/forward routing.

The proxy is an a0-applicant api handler that runs in the A0 shell, so we load just
its module with the framework imports stubbed and exercise the pure ``dispatch``
routing (hermetic — ``_forward`` is patched, no engine call). Mirrors
``test_model_config_proxy.py`` / ``test_az3_automation_proxy.py``.
"""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path
from unittest.mock import patch

import pytest

HANDLER = Path(__file__).resolve().parents[2] / "a0-applicant/api/stealth.py"


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

    spec = importlib.util.spec_from_file_location("_az_stealth", HANDLER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestStealthProxy:
    def _capture(self, mod):
        seen = {}

        def fake(method, path, body=None, timeout=10):
            seen.update(method=method, path=path, body=body)
            return {"ok": True, "status": 200, "data": {}}

        return seen, fake

    def test_get_forwards_get(self, mod):
        seen, fake = self._capture(mod)
        with patch.object(mod, "_forward", fake):
            r = mod.dispatch({"action": "get"})
        assert seen["method"] == "GET"
        assert seen["path"] == "/api/setup/stealth"
        assert r["ok"] is True

    def test_default_action_is_get(self, mod):
        seen, fake = self._capture(mod)
        with patch.object(mod, "_forward", fake):
            mod.dispatch({})
        assert seen["method"] == "GET"
        assert seen["path"] == "/api/setup/stealth"

    def test_set_forwards_put_stripping_action(self, mod):
        seen, fake = self._capture(mod)
        with patch.object(mod, "_forward", fake):
            mod.dispatch(
                {
                    "action": "set",
                    "egress_route": "residential",
                    "egress_proxy_url": "http://user:pass@resi:8880",
                    "request_pacing_ms": 3000,
                }
            )
        assert seen["method"] == "PUT"
        assert seen["path"] == "/api/setup/stealth"
        assert seen["body"] == {
            "egress_route": "residential",
            "egress_proxy_url": "http://user:pass@resi:8880",
            "request_pacing_ms": 3000,
        }
        assert "action" not in seen["body"]

    def test_unknown_action_is_400(self, mod):
        r = mod.dispatch({"action": "bogus"})
        assert r["ok"] is False and r["status"] == 400

    def test_forward_offline_degrades(self, mod):
        # No engine reachable: _forward returns a non-raising error envelope.
        r = mod.dispatch({"action": "get"})
        assert r["ok"] is False
        assert r["status"] == 0
        assert "error" in r
