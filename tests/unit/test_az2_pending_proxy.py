"""AZ2 (#833-#838) — the pending-actions proxy dispatch/forward routing.

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

HANDLER = Path(__file__).resolve().parents[2] / "a0-applicant/api/pending.py"


@pytest.fixture()
def pend():
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

    spec = importlib.util.spec_from_file_location("_az2_pend", HANDLER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_list_forwards_get_with_campaign(pend):
    seen = {}

    def fake(method, path, body=None, timeout=10):
        seen.update(method=method, path=path)
        return {"ok": True, "status": 200, "data": {"items": []}}

    with patch.object(pend, "_forward", fake):
        r = pend.dispatch({"campaign_id": "c1", "action": "list", "include_snoozed": True})
    assert seen == {"method": "GET", "path": "/api/pending-actions/c1?include_snoozed=true"}
    assert r["data"]["items"] == []


def test_list_defaults_to_system_campaign(pend):
    seen = {}

    def fake(method, path, body=None, timeout=10):
        seen.update(method=method, path=path)
        return {"ok": True, "status": 200, "data": {"items": []}}

    with patch.object(pend, "_forward", fake):
        pend.dispatch({"action": "list"})
    assert seen["path"] == "/api/pending-actions/__system__?include_snoozed=false"


def test_count_forwards_get(pend):
    seen = {}

    def fake(method, path, body=None, timeout=10):
        seen.update(method=method, path=path)
        return {"ok": True, "status": 200, "data": {"count": 3}}

    with patch.object(pend, "_forward", fake):
        r = pend.dispatch({"campaign_id": "c2", "action": "count"})
    assert seen == {"method": "GET", "path": "/api/pending-actions/c2/count"}
    assert r["data"]["count"] == 3


def test_resolve_forwards_post(pend):
    seen = {}

    def fake(method, path, body=None, timeout=10):
        seen.update(method=method, path=path, body=body)
        return {"ok": True, "status": 204}

    with patch.object(pend, "_forward", fake):
        pend.dispatch({"campaign_id": "c1", "action": "resolve", "action_id": "a1"})
    assert seen["method"] == "POST"
    assert seen["path"] == "/api/pending-actions/a1/resolve"
    # When apply is absent, body is None because {} is falsy
    assert seen["body"] is None


def test_resolve_with_apply_forwards_post_with_body(pend):
    seen = {}

    def fake(method, path, body=None, timeout=10):
        seen.update(method=method, path=path, body=body)
        return {"ok": True, "status": 204}

    with patch.object(pend, "_forward", fake):
        pend.dispatch({"campaign_id": "c1", "action": "resolve", "action_id": "a1", "apply": True})
    assert seen["method"] == "POST"
    assert seen["path"] == "/api/pending-actions/a1/resolve"
    assert seen["body"] == {"apply": True}


def test_snooze_hours_forwards_post(pend):
    seen = {}

    def fake(method, path, body=None, timeout=10):
        seen.update(method=method, path=path, body=body)
        return {"ok": True, "status": 200, "data": {}}

    with patch.object(pend, "_forward", fake):
        pend.dispatch({"campaign_id": "c1", "action": "snooze", "action_id": "a1", "hours": 24})
    assert seen["method"] == "POST"
    assert seen["path"] == "/api/pending-actions/a1/snooze"
    assert seen["body"] == {"hours": 24}


def test_snooze_until_forwards_post(pend):
    seen = {}

    def fake(method, path, body=None, timeout=10):
        seen.update(method=method, path=path, body=body)
        return {"ok": True, "status": 200, "data": {}}

    with patch.object(pend, "_forward", fake):
        pend.dispatch({"campaign_id": "c1", "action": "snooze", "action_id": "a1", "until": "2025-01-01T00:00:00Z"})
    assert seen["method"] == "POST"
    assert seen["path"] == "/api/pending-actions/a1/snooze"
    assert seen["body"] == {"until": "2025-01-01T00:00:00Z"}


def test_resolve_bulk_forwards_post(pend):
    seen = {}

    def fake(method, path, body=None, timeout=10):
        seen.update(method=method, path=path, body=body)
        return {"ok": True, "status": 200, "data": {}}

    with patch.object(pend, "_forward", fake):
        pend.dispatch({"campaign_id": "c1", "action": "resolve_bulk", "action_ids": ["a1", "a2"]})
    assert seen["method"] == "POST"
    assert seen["path"] == "/api/pending-actions/c1/resolve-bulk"
    assert seen["body"] == {"action_ids": ["a1", "a2"]}


def test_unknown_action_is_rejected(pend):
    r = pend.dispatch({"action": "delete_everything"})
    assert r["ok"] is False and r["status"] == 400


def test_defaults_to_system_campaign_and_returns_unknown_when_no_action(pend):
    r = pend.dispatch({})
    assert r["ok"] is False and r["status"] == 400
