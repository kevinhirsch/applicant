"""Model-endpoints proxy dispatch/forward routing.

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

HANDLER = Path(__file__).resolve().parents[2] / "a0-applicant/api/model_endpoints.py"


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

    spec = importlib.util.spec_from_file_location("_az_model_endpoints", HANDLER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestModelEndpointsProxy:
    """Hermetic dispatch tests for the model_endpoints proxy."""

    def test_list_forwards_get(self, mod):
        seen = {}

        def fake(method, path, body=None, timeout=10):
            seen.update(method=method, path=path)
            return {"ok": True, "status": 200, "data": []}

        with patch.object(mod, "_forward", fake):
            r = mod.dispatch({"action": "list"})
        assert seen == {"method": "GET", "path": "/api/model-endpoints"}
        assert r["ok"] is True

    def test_add_forwards_post(self, mod):
        seen = {}

        def fake(method, path, body=None, timeout=10):
            seen.update(method=method, path=path, body=body)
            return {"ok": True, "status": 201, "data": {"id": "ep-1"}}

        with patch.object(mod, "_forward", fake):
            r = mod.dispatch({
                "action": "add",
                "base_url": "http://localhost:11434",
                "api_key": "sk-xxx",
                "name": "local-ollama",
                "model_type": "llm",
            })
        assert seen["method"] == "POST"
        assert seen["path"] == "/api/model-endpoints"
        assert seen["body"] == {
            "base_url": "http://localhost:11434",
            "api_key": "sk-xxx",
            "name": "local-ollama",
            "model_type": "llm",
        }

    def test_add_passes_all_fields_with_skip_probe(self, mod):
        seen = {}

        def fake(method, path, body=None, timeout=10):
            seen.update(method=method, path=path, body=body)
            return {"ok": True, "status": 201, "data": {"id": "ep-2"}}

        with patch.object(mod, "_forward", fake):
            r = mod.dispatch({
                "action": "add",
                "base_url": "https://api.openai.com/v1",
                "api_key": "sk-xxx",
                "name": "openai",
                "model_type": "llm",
                "skip_probe": True,
            })
        assert seen["body"] == {
            "base_url": "https://api.openai.com/v1",
            "api_key": "sk-xxx",
            "name": "openai",
            "model_type": "llm",
            "skip_probe": True,
        }

    def test_test_forwards_post(self, mod):
        seen = {}

        def fake(method, path, body=None, timeout=10):
            seen.update(method=method, path=path, body=body)
            return {"ok": True, "status": 200, "data": {"reachable": True}}

        with patch.object(mod, "_forward", fake):
            r = mod.dispatch({
                "action": "test",
                "base_url": "http://localhost:11434",
                "api_key": "sk-xxx",
            })
        assert seen["method"] == "POST"
        assert seen["path"] == "/api/model-endpoints/test"
        assert seen["body"] == {"base_url": "http://localhost:11434", "api_key": "sk-xxx"}

    def test_remove_forwards_delete(self, mod):
        seen = {}

        def fake(method, path, body=None, timeout=10):
            seen.update(method=method, path=path)
            return {"ok": True, "status": 200, "data": {"ok": True}}

        with patch.object(mod, "_forward", fake):
            r = mod.dispatch({"action": "remove", "endpoint_id": "ep-1"})
        assert seen == {"method": "DELETE", "path": "/api/model-endpoints/ep-1"}

    def test_remove_requires_endpoint_id(self, mod):
        r = mod.dispatch({"action": "remove"})
        assert r["ok"] is False and r["status"] == 400
        assert "endpoint_id required" in r["error"]

    def test_models_forwards_get(self, mod):
        seen = {}

        def fake(method, path, body=None, timeout=10):
            seen.update(method=method, path=path)
            return {"ok": True, "status": 200, "data": {"models": ["llama3", "mistral"]}}

        with patch.object(mod, "_forward", fake):
            r = mod.dispatch({"action": "models", "endpoint_id": "ep-1"})
        assert seen == {"method": "GET", "path": "/api/model-endpoints/ep-1/models"}

    def test_models_requires_endpoint_id(self, mod):
        r = mod.dispatch({"action": "models"})
        assert r["ok"] is False and r["status"] == 400
        assert "endpoint_id required" in r["error"]

    def test_unknown_action_is_rejected(self, mod):
        r = mod.dispatch({"action": "nuke"})
        assert r["ok"] is False and r["status"] == 400
        assert "unknown model_endpoints action" in r["error"]
