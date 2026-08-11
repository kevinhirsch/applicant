"""AZ3 (#839) — the fonts proxy dispatch/forward routing.

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

HANDLER = Path(__file__).resolve().parents[2] / "a0-applicant/api/fonts.py"


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

    spec = importlib.util.spec_from_file_location("_az3_fonts", HANDLER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestFontsDispatch:
    """Pure dispatch tests for the fonts proxy handler."""

    def test_list_forwards_get(self, mod):
        seen = {}

        def fake(method, path, body=None, timeout=10):
            seen.update(method=method, path=path)
            return {"ok": True, "status": 200, "data": {"installed": []}}

        with patch.object(mod, "_forward", fake):
            r = mod.dispatch({"action": "list"})
        assert seen == {"method": "GET", "path": "/api/fonts"}

    def test_detect_forwards_post(self, mod):
        seen = {}

        def fake(method, path, body=None, timeout=10):
            seen.update(method=method, path=path, body=body)
            return {"ok": True, "status": 200, "data": {"required": [], "missing": [], "installed": []}}

        with patch.object(mod, "_forward", fake):
            r = mod.dispatch({"action": "detect"})
        assert seen["method"] == "POST"
        assert seen["path"] == "/api/fonts/detect"
        assert seen["body"] is None

    def test_install_forwards_post_with_body(self, mod):
        seen = {}

        def fake(method, path, body=None, timeout=10):
            seen.update(method=method, path=path, body=body)
            return {"ok": True, "status": 200, "data": {"installed": ["Lato"], "confirmed": True}}

        with patch.object(mod, "_forward", fake):
            r = mod.dispatch({"action": "install", "name": "Lato"})
        assert seen["method"] == "POST"
        assert seen["path"] == "/api/fonts/install"
        assert seen["body"] == {"name": "Lato"}

    def test_install_forwards_with_file(self, mod):
        seen = {}

        def fake(method, path, body=None, timeout=10):
            seen.update(method=method, path=path, body=body)
            return {"ok": True, "status": 200, "data": {"installed": ["Custom"], "confirmed": True}}

        with patch.object(mod, "_forward", fake):
            r = mod.dispatch({"action": "install", "name": "Custom", "file": "base64..."})
        assert seen["body"] == {"name": "Custom", "file": "base64..."}

    def test_default_is_list(self, mod):
        seen = {}

        def fake(method, path, body=None, timeout=10):
            seen.update(method=method, path=path)
            return {"ok": True, "status": 200, "data": {"installed": []}}

        with patch.object(mod, "_forward", fake):
            r = mod.dispatch({"action": ""})
        assert seen == {"method": "GET", "path": "/api/fonts"}

    def test_default_when_no_action(self, mod):
        seen = {}

        def fake(method, path, body=None, timeout=10):
            seen.update(method=method, path=path)
            return {"ok": True, "status": 200, "data": {"installed": []}}

        with patch.object(mod, "_forward", fake):
            r = mod.dispatch({})
        assert seen == {"method": "GET", "path": "/api/fonts"}

    def test_unknown_action_rejected(self, mod):
        r = mod.dispatch({"action": "nuke"})
        assert r["ok"] is False and r["status"] == 400
        assert "unknown fonts action" in r["error"]
