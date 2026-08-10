"""EPIC MODEL-CONFIG — model_config proxy dispatch/forward routing.

The proxy is an a0-applicant api handler that runs in the A0 shell, so we load just
its module with the framework imports stubbed and exercise the pure ``dispatch``
routing (hermetic — ``_forward`` is patched, no engine call). Mirrors
``test_model_endpoints_proxy.py``.
"""
from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path
from unittest.mock import patch

import pytest

HANDLER = Path(__file__).resolve().parents[2] / "a0-applicant/api/model_config.py"


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

    spec = importlib.util.spec_from_file_location("_az_model_config", HANDLER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestModelConfigProxy:
    def _capture(self, mod):
        seen = {}

        def fake(method, path, body=None, timeout=10):
            seen.update(method=method, path=path, body=body)
            return {"ok": True, "status": 200, "data": {}}

        return seen, fake

    def test_get_use_cases_forwards_get(self, mod):
        seen, fake = self._capture(mod)
        with patch.object(mod, "_forward", fake):
            r = mod.dispatch({"action": "get_use_cases"})
        assert seen["method"] == "GET"
        assert seen["path"] == "/api/setup/llm/use-cases"
        assert r["ok"] is True

    def test_default_action_is_get_use_cases(self, mod):
        seen, fake = self._capture(mod)
        with patch.object(mod, "_forward", fake):
            mod.dispatch({})
        assert seen["path"] == "/api/setup/llm/use-cases"

    def test_set_use_case_forwards_put_with_body(self, mod):
        seen, fake = self._capture(mod)
        with patch.object(mod, "_forward", fake):
            mod.dispatch(
                {
                    "action": "set_use_case",
                    "use_case": "drafting_cover_letter",
                    "mode": "endpoint",
                    "endpoint_id": "ep-1",
                    "model": "deepseek-v4-flash",
                }
            )
        assert seen["method"] == "PUT"
        assert seen["path"] == "/api/setup/llm/use-cases/drafting_cover_letter"
        assert seen["body"] == {
            "mode": "endpoint",
            "endpoint_id": "ep-1",
            "model": "deepseek-v4-flash",
        }

    def test_set_use_case_requires_use_case(self, mod):
        r = mod.dispatch({"action": "set_use_case", "mode": "default"})
        assert r["ok"] is False and r["status"] == 400

    def test_clear_use_case_forwards_delete(self, mod):
        seen, fake = self._capture(mod)
        with patch.object(mod, "_forward", fake):
            mod.dispatch({"action": "clear_use_case", "use_case": "chat"})
        assert seen["method"] == "DELETE"
        assert seen["path"] == "/api/setup/llm/use-cases/chat"

    def test_get_smart_routing_forwards_get(self, mod):
        seen, fake = self._capture(mod)
        with patch.object(mod, "_forward", fake):
            mod.dispatch({"action": "get_smart_routing"})
        assert seen["method"] == "GET"
        assert seen["path"] == "/api/setup/llm/smart-routing"

    def test_set_smart_routing_forwards_put_partial(self, mod):
        seen, fake = self._capture(mod)
        with patch.object(mod, "_forward", fake):
            mod.dispatch({"action": "set_smart_routing", "enabled": False})
        assert seen["method"] == "PUT"
        assert seen["path"] == "/api/setup/llm/smart-routing"
        assert seen["body"] == {"enabled": False}  # prefer_local omitted -> untouched

    def test_from_endpoint_forwards_post(self, mod):
        seen, fake = self._capture(mod)
        with patch.object(mod, "_forward", fake):
            mod.dispatch(
                {"action": "from_endpoint", "endpoint_id": "ep-1", "model": "m"}
            )
        assert seen["method"] == "POST"
        assert seen["path"] == "/api/setup/llm/from-endpoint"
        assert seen["body"] == {"endpoint_id": "ep-1", "model": "m"}

    def test_from_endpoint_requires_fields(self, mod):
        r = mod.dispatch({"action": "from_endpoint", "endpoint_id": "ep-1"})
        assert r["ok"] is False and r["status"] == 400

    def test_unknown_action_is_400(self, mod):
        r = mod.dispatch({"action": "bogus"})
        assert r["ok"] is False and r["status"] == 400
