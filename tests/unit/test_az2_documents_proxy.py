"""AZ2 (#837) — the documents proxy dispatch/forward routing.

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

HANDLER = Path(__file__).resolve().parents[2] / "a0-applicant/api/documents.py"


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

    spec = importlib.util.spec_from_file_location("_az2_documents", HANDLER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestDocumentsProxy:
    """Hermetic dispatch tests for the documents proxy."""

    def test_list_forwards_get(self, mod):
        seen = {}

        def fake(method, path, body=None, timeout=10):
            seen.update(method=method, path=path)
            return {"ok": True, "status": 200, "data": {}}

        with patch.object(mod, "_forward", fake):
            r = mod.dispatch({"action": "list", "application_id": "app1"})
        assert seen["method"] == "GET"
        assert seen["path"] == "/api/documents/applications/app1"

    def test_provenance_forwards_get(self, mod):
        seen = {}

        def fake(method, path, body=None, timeout=10):
            seen.update(method=method, path=path)
            return {"ok": True, "status": 200, "data": {}}

        with patch.object(mod, "_forward", fake):
            r = mod.dispatch({"action": "provenance", "document_id": "doc1"})
        assert seen["method"] == "GET"
        assert seen["path"] == "/api/documents/doc1/provenance"

    def test_approve_forwards_post(self, mod):
        seen = {}

        def fake(method, path, body=None, timeout=10):
            seen.update(method=method, path=path)
            return {"ok": True, "status": 200, "data": {}}

        with patch.object(mod, "_forward", fake):
            r = mod.dispatch({"action": "approve", "document_id": "doc1"})
        assert seen["method"] == "POST"
        assert seen["path"] == "/api/documents/doc1/approve"

    def test_decline_forwards_post(self, mod):
        seen = {}

        def fake(method, path, body=None, timeout=10):
            seen.update(method=method, path=path)
            return {"ok": True, "status": 200, "data": {}}

        with patch.object(mod, "_forward", fake):
            r = mod.dispatch({"action": "decline", "document_id": "doc1"})
        assert seen["method"] == "POST"
        assert seen["path"] == "/api/documents/doc1/decline"

    def test_redline_forwards_post(self, mod):
        seen = {}

        def fake(method, path, body=None, timeout=10):
            seen.update(method=method, path=path, body=body)
            return {"ok": True, "status": 200, "data": {}}

        with patch.object(mod, "_forward", fake):
            r = mod.dispatch({
                "action": "redline",
                "variant_id": "v1",
                "base_source": "old",
                "new_source": "new",
            })
        assert seen["method"] == "POST"
        assert seen["path"] == "/api/documents/redline"
        assert seen["body"]["variant_id"] == "v1"
        assert seen["body"]["base_source"] == "old"
        assert seen["body"]["new_source"] == "new"

    def test_snapshot_forwards_get(self, mod):
        seen = {}

        def fake(method, path, body=None, timeout=10):
            seen.update(method=method, path=path)
            return {"ok": True, "status": 200, "data": {}}

        with patch.object(mod, "_forward", fake):
            r = mod.dispatch({"action": "snapshot", "application_id": "app1"})
        assert seen["method"] == "GET"
        assert seen["path"] == "/api/outcomes/applications/app1/snapshot"

    def test_list_missing_application_id_400(self, mod):
        r = mod.dispatch({"action": "list"})
        assert r["ok"] is False
        assert r["status"] == 400
        assert "application_id required" in r["error"]

    def test_snapshot_missing_application_id_400(self, mod):
        r = mod.dispatch({"action": "snapshot"})
        assert r["ok"] is False
        assert r["status"] == 400
        assert "application_id required" in r["error"]

    def test_provenance_missing_document_id_400(self, mod):
        r = mod.dispatch({"action": "provenance"})
        assert r["ok"] is False
        assert r["status"] == 400
        assert "document_id required" in r["error"]

    def test_approve_missing_document_id_400(self, mod):
        r = mod.dispatch({"action": "approve"})
        assert r["ok"] is False
        assert r["status"] == 400
        assert "document_id required" in r["error"]

    def test_decline_missing_document_id_400(self, mod):
        r = mod.dispatch({"action": "decline"})
        assert r["ok"] is False
        assert r["status"] == 400
        assert "document_id required" in r["error"]

    def test_default_action_is_list(self, mod):
        seen = {}

        def fake(method, path, body=None, timeout=10):
            seen.update(method=method, path=path)
            return {"ok": True, "status": 200, "data": {}}

        with patch.object(mod, "_forward", fake):
            r = mod.dispatch({"action": "", "application_id": "a1"})
        assert seen["method"] == "GET"
        assert seen["path"] == "/api/documents/applications/a1"

    def test_unknown_action_rejected(self, mod):
        r = mod.dispatch({"action": "zoom"})
        assert r["ok"] is False
        assert r["status"] == 400
        assert "unknown documents action" in r["error"]
