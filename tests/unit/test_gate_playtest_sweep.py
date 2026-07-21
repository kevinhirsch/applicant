"""Contract sweep over ALL a0-applicant API proxy dispatch() handlers.

For each proxy: stub helpers.api and flask, load the module via importlib,
patch _forward, then exercise dispatch() for every documented action.
Monkey-tests ensure unknown / garbage input never crashes.
"""
from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path
from unittest.mock import patch

import pytest

HANDLER_DIR = Path(__file__).resolve().parents[2] / "a0-applicant/api"


def _assert_safe_envelope(r):
    """Assert the response is a well-formed envelope with a 2xx/4xx status (or 0)."""
    assert isinstance(r, dict), f"dispatch returned non-dict: {r!r}"
    assert "ok" in r, f"missing ok: {r!r}"
    assert "status" in r, f"missing status: {r!r}"
    assert isinstance(r["status"], int), f"status not int: {r!r}"
    assert r["status"] == 0 or 200 <= r["status"] < 500, f"Unexpected status {r['status']}: {r!r}"


def _stub_modules():
    """Set up stubs for helpers.api and flask so any proxy module can load."""
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


def _assert_safe_envelope(r, label=""):
    """Assert the response is a well-formed envelope with a non-5xx status.

    Accepts 0 (no-status-yet) and any 2xx/4xx code (e.g. 409 onboarding).
    Rejects 5xx (>= 500) and non-integer statuses.
    """
    assert isinstance(r, dict), f"{label}did not return dict: {r!r}"
    assert "ok" in r, f"{label}missing ok: {r!r}"
    assert "status" in r, f"{label}missing status: {r!r}"
    assert isinstance(r["status"], int), f"{label}status not int: {r!r}"
    s = r["status"]
    assert s == 0 or 200 <= s < 500, f"{label}Unexpected status {s}: {r!r}"


# ── agent_runs proxy ────────────────────────────────────────────────────


@pytest.fixture()
def mod_agent_runs():
    _stub_modules()
    handler = HANDLER_DIR / "agent_runs.py"
    spec = importlib.util.spec_from_file_location(
        "_sweep_agent_runs", handler)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_agent_runs_status(mod_agent_runs):
    seen = {}

    def fake(method, path, body=None, timeout=10):
        seen["called"] = True
        return {"ok": True, "status": 200, "data": {}}

    with patch.object(mod_agent_runs, "_forward", fake):
        r = mod_agent_runs.dispatch({
        'action': 'status',
        'campaign_id': 'c1'
    })
    assert seen.get("called"), "dispatch did not call _forward"
    assert isinstance(r, dict), f"dispatch returned non-dict: {r!r}"


def test_agent_runs_intent(mod_agent_runs):
    seen = {}

    def fake(method, path, body=None, timeout=10):
        seen["called"] = True
        return {"ok": True, "status": 200, "data": {}}

    with patch.object(mod_agent_runs, "_forward", fake):
        r = mod_agent_runs.dispatch({
        'action': 'intent',
        'campaign_id': 'c1'
    })
    assert seen.get("called"), "dispatch did not call _forward"
    assert isinstance(r, dict), f"dispatch returned non-dict: {r!r}"


def test_agent_runs_list(mod_agent_runs):
    seen = {}

    def fake(method, path, body=None, timeout=10):
        seen["called"] = True
        return {"ok": True, "status": 200, "data": {}}

    with patch.object(mod_agent_runs, "_forward", fake):
        r = mod_agent_runs.dispatch({
        'action': 'list',
        'campaign_id': 'c1'
    })
    assert seen.get("called"), "dispatch did not call _forward"
    assert isinstance(r, dict), f"dispatch returned non-dict: {r!r}"


def test_agent_runs_run(mod_agent_runs):
    seen = {}

    def fake(method, path, body=None, timeout=10):
        seen["called"] = True
        return {"ok": True, "status": 200, "data": {}}

    with patch.object(mod_agent_runs, "_forward", fake):
        r = mod_agent_runs.dispatch({
        'action': 'run',
        'campaign_id': 'c1'
    })
    assert seen.get("called"), "dispatch did not call _forward"
    assert isinstance(r, dict), f"dispatch returned non-dict: {r!r}"


def test_agent_runs_pause(mod_agent_runs):
    seen = {}

    def fake(method, path, body=None, timeout=10):
        seen["called"] = True
        return {"ok": True, "status": 200, "data": {}}

    with patch.object(mod_agent_runs, "_forward", fake):
        r = mod_agent_runs.dispatch({
        'action': 'pause',
        'campaign_id': 'c1'
    })
    assert seen.get("called"), "dispatch did not call _forward"
    assert isinstance(r, dict), f"dispatch returned non-dict: {r!r}"


def test_agent_runs_resume(mod_agent_runs):
    seen = {}

    def fake(method, path, body=None, timeout=10):
        seen["called"] = True
        return {"ok": True, "status": 200, "data": {}}

    with patch.object(mod_agent_runs, "_forward", fake):
        r = mod_agent_runs.dispatch({
        'action': 'resume',
        'campaign_id': 'c1'
    })
    assert seen.get("called"), "dispatch did not call _forward"
    assert isinstance(r, dict), f"dispatch returned non-dict: {r!r}"


def test_agent_runs_monkey_unknown_action(mod_agent_runs):
    r = mod_agent_runs.dispatch({"action": "nuke_galaxy_from_orbit"})
    assert r.get("ok") is False, f"Expected ok=False, got {r!r}"
    assert r.get("status") == 400, f"Expected status=400, got {r!r}"

def test_agent_runs_monkey_garbage_input(mod_agent_runs):
    for bad in [
        {},
        {"action": ""},
        {"action": None},
        {"action": 123},
        {"action": "a" * 1000},
    ]:
        r = mod_agent_runs.dispatch(bad)
        assert isinstance(r, dict), f"dispatch({bad!r}) did not return dict: {r!r}"
        assert "ok" in r, f"dispatch({bad!r}) missing ok: {r!r}"
        assert "status" in r, f"dispatch({bad!r}) missing status: {r!r}"
        _assert_safe_envelope(r)


# ── attributes proxy ────────────────────────────────────────────────────


@pytest.fixture()
def mod_attributes():
    _stub_modules()
    handler = HANDLER_DIR / "attributes.py"
    spec = importlib.util.spec_from_file_location(
        "_sweep_attributes", handler)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_attributes_list(mod_attributes):
    seen = {}

    def fake(method, path, body=None, timeout=10):
        seen["called"] = True
        return {"ok": True, "status": 200, "data": {}}

    with patch.object(mod_attributes, "_forward", fake):
        r = mod_attributes.dispatch({
        'action': 'list',
        'campaign_id': 'c1'
    })
    assert seen.get("called"), "dispatch did not call _forward"
    assert isinstance(r, dict), f"dispatch returned non-dict: {r!r}"


def test_attributes_add(mod_attributes):
    seen = {}

    def fake(method, path, body=None, timeout=10):
        seen["called"] = True
        return {"ok": True, "status": 200, "data": {}}

    with patch.object(mod_attributes, "_forward", fake):
        r = mod_attributes.dispatch({
        'action': 'add',
        'campaign_id': 'c1',
        'name': 'attr1',
        'value': 'val1'
    })
    assert seen.get("called"), "dispatch did not call _forward"
    assert isinstance(r, dict), f"dispatch returned non-dict: {r!r}"


def test_attributes_delete(mod_attributes):
    seen = {}

    def fake(method, path, body=None, timeout=10):
        seen["called"] = True
        return {"ok": True, "status": 200, "data": {}}

    with patch.object(mod_attributes, "_forward", fake):
        r = mod_attributes.dispatch({
        'action': 'delete',
        'campaign_id': 'c1',
        'attribute_id': 'attr1'
    })
    assert seen.get("called"), "dispatch did not call _forward"
    assert isinstance(r, dict), f"dispatch returned non-dict: {r!r}"


def test_attributes_monkey_unknown_action(mod_attributes):
    r = mod_attributes.dispatch({"action": "nuke_galaxy_from_orbit"})
    assert r.get("ok") is False, f"Expected ok=False, got {r!r}"
    assert r.get("status") == 400, f"Expected status=400, got {r!r}"

def test_attributes_monkey_garbage_input(mod_attributes):
    for bad in [
        {},
        {"action": ""},
        {"action": None},
        {"action": 123},
        {"action": "a" * 1000},
    ]:
        r = mod_attributes.dispatch(bad)
        assert isinstance(r, dict), f"dispatch({bad!r}) did not return dict: {r!r}"
        assert "ok" in r, f"dispatch({bad!r}) missing ok: {r!r}"
        assert "status" in r, f"dispatch({bad!r}) missing status: {r!r}"
        _assert_safe_envelope(r)


# ── audit proxy ────────────────────────────────────────────────────


@pytest.fixture()
def mod_audit():
    _stub_modules()
    handler = HANDLER_DIR / "audit.py"
    spec = importlib.util.spec_from_file_location(
        "_sweep_audit", handler)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_audit_log(mod_audit):
    seen = {}

    def fake(method, path, body=None, timeout=10):
        seen["called"] = True
        return {"ok": True, "status": 200, "data": {}}

    with patch.object(mod_audit, "_forward", fake):
        r = mod_audit.dispatch({
        'action': 'log',
        'campaign_id': 'c1'
    })
    assert seen.get("called"), "dispatch did not call _forward"
    assert isinstance(r, dict), f"dispatch returned non-dict: {r!r}"


def test_audit_application_log(mod_audit):
    seen = {}

    def fake(method, path, body=None, timeout=10):
        seen["called"] = True
        return {"ok": True, "status": 200, "data": {}}

    with patch.object(mod_audit, "_forward", fake):
        r = mod_audit.dispatch({
        'action': 'application_log',
        'campaign_id': 'c1',
        'application_id': 'a1'
    })
    assert seen.get("called"), "dispatch did not call _forward"
    assert isinstance(r, dict), f"dispatch returned non-dict: {r!r}"


def test_audit_monkey_unknown_action(mod_audit):
    r = mod_audit.dispatch({"action": "nuke_galaxy_from_orbit"})
    assert r.get("ok") is False, f"Expected ok=False, got {r!r}"
    assert r.get("status") == 400, f"Expected status=400, got {r!r}"

def test_audit_monkey_garbage_input(mod_audit):
    for bad in [
        {},
        {"action": ""},
        {"action": None},
        {"action": 123},
        {"action": "a" * 1000},
    ]:
        r = mod_audit.dispatch(bad)
        assert isinstance(r, dict), f"dispatch({bad!r}) did not return dict: {r!r}"
        assert "ok" in r, f"dispatch({bad!r}) missing ok: {r!r}"
        assert "status" in r, f"dispatch({bad!r}) missing status: {r!r}"
        _assert_safe_envelope(r)


# ── campaigns proxy ────────────────────────────────────────────────────


@pytest.fixture()
def mod_campaigns():
    _stub_modules()
    handler = HANDLER_DIR / "campaigns.py"
    spec = importlib.util.spec_from_file_location(
        "_sweep_campaigns", handler)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_campaigns_list(mod_campaigns):
    seen = {}

    def fake(method, path, body=None, timeout=10):
        seen["called"] = True
        return {"ok": True, "status": 200, "data": {}}

    with patch.object(mod_campaigns, "_forward", fake):
        r = mod_campaigns.dispatch({
        'action': 'list',
        'campaign_id': 'c1'
    })
    assert seen.get("called"), "dispatch did not call _forward"
    assert isinstance(r, dict), f"dispatch returned non-dict: {r!r}"


def test_campaigns_create(mod_campaigns):
    seen = {}

    def fake(method, path, body=None, timeout=10):
        seen["called"] = True
        return {"ok": True, "status": 200, "data": {}}

    with patch.object(mod_campaigns, "_forward", fake):
        r = mod_campaigns.dispatch({
        'action': 'create',
        'campaign_id': 'c1'
    })
    assert seen.get("called"), "dispatch did not call _forward"
    assert isinstance(r, dict), f"dispatch returned non-dict: {r!r}"


def test_campaigns_update(mod_campaigns):
    seen = {}

    def fake(method, path, body=None, timeout=10):
        seen["called"] = True
        return {"ok": True, "status": 200, "data": {}}

    with patch.object(mod_campaigns, "_forward", fake):
        r = mod_campaigns.dispatch({
        'action': 'update',
        'campaign_id': 'c1',
        'name': 'newname'
    })
    assert seen.get("called"), "dispatch did not call _forward"
    assert isinstance(r, dict), f"dispatch returned non-dict: {r!r}"


def test_campaigns_clone(mod_campaigns):
    seen = {}

    def fake(method, path, body=None, timeout=10):
        seen["called"] = True
        return {"ok": True, "status": 200, "data": {}}

    with patch.object(mod_campaigns, "_forward", fake):
        r = mod_campaigns.dispatch({
        'action': 'clone',
        'campaign_id': 'c1',
        'name': 'clone'
    })
    assert seen.get("called"), "dispatch did not call _forward"
    assert isinstance(r, dict), f"dispatch returned non-dict: {r!r}"


def test_campaigns_guardrails(mod_campaigns):
    seen = {}

    def fake(method, path, body=None, timeout=10):
        seen["called"] = True
        return {"ok": True, "status": 200, "data": {}}

    with patch.object(mod_campaigns, "_forward", fake):
        r = mod_campaigns.dispatch({
        'action': 'guardrails',
        'campaign_id': 'c1'
    })
    assert seen.get("called"), "dispatch did not call _forward"
    assert isinstance(r, dict), f"dispatch returned non-dict: {r!r}"


def test_campaigns_monkey_unknown_action(mod_campaigns):
    r = mod_campaigns.dispatch({"action": "nuke_galaxy_from_orbit"})
    assert r.get("ok") is False, f"Expected ok=False, got {r!r}"
    assert r.get("status") == 400, f"Expected status=400, got {r!r}"

def test_campaigns_monkey_garbage_input(mod_campaigns):
    for bad in [
        {},
        {"action": ""},
        {"action": None},
        {"action": 123},
        {"action": "a" * 1000},
    ]:
        r = mod_campaigns.dispatch(bad)
        assert isinstance(r, dict), f"dispatch({bad!r}) did not return dict: {r!r}"
        assert "ok" in r, f"dispatch({bad!r}) missing ok: {r!r}"
        assert "status" in r, f"dispatch({bad!r}) missing status: {r!r}"
        _assert_safe_envelope(r)


# ── chat proxy ────────────────────────────────────────────────────


@pytest.fixture()
def mod_chat():
    _stub_modules()
    handler = HANDLER_DIR / "chat.py"
    spec = importlib.util.spec_from_file_location(
        "_sweep_chat", handler)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_chat_send(mod_chat):
    seen = {}

    def fake(method, path, body=None, timeout=10):
        seen["called"] = True
        return {"ok": True, "status": 200, "data": {}}

    with patch.object(mod_chat, "_forward", fake):
        r = mod_chat.dispatch({
        'action': 'send',
        'campaign_id': 'c1',
        'message': 'hello'
    })
    assert seen.get("called"), "dispatch did not call _forward"
    assert isinstance(r, dict), f"dispatch returned non-dict: {r!r}"


def test_chat_confirm(mod_chat):
    seen = {}

    def fake(method, path, body=None, timeout=10):
        seen["called"] = True
        return {"ok": True, "status": 200, "data": {}}

    with patch.object(mod_chat, "_forward", fake):
        r = mod_chat.dispatch({
        'action': 'confirm',
        'campaign_id': 'c1',
        'message': 'ok'
    })
    assert seen.get("called"), "dispatch did not call _forward"
    assert isinstance(r, dict), f"dispatch returned non-dict: {r!r}"


def test_chat_confirm_criteria(mod_chat):
    seen = {}

    def fake(method, path, body=None, timeout=10):
        seen["called"] = True
        return {"ok": True, "status": 200, "data": {}}

    with patch.object(mod_chat, "_forward", fake):
        r = mod_chat.dispatch({
        'action': 'confirm_criteria',
        'campaign_id': 'c1',
        'changes': {'k': 'v'}
    })
    assert seen.get("called"), "dispatch did not call _forward"
    assert isinstance(r, dict), f"dispatch returned non-dict: {r!r}"


def test_chat_monkey_unknown_action(mod_chat):
    r = mod_chat.dispatch({"action": "nuke_galaxy_from_orbit"})
    assert r.get("ok") is False, f"Expected ok=False, got {r!r}"
    assert r.get("status") == 400, f"Expected status=400, got {r!r}"

def test_chat_monkey_garbage_input(mod_chat):
    for bad in [
        {},
        {"action": ""},
        {"action": None},
        {"action": 123},
        {"action": "a" * 1000},
    ]:
        r = mod_chat.dispatch(bad)
        assert isinstance(r, dict), f"dispatch({bad!r}) did not return dict: {r!r}"
        assert "ok" in r, f"dispatch({bad!r}) missing ok: {r!r}"
        assert "status" in r, f"dispatch({bad!r}) missing status: {r!r}"
        _assert_safe_envelope(r)


# ── compare proxy ────────────────────────────────────────────────────


@pytest.fixture()
def mod_compare():
    _stub_modules()
    handler = HANDLER_DIR / "compare.py"
    spec = importlib.util.spec_from_file_location(
        "_sweep_compare", handler)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_compare_applications(mod_compare):
    seen = {}

    def fake(method, path, body=None, timeout=10):
        seen["called"] = True
        return {"ok": True, "status": 200, "data": {}}

    with patch.object(mod_compare, "_forward", fake):
        r = mod_compare.dispatch({
        'action': 'applications',
        'ids': ['a1', 'a2']
    })
    assert seen.get("called"), "dispatch did not call _forward"
    assert isinstance(r, dict), f"dispatch returned non-dict: {r!r}"


def test_compare_postings(mod_compare):
    seen = {}

    def fake(method, path, body=None, timeout=10):
        seen["called"] = True
        return {"ok": True, "status": 200, "data": {}}

    with patch.object(mod_compare, "_forward", fake):
        r = mod_compare.dispatch({
        'action': 'postings',
        'ids': ['a1', 'a2']
    })
    assert seen.get("called"), "dispatch did not call _forward"
    assert isinstance(r, dict), f"dispatch returned non-dict: {r!r}"


def test_compare_monkey_unknown_action(mod_compare):
    r = mod_compare.dispatch({"action": "nuke_galaxy_from_orbit"})
    assert r.get("ok") is False, f"Expected ok=False, got {r!r}"
    assert r.get("status") == 400, f"Expected status=400, got {r!r}"

def test_compare_monkey_garbage_input(mod_compare):
    for bad in [
        {},
        {"action": ""},
        {"action": None},
        {"action": 123},
        {"action": "a" * 1000},
    ]:
        r = mod_compare.dispatch(bad)
        assert isinstance(r, dict), f"dispatch({bad!r}) did not return dict: {r!r}"
        assert "ok" in r, f"dispatch({bad!r}) missing ok: {r!r}"
        assert "status" in r, f"dispatch({bad!r}) missing status: {r!r}"
        _assert_safe_envelope(r)


# ── conversion proxy ────────────────────────────────────────────────────


@pytest.fixture()
def mod_conversion():
    _stub_modules()
    handler = HANDLER_DIR / "conversion.py"
    spec = importlib.util.spec_from_file_location(
        "_sweep_conversion", handler)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_conversion_engine(mod_conversion):
    seen = {}

    def fake(method, path, body=None, timeout=10):
        seen["called"] = True
        return {"ok": True, "status": 200, "data": {}}

    with patch.object(mod_conversion, "_forward", fake):
        r = mod_conversion.dispatch({
        'action': 'engine',
        'campaign_id': 'c1'
    })
    assert seen.get("called"), "dispatch did not call _forward"
    assert isinstance(r, dict), f"dispatch returned non-dict: {r!r}"


def test_conversion_preview(mod_conversion):
    seen = {}

    def fake(method, path, body=None, timeout=10):
        seen["called"] = True
        return {"ok": True, "status": 200, "data": {}}

    with patch.object(mod_conversion, "_forward", fake):
        r = mod_conversion.dispatch({
        'action': 'preview',
        'campaign_id': 'c1'
    })
    assert seen.get("called"), "dispatch did not call _forward"
    assert isinstance(r, dict), f"dispatch returned non-dict: {r!r}"


def test_conversion_accept(mod_conversion):
    seen = {}

    def fake(method, path, body=None, timeout=10):
        seen["called"] = True
        return {"ok": True, "status": 200, "data": {}}

    with patch.object(mod_conversion, "_forward", fake):
        r = mod_conversion.dispatch({
        'action': 'accept',
        'campaign_id': 'c1'
    })
    assert seen.get("called"), "dispatch did not call _forward"
    assert isinstance(r, dict), f"dispatch returned non-dict: {r!r}"


def test_conversion_reject(mod_conversion):
    seen = {}

    def fake(method, path, body=None, timeout=10):
        seen["called"] = True
        return {"ok": True, "status": 200, "data": {}}

    with patch.object(mod_conversion, "_forward", fake):
        r = mod_conversion.dispatch({
        'action': 'reject',
        'campaign_id': 'c1'
    })
    assert seen.get("called"), "dispatch did not call _forward"
    assert isinstance(r, dict), f"dispatch returned non-dict: {r!r}"


def test_conversion_monkey_unknown_action(mod_conversion):
    r = mod_conversion.dispatch({"action": "nuke_galaxy_from_orbit"})
    assert r.get("ok") is False, f"Expected ok=False, got {r!r}"
    assert r.get("status") == 400, f"Expected status=400, got {r!r}"

def test_conversion_monkey_garbage_input(mod_conversion):
    for bad in [
        {},
        {"action": ""},
        {"action": None},
        {"action": 123},
        {"action": "a" * 1000},
    ]:
        r = mod_conversion.dispatch(bad)
        assert isinstance(r, dict), f"dispatch({bad!r}) did not return dict: {r!r}"
        assert "ok" in r, f"dispatch({bad!r}) missing ok: {r!r}"
        assert "status" in r, f"dispatch({bad!r}) missing status: {r!r}"
        _assert_safe_envelope(r)


# ── criteria proxy ────────────────────────────────────────────────────


@pytest.fixture()
def mod_criteria():
    _stub_modules()
    handler = HANDLER_DIR / "criteria.py"
    spec = importlib.util.spec_from_file_location(
        "_sweep_criteria", handler)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_criteria_view(mod_criteria):
    seen = {}

    def fake(method, path, body=None, timeout=10):
        seen["called"] = True
        return {"ok": True, "status": 200, "data": {}}

    with patch.object(mod_criteria, "_forward", fake):
        r = mod_criteria.dispatch({
        'action': 'view',
        'campaign_id': 'c1'
    })
    assert seen.get("called"), "dispatch did not call _forward"
    assert isinstance(r, dict), f"dispatch returned non-dict: {r!r}"


def test_criteria_signature(mod_criteria):
    seen = {}

    def fake(method, path, body=None, timeout=10):
        seen["called"] = True
        return {"ok": True, "status": 200, "data": {}}

    with patch.object(mod_criteria, "_forward", fake):
        r = mod_criteria.dispatch({
        'action': 'signature',
        'campaign_id': 'c1'
    })
    assert seen.get("called"), "dispatch did not call _forward"
    assert isinstance(r, dict), f"dispatch returned non-dict: {r!r}"


def test_criteria_apply_learned(mod_criteria):
    seen = {}

    def fake(method, path, body=None, timeout=10):
        seen["called"] = True
        return {"ok": True, "status": 200, "data": {}}

    with patch.object(mod_criteria, "_forward", fake):
        r = mod_criteria.dispatch({
        'action': 'apply_learned',
        'campaign_id': 'c1',
        'adjustment': 'adj1',
        'rationale': 'test'
    })
    assert seen.get("called"), "dispatch did not call _forward"
    assert isinstance(r, dict), f"dispatch returned non-dict: {r!r}"


def test_criteria_monkey_unknown_action(mod_criteria):
    r = mod_criteria.dispatch({"action": "nuke_galaxy_from_orbit"})
    assert r.get("ok") is False, f"Expected ok=False, got {r!r}"
    assert r.get("status") == 400, f"Expected status=400, got {r!r}"

def test_criteria_monkey_garbage_input(mod_criteria):
    for bad in [
        {},
        {"action": ""},
        {"action": None},
        {"action": 123},
        {"action": "a" * 1000},
    ]:
        r = mod_criteria.dispatch(bad)
        assert isinstance(r, dict), f"dispatch({bad!r}) did not return dict: {r!r}"
        assert "ok" in r, f"dispatch({bad!r}) missing ok: {r!r}"
        assert "status" in r, f"dispatch({bad!r}) missing status: {r!r}"
        _assert_safe_envelope(r)


# ── digest proxy ────────────────────────────────────────────────────


@pytest.fixture()
def mod_digest():
    _stub_modules()
    handler = HANDLER_DIR / "digest.py"
    spec = importlib.util.spec_from_file_location(
        "_sweep_digest", handler)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_digest_get(mod_digest):
    seen = {}

    def fake(method, path, body=None, timeout=10):
        seen["called"] = True
        return {"ok": True, "status": 200, "data": {}}

    with patch.object(mod_digest, "_forward", fake):
        r = mod_digest.dispatch({
        'action': 'get',
        'campaign_id': 'c1'
    })
    assert seen.get("called"), "dispatch did not call _forward"
    assert isinstance(r, dict), f"dispatch returned non-dict: {r!r}"


def test_digest_recap(mod_digest):
    seen = {}

    def fake(method, path, body=None, timeout=10):
        seen["called"] = True
        return {"ok": True, "status": 200, "data": {}}

    with patch.object(mod_digest, "_forward", fake):
        r = mod_digest.dispatch({
        'action': 'recap',
        'campaign_id': 'c1'
    })
    assert seen.get("called"), "dispatch did not call _forward"
    assert isinstance(r, dict), f"dispatch returned non-dict: {r!r}"


def test_digest_approve(mod_digest):
    seen = {}

    def fake(method, path, body=None, timeout=10):
        seen["called"] = True
        return {"ok": True, "status": 200, "data": {}}

    with patch.object(mod_digest, "_forward", fake):
        r = mod_digest.dispatch({
        'action': 'approve',
        'campaign_id': 'c1',
        'application_id': 'a1'
    })
    assert seen.get("called"), "dispatch did not call _forward"
    assert isinstance(r, dict), f"dispatch returned non-dict: {r!r}"


def test_digest_decline(mod_digest):
    seen = {}

    def fake(method, path, body=None, timeout=10):
        seen["called"] = True
        return {"ok": True, "status": 200, "data": {}}

    with patch.object(mod_digest, "_forward", fake):
        r = mod_digest.dispatch({
        'action': 'decline',
        'campaign_id': 'c1',
        'application_id': 'a1'
    })
    assert seen.get("called"), "dispatch did not call _forward"
    assert isinstance(r, dict), f"dispatch returned non-dict: {r!r}"


def test_digest_monkey_unknown_action(mod_digest):
    r = mod_digest.dispatch({"action": "nuke_galaxy_from_orbit"})
    assert r.get("ok") is False, f"Expected ok=False, got {r!r}"
    assert r.get("status") == 400, f"Expected status=400, got {r!r}"

def test_digest_monkey_garbage_input(mod_digest):
    for bad in [
        {},
        {"action": ""},
        {"action": None},
        {"action": 123},
        {"action": "a" * 1000},
    ]:
        r = mod_digest.dispatch(bad)
        assert isinstance(r, dict), f"dispatch({bad!r}) did not return dict: {r!r}"
        assert "ok" in r, f"dispatch({bad!r}) missing ok: {r!r}"
        assert "status" in r, f"dispatch({bad!r}) missing status: {r!r}"
        _assert_safe_envelope(r)


# ── discovery proxy ────────────────────────────────────────────────────


@pytest.fixture()
def mod_discovery():
    _stub_modules()
    handler = HANDLER_DIR / "discovery.py"
    spec = importlib.util.spec_from_file_location(
        "_sweep_discovery", handler)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_discovery_list(mod_discovery):
    seen = {}

    def fake(method, path, body=None, timeout=10):
        seen["called"] = True
        return {"ok": True, "status": 200, "data": {}}

    with patch.object(mod_discovery, "_forward", fake):
        r = mod_discovery.dispatch({
        'action': 'list',
        'campaign_id': 'c1'
    })
    assert seen.get("called"), "dispatch did not call _forward"
    assert isinstance(r, dict), f"dispatch returned non-dict: {r!r}"


def test_discovery_set(mod_discovery):
    seen = {}

    def fake(method, path, body=None, timeout=10):
        seen["called"] = True
        return {"ok": True, "status": 200, "data": {}}

    with patch.object(mod_discovery, "_forward", fake):
        r = mod_discovery.dispatch({
        'action': 'set',
        'campaign_id': 'c1',
        'source_key': 'src1'
    })
    assert seen.get("called"), "dispatch did not call _forward"
    assert isinstance(r, dict), f"dispatch returned non-dict: {r!r}"


def test_discovery_monkey_unknown_action(mod_discovery):
    r = mod_discovery.dispatch({"action": "nuke_galaxy_from_orbit"})
    assert r.get("ok") is False, f"Expected ok=False, got {r!r}"
    assert r.get("status") == 400, f"Expected status=400, got {r!r}"

def test_discovery_monkey_garbage_input(mod_discovery):
    for bad in [
        {},
        {"action": ""},
        {"action": None},
        {"action": 123},
        {"action": "a" * 1000},
    ]:
        r = mod_discovery.dispatch(bad)
        assert isinstance(r, dict), f"dispatch({bad!r}) did not return dict: {r!r}"
        assert "ok" in r, f"dispatch({bad!r}) missing ok: {r!r}"
        assert "status" in r, f"dispatch({bad!r}) missing status: {r!r}"
        _assert_safe_envelope(r)


# ── documents proxy ────────────────────────────────────────────────────


@pytest.fixture()
def mod_documents():
    _stub_modules()
    handler = HANDLER_DIR / "documents.py"
    spec = importlib.util.spec_from_file_location(
        "_sweep_documents", handler)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_documents_list(mod_documents):
    seen = {}

    def fake(method, path, body=None, timeout=10):
        seen["called"] = True
        return {"ok": True, "status": 200, "data": {}}

    with patch.object(mod_documents, "_forward", fake):
        r = mod_documents.dispatch({
        'action': 'list',
        'application_id': 'a1'
    })
    assert seen.get("called"), "dispatch did not call _forward"
    assert isinstance(r, dict), f"dispatch returned non-dict: {r!r}"


def test_documents_provenance(mod_documents):
    seen = {}

    def fake(method, path, body=None, timeout=10):
        seen["called"] = True
        return {"ok": True, "status": 200, "data": {}}

    with patch.object(mod_documents, "_forward", fake):
        r = mod_documents.dispatch({
        'action': 'provenance',
        'application_id': 'a1',
        'document_id': 'd1'
    })
    assert seen.get("called"), "dispatch did not call _forward"
    assert isinstance(r, dict), f"dispatch returned non-dict: {r!r}"


def test_documents_approve(mod_documents):
    seen = {}

    def fake(method, path, body=None, timeout=10):
        seen["called"] = True
        return {"ok": True, "status": 200, "data": {}}

    with patch.object(mod_documents, "_forward", fake):
        r = mod_documents.dispatch({
        'action': 'approve',
        'document_id': 'd1'
    })
    assert seen.get("called"), "dispatch did not call _forward"
    assert isinstance(r, dict), f"dispatch returned non-dict: {r!r}"


def test_documents_decline(mod_documents):
    seen = {}

    def fake(method, path, body=None, timeout=10):
        seen["called"] = True
        return {"ok": True, "status": 200, "data": {}}

    with patch.object(mod_documents, "_forward", fake):
        r = mod_documents.dispatch({
        'action': 'decline',
        'document_id': 'd1'
    })
    assert seen.get("called"), "dispatch did not call _forward"
    assert isinstance(r, dict), f"dispatch returned non-dict: {r!r}"


def test_documents_redline(mod_documents):
    seen = {}

    def fake(method, path, body=None, timeout=10):
        seen["called"] = True
        return {"ok": True, "status": 200, "data": {}}

    with patch.object(mod_documents, "_forward", fake):
        r = mod_documents.dispatch({
        'action': 'redline',
        'application_id': 'a1'
    })
    assert seen.get("called"), "dispatch did not call _forward"
    assert isinstance(r, dict), f"dispatch returned non-dict: {r!r}"


def test_documents_snapshot(mod_documents):
    seen = {}

    def fake(method, path, body=None, timeout=10):
        seen["called"] = True
        return {"ok": True, "status": 200, "data": {}}

    with patch.object(mod_documents, "_forward", fake):
        r = mod_documents.dispatch({
        'action': 'snapshot',
        'application_id': 'a1'
    })
    assert seen.get("called"), "dispatch did not call _forward"
    assert isinstance(r, dict), f"dispatch returned non-dict: {r!r}"


def test_documents_monkey_unknown_action(mod_documents):
    r = mod_documents.dispatch({"action": "nuke_galaxy_from_orbit"})
    assert r.get("ok") is False, f"Expected ok=False, got {r!r}"
    assert r.get("status") == 400, f"Expected status=400, got {r!r}"

def test_documents_monkey_garbage_input(mod_documents):
    for bad in [
        {},
        {"action": ""},
        {"action": None},
        {"action": 123},
        {"action": "a" * 1000},
    ]:
        r = mod_documents.dispatch(bad)
        assert isinstance(r, dict), f"dispatch({bad!r}) did not return dict: {r!r}"
        assert "ok" in r, f"dispatch({bad!r}) missing ok: {r!r}"
        assert "status" in r, f"dispatch({bad!r}) missing status: {r!r}"
        _assert_safe_envelope(r)


# ── dormant proxy ────────────────────────────────────────────────────


@pytest.fixture()
def mod_dormant():
    _stub_modules()
    handler = HANDLER_DIR / "dormant.py"
    spec = importlib.util.spec_from_file_location(
        "_sweep_dormant", handler)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_dormant_list(mod_dormant):
    seen = {}

    def fake(method, path, body=None, timeout=10):
        seen["called"] = True
        return {"ok": True, "status": 200, "data": {}}

    with patch.object(mod_dormant, "_forward", fake):
        r = mod_dormant.dispatch({
        'action': 'list'
    })
    assert seen.get("called"), "dispatch did not call _forward"
    assert isinstance(r, dict), f"dispatch returned non-dict: {r!r}"


def test_dormant_monkey_unknown_action(mod_dormant):
    r = mod_dormant.dispatch({"action": "nuke_galaxy_from_orbit"})
    assert r.get("ok") is False, f"Expected ok=False, got {r!r}"
    assert r.get("status") == 400, f"Expected status=400, got {r!r}"

def test_dormant_monkey_garbage_input(mod_dormant):
    for bad in [
        {},
        {"action": ""},
        {"action": None},
        {"action": 123},
        {"action": "a" * 1000},
    ]:
        r = mod_dormant.dispatch(bad)
        assert isinstance(r, dict), f"dispatch({bad!r}) did not return dict: {r!r}"
        assert "ok" in r, f"dispatch({bad!r}) missing ok: {r!r}"
        assert "status" in r, f"dispatch({bad!r}) missing status: {r!r}"
        _assert_safe_envelope(r)


# ── easy_apply proxy ────────────────────────────────────────────────────


@pytest.fixture()
def mod_easy_apply():
    _stub_modules()
    handler = HANDLER_DIR / "easy_apply.py"
    spec = importlib.util.spec_from_file_location(
        "_sweep_easy_apply", handler)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_easy_apply_status(mod_easy_apply):
    seen = {}

    def fake(method, path, body=None, timeout=10):
        seen["called"] = True
        return {"ok": True, "status": 200, "data": {}}

    with patch.object(mod_easy_apply, "_forward", fake):
        r = mod_easy_apply.dispatch({
        'action': 'status',
        'campaign_id': 'c1',
        'posting_id': 'p1'
    })
    assert seen.get("called"), "dispatch did not call _forward"
    assert isinstance(r, dict), f"dispatch returned non-dict: {r!r}"


def test_easy_apply_monkey_unknown_action(mod_easy_apply):
    r = mod_easy_apply.dispatch({"action": "nuke_galaxy_from_orbit"})
    assert r.get("ok") is False, f"Expected ok=False, got {r!r}"
    assert r.get("status") == 400, f"Expected status=400, got {r!r}"

def test_easy_apply_monkey_garbage_input(mod_easy_apply):
    for bad in [
        {},
        {"action": ""},
        {"action": None},
        {"action": 123},
        {"action": "a" * 1000},
    ]:
        r = mod_easy_apply.dispatch(bad)
        assert isinstance(r, dict), f"dispatch({bad!r}) did not return dict: {r!r}"
        assert "ok" in r, f"dispatch({bad!r}) missing ok: {r!r}"
        assert "status" in r, f"dispatch({bad!r}) missing status: {r!r}"
        _assert_safe_envelope(r)


# ── feedback proxy ────────────────────────────────────────────────────


@pytest.fixture()
def mod_feedback():
    _stub_modules()
    handler = HANDLER_DIR / "feedback.py"
    spec = importlib.util.spec_from_file_location(
        "_sweep_feedback", handler)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_feedback_history(mod_feedback):
    seen = {}

    def fake(method, path, body=None, timeout=10):
        seen["called"] = True
        return {"ok": True, "status": 200, "data": {}}

    with patch.object(mod_feedback, "_forward", fake):
        r = mod_feedback.dispatch({
        'action': 'history',
        'campaign_id': 'c1'
    })
    assert seen.get("called"), "dispatch did not call _forward"
    assert isinstance(r, dict), f"dispatch returned non-dict: {r!r}"


def test_feedback_freetext(mod_feedback):
    seen = {}

    def fake(method, path, body=None, timeout=10):
        seen["called"] = True
        return {"ok": True, "status": 200, "data": {}}

    with patch.object(mod_feedback, "_forward", fake):
        r = mod_feedback.dispatch({
        'action': 'freetext',
        'campaign_id': 'c1',
        'text': 'nice'
    })
    assert seen.get("called"), "dispatch did not call _forward"
    assert isinstance(r, dict), f"dispatch returned non-dict: {r!r}"


def test_feedback_survey(mod_feedback):
    seen = {}

    def fake(method, path, body=None, timeout=10):
        seen["called"] = True
        return {"ok": True, "status": 200, "data": {}}

    with patch.object(mod_feedback, "_forward", fake):
        r = mod_feedback.dispatch({
        'action': 'survey',
        'campaign_id': 'c1',
        'answers': {'q1': 'yes'}
    })
    assert seen.get("called"), "dispatch did not call _forward"
    assert isinstance(r, dict), f"dispatch returned non-dict: {r!r}"


def test_feedback_monkey_unknown_action(mod_feedback):
    r = mod_feedback.dispatch({"action": "nuke_galaxy_from_orbit"})
    assert r.get("ok") is False, f"Expected ok=False, got {r!r}"
    assert r.get("status") == 400, f"Expected status=400, got {r!r}"

def test_feedback_monkey_garbage_input(mod_feedback):
    for bad in [
        {},
        {"action": ""},
        {"action": None},
        {"action": 123},
        {"action": "a" * 1000},
    ]:
        r = mod_feedback.dispatch(bad)
        assert isinstance(r, dict), f"dispatch({bad!r}) did not return dict: {r!r}"
        assert "ok" in r, f"dispatch({bad!r}) missing ok: {r!r}"
        assert "status" in r, f"dispatch({bad!r}) missing status: {r!r}"
        _assert_safe_envelope(r)


# ── fonts proxy ────────────────────────────────────────────────────


@pytest.fixture()
def mod_fonts():
    _stub_modules()
    handler = HANDLER_DIR / "fonts.py"
    spec = importlib.util.spec_from_file_location(
        "_sweep_fonts", handler)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_fonts_list(mod_fonts):
    seen = {}

    def fake(method, path, body=None, timeout=10):
        seen["called"] = True
        return {"ok": True, "status": 200, "data": {}}

    with patch.object(mod_fonts, "_forward", fake):
        r = mod_fonts.dispatch({
        'action': 'list'
    })
    assert seen.get("called"), "dispatch did not call _forward"
    assert isinstance(r, dict), f"dispatch returned non-dict: {r!r}"


def test_fonts_detect(mod_fonts):
    seen = {}

    def fake(method, path, body=None, timeout=10):
        seen["called"] = True
        return {"ok": True, "status": 200, "data": {}}

    with patch.object(mod_fonts, "_forward", fake):
        r = mod_fonts.dispatch({
        'action': 'detect'
    })
    assert seen.get("called"), "dispatch did not call _forward"
    assert isinstance(r, dict), f"dispatch returned non-dict: {r!r}"


def test_fonts_install(mod_fonts):
    seen = {}

    def fake(method, path, body=None, timeout=10):
        seen["called"] = True
        return {"ok": True, "status": 200, "data": {}}

    with patch.object(mod_fonts, "_forward", fake):
        r = mod_fonts.dispatch({
        'action': 'install',
        'name': 'font1',
        'file': 'base64data'
    })
    assert seen.get("called"), "dispatch did not call _forward"
    assert isinstance(r, dict), f"dispatch returned non-dict: {r!r}"


def test_fonts_monkey_unknown_action(mod_fonts):
    r = mod_fonts.dispatch({"action": "nuke_galaxy_from_orbit"})
    assert r.get("ok") is False, f"Expected ok=False, got {r!r}"
    assert r.get("status") == 400, f"Expected status=400, got {r!r}"

def test_fonts_monkey_garbage_input(mod_fonts):
    for bad in [
        {},
        {"action": ""},
        {"action": None},
        {"action": 123},
        {"action": "a" * 1000},
    ]:
        r = mod_fonts.dispatch(bad)
        assert isinstance(r, dict), f"dispatch({bad!r}) did not return dict: {r!r}"
        assert "ok" in r, f"dispatch({bad!r}) missing ok: {r!r}"
        assert "status" in r, f"dispatch({bad!r}) missing status: {r!r}"
        _assert_safe_envelope(r)


# ── gallery proxy ────────────────────────────────────────────────────


@pytest.fixture()
def mod_gallery():
    _stub_modules()
    handler = HANDLER_DIR / "gallery.py"
    spec = importlib.util.spec_from_file_location(
        "_sweep_gallery", handler)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_gallery_view(mod_gallery):
    seen = {}

    def fake(method, path, body=None, timeout=10):
        seen["called"] = True
        return {"ok": True, "status": 200, "data": {}}

    with patch.object(mod_gallery, "_forward", fake):
        r = mod_gallery.dispatch({
        'action': 'view',
        'campaign_id': 'c1'
    })
    assert seen.get("called"), "dispatch did not call _forward"
    assert isinstance(r, dict), f"dispatch returned non-dict: {r!r}"


def test_gallery_monkey_unknown_action(mod_gallery):
    r = mod_gallery.dispatch({"action": "nuke_galaxy_from_orbit"})
    assert r.get("ok") is False, f"Expected ok=False, got {r!r}"
    assert r.get("status") == 400, f"Expected status=400, got {r!r}"

def test_gallery_monkey_garbage_input(mod_gallery):
    for bad in [
        {},
        {"action": ""},
        {"action": None},
        {"action": 123},
        {"action": "a" * 1000},
    ]:
        r = mod_gallery.dispatch(bad)
        assert isinstance(r, dict), f"dispatch({bad!r}) did not return dict: {r!r}"
        assert "ok" in r, f"dispatch({bad!r}) missing ok: {r!r}"
        assert "status" in r, f"dispatch({bad!r}) missing status: {r!r}"
        _assert_safe_envelope(r)


# ── health proxy ────────────────────────────────────────────────────


@pytest.fixture()
def mod_health():
    _stub_modules()
    handler = HANDLER_DIR / "health.py"
    spec = importlib.util.spec_from_file_location(
        "_sweep_health", handler)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_health_capabilities(mod_health):
    seen = {}

    def fake(method, path, body=None, timeout=10):
        seen["called"] = True
        return {"ok": True, "status": 200, "data": {}}

    with patch.object(mod_health, "_forward", fake):
        r = mod_health.dispatch({
        'action': 'capabilities'
    })
    assert seen.get("called"), "dispatch did not call _forward"
    assert isinstance(r, dict), f"dispatch returned non-dict: {r!r}"


def test_health_monkey_unknown_action(mod_health):
    r = mod_health.dispatch({"action": "nuke_galaxy_from_orbit"})
    assert r.get("ok") is False, f"Expected ok=False, got {r!r}"
    assert r.get("status") == 400, f"Expected status=400, got {r!r}"

def test_health_monkey_garbage_input(mod_health):
    for bad in [
        {},
        {"action": ""},
        {"action": None},
        {"action": 123},
        {"action": "a" * 1000},
    ]:
        r = mod_health.dispatch(bad)
        assert isinstance(r, dict), f"dispatch({bad!r}) did not return dict: {r!r}"
        assert "ok" in r, f"dispatch({bad!r}) missing ok: {r!r}"
        assert "status" in r, f"dispatch({bad!r}) missing status: {r!r}"
        _assert_safe_envelope(r)


# ── mind proxy ────────────────────────────────────────────────────


@pytest.fixture()
def mod_mind():
    _stub_modules()
    handler = HANDLER_DIR / "mind.py"
    spec = importlib.util.spec_from_file_location(
        "_sweep_mind", handler)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_mind_memory(mod_mind):
    seen = {}

    def fake(method, path, body=None, timeout=10):
        seen["called"] = True
        return {"ok": True, "status": 200, "data": {}}

    with patch.object(mod_mind, "_forward", fake):
        r = mod_mind.dispatch({
        'action': 'memory'
    })
    assert seen.get("called"), "dispatch did not call _forward"
    assert isinstance(r, dict), f"dispatch returned non-dict: {r!r}"


def test_mind_skills(mod_mind):
    seen = {}

    def fake(method, path, body=None, timeout=10):
        seen["called"] = True
        return {"ok": True, "status": 200, "data": {}}

    with patch.object(mod_mind, "_forward", fake):
        r = mod_mind.dispatch({
        'action': 'skills'
    })
    assert seen.get("called"), "dispatch did not call _forward"
    assert isinstance(r, dict), f"dispatch returned non-dict: {r!r}"


def test_mind_curation(mod_mind):
    seen = {}

    def fake(method, path, body=None, timeout=10):
        seen["called"] = True
        return {"ok": True, "status": 200, "data": {}}

    with patch.object(mod_mind, "_forward", fake):
        r = mod_mind.dispatch({
        'action': 'curation'
    })
    assert seen.get("called"), "dispatch did not call _forward"
    assert isinstance(r, dict), f"dispatch returned non-dict: {r!r}"


def test_mind_approve(mod_mind):
    seen = {}

    def fake(method, path, body=None, timeout=10):
        seen["called"] = True
        return {"ok": True, "status": 200, "data": {}}

    with patch.object(mod_mind, "_forward", fake):
        r = mod_mind.dispatch({
        'action': 'approve',
        'proposal_id': 'p1'
    })
    assert seen.get("called"), "dispatch did not call _forward"
    assert isinstance(r, dict), f"dispatch returned non-dict: {r!r}"


def test_mind_forget(mod_mind):
    seen = {}

    def fake(method, path, body=None, timeout=10):
        seen["called"] = True
        return {"ok": True, "status": 200, "data": {}}

    with patch.object(mod_mind, "_forward", fake):
        r = mod_mind.dispatch({
        'action': 'forget',
        'key': 'k1'
    })
    assert seen.get("called"), "dispatch did not call _forward"
    assert isinstance(r, dict), f"dispatch returned non-dict: {r!r}"


def test_mind_monkey_unknown_action(mod_mind):
    r = mod_mind.dispatch({"action": "nuke_galaxy_from_orbit"})
    assert r.get("ok") is False, f"Expected ok=False, got {r!r}"
    assert r.get("status") == 400, f"Expected status=400, got {r!r}"

def test_mind_monkey_garbage_input(mod_mind):
    for bad in [
        {},
        {"action": ""},
        {"action": None},
        {"action": 123},
        {"action": "a" * 1000},
    ]:
        r = mod_mind.dispatch(bad)
        assert isinstance(r, dict), f"dispatch({bad!r}) did not return dict: {r!r}"
        assert "ok" in r, f"dispatch({bad!r}) missing ok: {r!r}"
        assert "status" in r, f"dispatch({bad!r}) missing status: {r!r}"
        _assert_safe_envelope(r)


# ── model_endpoints proxy ────────────────────────────────────────────────────


@pytest.fixture()
def mod_model_endpoints():
    _stub_modules()
    handler = HANDLER_DIR / "model_endpoints.py"
    spec = importlib.util.spec_from_file_location(
        "_sweep_model_endpoints", handler)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_model_endpoints_list(mod_model_endpoints):
    seen = {}

    def fake(method, path, body=None, timeout=10):
        seen["called"] = True
        return {"ok": True, "status": 200, "data": {}}

    with patch.object(mod_model_endpoints, "_forward", fake):
        r = mod_model_endpoints.dispatch({
        'action': 'list'
    })
    assert seen.get("called"), "dispatch did not call _forward"
    assert isinstance(r, dict), f"dispatch returned non-dict: {r!r}"


def test_model_endpoints_add(mod_model_endpoints):
    seen = {}

    def fake(method, path, body=None, timeout=10):
        seen["called"] = True
        return {"ok": True, "status": 200, "data": {}}

    with patch.object(mod_model_endpoints, "_forward", fake):
        r = mod_model_endpoints.dispatch({
        'action': 'add'
    })
    assert seen.get("called"), "dispatch did not call _forward"
    assert isinstance(r, dict), f"dispatch returned non-dict: {r!r}"


def test_model_endpoints_test(mod_model_endpoints):
    seen = {}

    def fake(method, path, body=None, timeout=10):
        seen["called"] = True
        return {"ok": True, "status": 200, "data": {}}

    with patch.object(mod_model_endpoints, "_forward", fake):
        r = mod_model_endpoints.dispatch({
        'action': 'test'
    })
    assert seen.get("called"), "dispatch did not call _forward"
    assert isinstance(r, dict), f"dispatch returned non-dict: {r!r}"


def test_model_endpoints_remove(mod_model_endpoints):
    seen = {}

    def fake(method, path, body=None, timeout=10):
        seen["called"] = True
        return {"ok": True, "status": 200, "data": {}}

    with patch.object(mod_model_endpoints, "_forward", fake):
        r = mod_model_endpoints.dispatch({
        'action': 'remove',
        'endpoint_id': 'e1'
    })
    assert seen.get("called"), "dispatch did not call _forward"
    assert isinstance(r, dict), f"dispatch returned non-dict: {r!r}"


def test_model_endpoints_models(mod_model_endpoints):
    seen = {}

    def fake(method, path, body=None, timeout=10):
        seen["called"] = True
        return {"ok": True, "status": 200, "data": {}}

    with patch.object(mod_model_endpoints, "_forward", fake):
        r = mod_model_endpoints.dispatch({
        'action': 'models',
        'endpoint_id': 'e1'
    })
    assert seen.get("called"), "dispatch did not call _forward"
    assert isinstance(r, dict), f"dispatch returned non-dict: {r!r}"


def test_model_endpoints_monkey_unknown_action(mod_model_endpoints):
    r = mod_model_endpoints.dispatch({"action": "nuke_galaxy_from_orbit"})
    assert r.get("ok") is False, f"Expected ok=False, got {r!r}"
    assert r.get("status") == 400, f"Expected status=400, got {r!r}"

def test_model_endpoints_monkey_garbage_input(mod_model_endpoints):
    for bad in [
        {},
        {"action": ""},
        {"action": None},
        {"action": 123},
        {"action": "a" * 1000},
    ]:
        r = mod_model_endpoints.dispatch(bad)
        assert isinstance(r, dict), f"dispatch({bad!r}) did not return dict: {r!r}"
        assert "ok" in r, f"dispatch({bad!r}) missing ok: {r!r}"
        assert "status" in r, f"dispatch({bad!r}) missing status: {r!r}"
        _assert_safe_envelope(r)


# ── notifications proxy ────────────────────────────────────────────────────


@pytest.fixture()
def mod_notifications():
    _stub_modules()
    handler = HANDLER_DIR / "notifications.py"
    spec = importlib.util.spec_from_file_location(
        "_sweep_notifications", handler)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_notifications_list(mod_notifications):
    seen = {}

    def fake(method, path, body=None, timeout=10):
        seen["called"] = True
        return {"ok": True, "status": 200, "data": {}}

    with patch.object(mod_notifications, "_forward", fake):
        r = mod_notifications.dispatch({
        'action': 'list'
    })
    assert seen.get("called"), "dispatch did not call _forward"
    assert isinstance(r, dict), f"dispatch returned non-dict: {r!r}"


def test_notifications_seen(mod_notifications):
    seen = {}

    def fake(method, path, body=None, timeout=10):
        seen["called"] = True
        return {"ok": True, "status": 200, "data": {}}

    with patch.object(mod_notifications, "_forward", fake):
        r = mod_notifications.dispatch({
        'action': 'seen',
        'notification_id': 'n1'
    })
    assert seen.get("called"), "dispatch did not call _forward"
    assert isinstance(r, dict), f"dispatch returned non-dict: {r!r}"


def test_notifications_deliver_now(mod_notifications):
    seen = {}

    def fake(method, path, body=None, timeout=10):
        seen["called"] = True
        return {"ok": True, "status": 200, "data": {}}

    with patch.object(mod_notifications, "_forward", fake):
        r = mod_notifications.dispatch({
        'action': 'deliver_now'
    })
    assert seen.get("called"), "dispatch did not call _forward"
    assert isinstance(r, dict), f"dispatch returned non-dict: {r!r}"


def test_notifications_monkey_unknown_action(mod_notifications):
    r = mod_notifications.dispatch({"action": "nuke_galaxy_from_orbit"})
    assert r.get("ok") is False, f"Expected ok=False, got {r!r}"
    assert r.get("status") == 400, f"Expected status=400, got {r!r}"

def test_notifications_monkey_garbage_input(mod_notifications):
    for bad in [
        {},
        {"action": ""},
        {"action": None},
        {"action": 123},
        {"action": "a" * 1000},
    ]:
        r = mod_notifications.dispatch(bad)
        assert isinstance(r, dict), f"dispatch({bad!r}) did not return dict: {r!r}"
        assert "ok" in r, f"dispatch({bad!r}) missing ok: {r!r}"
        assert "status" in r, f"dispatch({bad!r}) missing status: {r!r}"
        _assert_safe_envelope(r)


# ── onboarding proxy ────────────────────────────────────────────────────


@pytest.fixture()
def mod_onboarding():
    _stub_modules()
    handler = HANDLER_DIR / "onboarding.py"
    spec = importlib.util.spec_from_file_location(
        "_sweep_onboarding", handler)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_onboarding_state(mod_onboarding):
    seen = {}

    def fake(method, path, body=None, timeout=10):
        seen["called"] = True
        return {"ok": True, "status": 200, "data": {}}

    with patch.object(mod_onboarding, "_forward", fake):
        r = mod_onboarding.dispatch({
        'action': 'state',
        'campaign_id': 'c1'
    })
    assert seen.get("called"), "dispatch did not call _forward"
    assert isinstance(r, dict), f"dispatch returned non-dict: {r!r}"


def test_onboarding_section(mod_onboarding):
    seen = {}

    def fake(method, path, body=None, timeout=10):
        seen["called"] = True
        return {"ok": True, "status": 200, "data": {}}

    with patch.object(mod_onboarding, "_forward", fake):
        r = mod_onboarding.dispatch({
        'action': 'section',
        'campaign_id': 'c1'
    })
    assert seen.get("called"), "dispatch did not call _forward"
    assert isinstance(r, dict), f"dispatch returned non-dict: {r!r}"


def test_onboarding_complete(mod_onboarding):
    seen = {}

    def fake(method, path, body=None, timeout=10):
        seen["called"] = True
        return {"ok": True, "status": 200, "data": {}}

    with patch.object(mod_onboarding, "_forward", fake):
        r = mod_onboarding.dispatch({
        'action': 'complete',
        'campaign_id': 'c1'
    })
    assert seen.get("called"), "dispatch did not call _forward"
    assert isinstance(r, dict), f"dispatch returned non-dict: {r!r}"


def test_onboarding_monkey_unknown_action(mod_onboarding):
    r = mod_onboarding.dispatch({"action": "nuke_galaxy_from_orbit"})
    assert r.get("ok") is False, f"Expected ok=False, got {r!r}"
    assert r.get("status") == 400, f"Expected status=400, got {r!r}"

def test_onboarding_monkey_garbage_input(mod_onboarding):
    for bad in [
        {},
        {"action": ""},
        {"action": None},
        {"action": 123},
        {"action": "a" * 1000},
    ]:
        r = mod_onboarding.dispatch(bad)
        assert isinstance(r, dict), f"dispatch({bad!r}) did not return dict: {r!r}"
        assert "ok" in r, f"dispatch({bad!r}) missing ok: {r!r}"
        assert "status" in r, f"dispatch({bad!r}) missing status: {r!r}"
        _assert_safe_envelope(r)


# ── ops proxy ────────────────────────────────────────────────────


@pytest.fixture()
def mod_ops():
    _stub_modules()
    handler = HANDLER_DIR / "ops.py"
    spec = importlib.util.spec_from_file_location(
        "_sweep_ops", handler)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_ops_tools(mod_ops):
    seen = {}

    def fake(method, path, body=None, timeout=10):
        seen["called"] = True
        return {"ok": True, "status": 200, "data": {}}

    with patch.object(mod_ops, "_forward", fake):
        r = mod_ops.dispatch({
        'action': 'tools',
        'campaign_id': 'c1'
    })
    assert seen.get("called"), "dispatch did not call _forward"
    assert isinstance(r, dict), f"dispatch returned non-dict: {r!r}"


def test_ops_set_tool(mod_ops):
    seen = {}

    def fake(method, path, body=None, timeout=10):
        seen["called"] = True
        return {"ok": True, "status": 200, "data": {}}

    with patch.object(mod_ops, "_forward", fake):
        r = mod_ops.dispatch({
        'action': 'set_tool',
        'campaign_id': 'c1',
        'tool_key': 'tk1'
    })
    assert seen.get("called"), "dispatch did not call _forward"
    assert isinstance(r, dict), f"dispatch returned non-dict: {r!r}"


def test_ops_history(mod_ops):
    seen = {}

    def fake(method, path, body=None, timeout=10):
        seen["called"] = True
        return {"ok": True, "status": 200, "data": {}}

    with patch.object(mod_ops, "_forward", fake):
        r = mod_ops.dispatch({
        'action': 'history',
        'campaign_id': 'c1'
    })
    assert seen.get("called"), "dispatch did not call _forward"
    assert isinstance(r, dict), f"dispatch returned non-dict: {r!r}"


def test_ops_detections(mod_ops):
    seen = {}

    def fake(method, path, body=None, timeout=10):
        seen["called"] = True
        return {"ok": True, "status": 200, "data": {}}

    with patch.object(mod_ops, "_forward", fake):
        r = mod_ops.dispatch({
        'action': 'detections',
        'campaign_id': 'c1'
    })
    assert seen.get("called"), "dispatch did not call _forward"
    assert isinstance(r, dict), f"dispatch returned non-dict: {r!r}"


def test_ops_logs(mod_ops):
    seen = {}

    def fake(method, path, body=None, timeout=10):
        seen["called"] = True
        return {"ok": True, "status": 200, "data": {}}

    with patch.object(mod_ops, "_forward", fake):
        r = mod_ops.dispatch({
        'action': 'logs',
        'campaign_id': 'c1'
    })
    assert seen.get("called"), "dispatch did not call _forward"
    assert isinstance(r, dict), f"dispatch returned non-dict: {r!r}"


def test_ops_monkey_unknown_action(mod_ops):
    r = mod_ops.dispatch({"action": "nuke_galaxy_from_orbit"})
    assert r.get("ok") is False, f"Expected ok=False, got {r!r}"
    assert r.get("status") == 400, f"Expected status=400, got {r!r}"

def test_ops_monkey_garbage_input(mod_ops):
    for bad in [
        {},
        {"action": ""},
        {"action": None},
        {"action": 123},
        {"action": "a" * 1000},
    ]:
        r = mod_ops.dispatch(bad)
        assert isinstance(r, dict), f"dispatch({bad!r}) did not return dict: {r!r}"
        assert "ok" in r, f"dispatch({bad!r}) missing ok: {r!r}"
        assert "status" in r, f"dispatch({bad!r}) missing status: {r!r}"
        _assert_safe_envelope(r)


# ── pending proxy ────────────────────────────────────────────────────


@pytest.fixture()
def mod_pending():
    _stub_modules()
    handler = HANDLER_DIR / "pending.py"
    spec = importlib.util.spec_from_file_location(
        "_sweep_pending", handler)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_pending_list(mod_pending):
    seen = {}

    def fake(method, path, body=None, timeout=10):
        seen["called"] = True
        return {"ok": True, "status": 200, "data": {}}

    with patch.object(mod_pending, "_forward", fake):
        r = mod_pending.dispatch({
        'action': 'list',
        'campaign_id': 'c1'
    })
    assert seen.get("called"), "dispatch did not call _forward"
    assert isinstance(r, dict), f"dispatch returned non-dict: {r!r}"


def test_pending_count(mod_pending):
    seen = {}

    def fake(method, path, body=None, timeout=10):
        seen["called"] = True
        return {"ok": True, "status": 200, "data": {}}

    with patch.object(mod_pending, "_forward", fake):
        r = mod_pending.dispatch({
        'action': 'count',
        'campaign_id': 'c1'
    })
    assert seen.get("called"), "dispatch did not call _forward"
    assert isinstance(r, dict), f"dispatch returned non-dict: {r!r}"


def test_pending_resolve(mod_pending):
    seen = {}

    def fake(method, path, body=None, timeout=10):
        seen["called"] = True
        return {"ok": True, "status": 200, "data": {}}

    with patch.object(mod_pending, "_forward", fake):
        r = mod_pending.dispatch({
        'action': 'resolve',
        'campaign_id': 'c1',
        'action_id': 'a1'
    })
    assert seen.get("called"), "dispatch did not call _forward"
    assert isinstance(r, dict), f"dispatch returned non-dict: {r!r}"


def test_pending_snooze(mod_pending):
    seen = {}

    def fake(method, path, body=None, timeout=10):
        seen["called"] = True
        return {"ok": True, "status": 200, "data": {}}

    with patch.object(mod_pending, "_forward", fake):
        r = mod_pending.dispatch({
        'action': 'snooze',
        'campaign_id': 'c1',
        'action_id': 'a1',
        'until': 'tomorrow'
    })
    assert seen.get("called"), "dispatch did not call _forward"
    assert isinstance(r, dict), f"dispatch returned non-dict: {r!r}"


def test_pending_resolve_bulk(mod_pending):
    seen = {}

    def fake(method, path, body=None, timeout=10):
        seen["called"] = True
        return {"ok": True, "status": 200, "data": {}}

    with patch.object(mod_pending, "_forward", fake):
        r = mod_pending.dispatch({
        'action': 'resolve_bulk',
        'campaign_id': 'c1',
        'action_ids': ['a1', 'a2']
    })
    assert seen.get("called"), "dispatch did not call _forward"
    assert isinstance(r, dict), f"dispatch returned non-dict: {r!r}"


def test_pending_monkey_unknown_action(mod_pending):
    r = mod_pending.dispatch({"action": "nuke_galaxy_from_orbit"})
    assert r.get("ok") is False, f"Expected ok=False, got {r!r}"
    assert r.get("status") == 400, f"Expected status=400, got {r!r}"

def test_pending_monkey_garbage_input(mod_pending):
    for bad in [
        {},
        {"action": ""},
        {"action": None},
        {"action": 123},
        {"action": "a" * 1000},
    ]:
        r = mod_pending.dispatch(bad)
        assert isinstance(r, dict), f"dispatch({bad!r}) did not return dict: {r!r}"
        assert "ok" in r, f"dispatch({bad!r}) missing ok: {r!r}"
        assert "status" in r, f"dispatch({bad!r}) missing status: {r!r}"
        _assert_safe_envelope(r)


# ── research proxy ────────────────────────────────────────────────────


@pytest.fixture()
def mod_research():
    _stub_modules()
    handler = HANDLER_DIR / "research.py"
    spec = importlib.util.spec_from_file_location(
        "_sweep_research", handler)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_research_cached(mod_research):
    seen = {}

    def fake(method, path, body=None, timeout=10):
        seen["called"] = True
        return {"ok": True, "status": 200, "data": {}}

    with patch.object(mod_research, "_forward", fake):
        r = mod_research.dispatch({
        'action': 'cached',
        'campaign_id': 'c1'
    })
    assert seen.get("called"), "dispatch did not call _forward"
    assert isinstance(r, dict), f"dispatch returned non-dict: {r!r}"


def test_research_budget(mod_research):
    seen = {}

    def fake(method, path, body=None, timeout=10):
        seen["called"] = True
        return {"ok": True, "status": 200, "data": {}}

    with patch.object(mod_research, "_forward", fake):
        r = mod_research.dispatch({
        'action': 'budget',
        'campaign_id': 'c1'
    })
    assert seen.get("called"), "dispatch did not call _forward"
    assert isinstance(r, dict), f"dispatch returned non-dict: {r!r}"


def test_research_run(mod_research):
    seen = {}

    def fake(method, path, body=None, timeout=10):
        seen["called"] = True
        return {"ok": True, "status": 200, "data": {}}

    with patch.object(mod_research, "_forward", fake):
        r = mod_research.dispatch({
        'action': 'run',
        'campaign_id': 'c1'
    })
    assert seen.get("called"), "dispatch did not call _forward"
    assert isinstance(r, dict), f"dispatch returned non-dict: {r!r}"


def test_research_monkey_unknown_action(mod_research):
    r = mod_research.dispatch({"action": "nuke_galaxy_from_orbit"})
    assert r.get("ok") is False, f"Expected ok=False, got {r!r}"
    assert r.get("status") == 400, f"Expected status=400, got {r!r}"

def test_research_monkey_garbage_input(mod_research):
    for bad in [
        {},
        {"action": ""},
        {"action": None},
        {"action": 123},
        {"action": "a" * 1000},
    ]:
        r = mod_research.dispatch(bad)
        assert isinstance(r, dict), f"dispatch({bad!r}) did not return dict: {r!r}"
        assert "ok" in r, f"dispatch({bad!r}) missing ok: {r!r}"
        assert "status" in r, f"dispatch({bad!r}) missing status: {r!r}"
        _assert_safe_envelope(r)


# ── screening proxy ────────────────────────────────────────────────────


@pytest.fixture()
def mod_screening():
    _stub_modules()
    handler = HANDLER_DIR / "screening.py"
    spec = importlib.util.spec_from_file_location(
        "_sweep_screening", handler)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_screening_library(mod_screening):
    seen = {}

    def fake(method, path, body=None, timeout=10):
        seen["called"] = True
        return {"ok": True, "status": 200, "data": {}}

    with patch.object(mod_screening, "_forward", fake):
        r = mod_screening.dispatch({
        'action': 'library',
        'campaign_id': 'c1'
    })
    assert seen.get("called"), "dispatch did not call _forward"
    assert isinstance(r, dict), f"dispatch returned non-dict: {r!r}"


def test_screening_generate(mod_screening):
    seen = {}

    def fake(method, path, body=None, timeout=10):
        seen["called"] = True
        return {"ok": True, "status": 200, "data": {}}

    with patch.object(mod_screening, "_forward", fake):
        r = mod_screening.dispatch({
        'action': 'generate',
        'campaign_id': 'c1'
    })
    assert seen.get("called"), "dispatch did not call _forward"
    assert isinstance(r, dict), f"dispatch returned non-dict: {r!r}"


def test_screening_monkey_unknown_action(mod_screening):
    r = mod_screening.dispatch({"action": "nuke_galaxy_from_orbit"})
    assert r.get("ok") is False, f"Expected ok=False, got {r!r}"
    assert r.get("status") == 400, f"Expected status=400, got {r!r}"

def test_screening_monkey_garbage_input(mod_screening):
    for bad in [
        {},
        {"action": ""},
        {"action": None},
        {"action": 123},
        {"action": "a" * 1000},
    ]:
        r = mod_screening.dispatch(bad)
        assert isinstance(r, dict), f"dispatch({bad!r}) did not return dict: {r!r}"
        assert "ok" in r, f"dispatch({bad!r}) missing ok: {r!r}"
        assert "status" in r, f"dispatch({bad!r}) missing status: {r!r}"
        _assert_safe_envelope(r)


# ── takeover proxy ────────────────────────────────────────────────────


@pytest.fixture()
def mod_takeover():
    _stub_modules()
    handler = HANDLER_DIR / "takeover.py"
    spec = importlib.util.spec_from_file_location(
        "_sweep_takeover", handler)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_takeover_sessions(mod_takeover):
    seen = {}

    def fake(method, path, body=None, timeout=10):
        seen["called"] = True
        return {"ok": True, "status": 200, "data": {}}

    with patch.object(mod_takeover, "_forward", fake):
        r = mod_takeover.dispatch({
        'action': 'sessions'
    })
    assert seen.get("called"), "dispatch did not call _forward"
    assert isinstance(r, dict), f"dispatch returned non-dict: {r!r}"


def test_takeover_view_url(mod_takeover):
    seen = {}

    def fake(method, path, body=None, timeout=10):
        seen["called"] = True
        return {"ok": True, "status": 200, "data": {}}

    with patch.object(mod_takeover, "_forward", fake):
        r = mod_takeover.dispatch({
        'action': 'view_url',
        'session_id': 's1'
    })
    assert seen.get("called"), "dispatch did not call _forward"
    assert isinstance(r, dict), f"dispatch returned non-dict: {r!r}"


def test_takeover_takeover(mod_takeover):
    seen = {}

    def fake(method, path, body=None, timeout=10):
        seen["called"] = True
        return {"ok": True, "status": 200, "data": {}}

    with patch.object(mod_takeover, "_forward", fake):
        r = mod_takeover.dispatch({
        'action': 'takeover',
        'session_id': 's1'
    })
    assert seen.get("called"), "dispatch did not call _forward"
    assert isinstance(r, dict), f"dispatch returned non-dict: {r!r}"


def test_takeover_resume_2fa(mod_takeover):
    seen = {}

    def fake(method, path, body=None, timeout=10):
        seen["called"] = True
        return {"ok": True, "status": 200, "data": {}}

    with patch.object(mod_takeover, "_forward", fake):
        r = mod_takeover.dispatch({
        'action': 'resume_2fa',
        'application_id': 'a1'
    })
    assert seen.get("called"), "dispatch did not call _forward"
    assert isinstance(r, dict), f"dispatch returned non-dict: {r!r}"


def test_takeover_resume_account(mod_takeover):
    seen = {}

    def fake(method, path, body=None, timeout=10):
        seen["called"] = True
        return {"ok": True, "status": 200, "data": {}}

    with patch.object(mod_takeover, "_forward", fake):
        r = mod_takeover.dispatch({
        'action': 'resume_account',
        'application_id': 'a1'
    })
    assert seen.get("called"), "dispatch did not call _forward"
    assert isinstance(r, dict), f"dispatch returned non-dict: {r!r}"


def test_takeover_resume_detection(mod_takeover):
    seen = {}

    def fake(method, path, body=None, timeout=10):
        seen["called"] = True
        return {"ok": True, "status": 200, "data": {}}

    with patch.object(mod_takeover, "_forward", fake):
        r = mod_takeover.dispatch({
        'action': 'resume_detection',
        'application_id': 'a1'
    })
    assert seen.get("called"), "dispatch did not call _forward"
    assert isinstance(r, dict), f"dispatch returned non-dict: {r!r}"


def test_takeover_handoff(mod_takeover):
    seen = {}

    def fake(method, path, body=None, timeout=10):
        seen["called"] = True
        return {"ok": True, "status": 200, "data": {}}

    with patch.object(mod_takeover, "_forward", fake):
        r = mod_takeover.dispatch({
        'action': 'handoff',
        'application_id': 'a1'
    })
    assert seen.get("called"), "dispatch did not call _forward"
    assert isinstance(r, dict), f"dispatch returned non-dict: {r!r}"


def test_takeover_final_approval(mod_takeover):
    seen = {}

    def fake(method, path, body=None, timeout=10):
        seen["called"] = True
        return {"ok": True, "status": 200, "data": {}}

    with patch.object(mod_takeover, "_forward", fake):
        r = mod_takeover.dispatch({
        'action': 'final_approval',
        'application_id': 'a1'
    })
    assert seen.get("called"), "dispatch did not call _forward"
    assert isinstance(r, dict), f"dispatch returned non-dict: {r!r}"


def test_takeover_monkey_unknown_action(mod_takeover):
    r = mod_takeover.dispatch({"action": "nuke_galaxy_from_orbit"})
    assert r.get("ok") is False, f"Expected ok=False, got {r!r}"
    assert r.get("status") == 400, f"Expected status=400, got {r!r}"

def test_takeover_monkey_garbage_input(mod_takeover):
    for bad in [
        {},
        {"action": ""},
        {"action": None},
        {"action": 123},
        {"action": "a" * 1000},
    ]:
        r = mod_takeover.dispatch(bad)
        assert isinstance(r, dict), f"dispatch({bad!r}) did not return dict: {r!r}"
        assert "ok" in r, f"dispatch({bad!r}) missing ok: {r!r}"
        assert "status" in r, f"dispatch({bad!r}) missing status: {r!r}"
        _assert_safe_envelope(r)


# ── tracker proxy ────────────────────────────────────────────────────


@pytest.fixture()
def mod_tracker():
    _stub_modules()
    handler = HANDLER_DIR / "tracker.py"
    spec = importlib.util.spec_from_file_location(
        "_sweep_tracker", handler)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_tracker_board(mod_tracker):
    seen = {}

    def fake(method, path, body=None, timeout=10):
        seen["called"] = True
        return {"ok": True, "status": 200, "data": {}}

    with patch.object(mod_tracker, "_forward", fake):
        r = mod_tracker.dispatch({
        'action': 'board',
        'campaign_id': 'c1'
    })
    assert seen.get("called"), "dispatch did not call _forward"
    assert isinstance(r, dict), f"dispatch returned non-dict: {r!r}"


def test_tracker_attention(mod_tracker):
    seen = {}

    def fake(method, path, body=None, timeout=10):
        seen["called"] = True
        return {"ok": True, "status": 200, "data": {}}

    with patch.object(mod_tracker, "_forward", fake):
        r = mod_tracker.dispatch({
        'action': 'attention',
        'campaign_id': 'c1'
    })
    assert seen.get("called"), "dispatch did not call _forward"
    assert isinstance(r, dict), f"dispatch returned non-dict: {r!r}"


def test_tracker_monkey_unknown_action(mod_tracker):
    r = mod_tracker.dispatch({"action": "nuke_galaxy_from_orbit"})
    assert r.get("ok") is False, f"Expected ok=False, got {r!r}"
    assert r.get("status") == 400, f"Expected status=400, got {r!r}"

def test_tracker_monkey_garbage_input(mod_tracker):
    for bad in [
        {},
        {"action": ""},
        {"action": None},
        {"action": 123},
        {"action": "a" * 1000},
    ]:
        r = mod_tracker.dispatch(bad)
        assert isinstance(r, dict), f"dispatch({bad!r}) did not return dict: {r!r}"
        assert "ok" in r, f"dispatch({bad!r}) missing ok: {r!r}"
        assert "status" in r, f"dispatch({bad!r}) missing status: {r!r}"
        _assert_safe_envelope(r)


# ── update_panel proxy ────────────────────────────────────────────────────


@pytest.fixture()
def mod_update_panel():
    _stub_modules()
    handler = HANDLER_DIR / "update_panel.py"
    spec = importlib.util.spec_from_file_location(
        "_sweep_update_panel", handler)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_update_panel_status(mod_update_panel):
    seen = {}

    def fake(method, path, body=None, timeout=10):
        seen["called"] = True
        return {"ok": True, "status": 200, "data": {}}

    with patch.object(mod_update_panel, "_forward", fake):
        r = mod_update_panel.dispatch({
        'action': 'status'
    })
    assert seen.get("called"), "dispatch did not call _forward"
    assert isinstance(r, dict), f"dispatch returned non-dict: {r!r}"


def test_update_panel_trigger(mod_update_panel):
    seen = {}

    def fake(method, path, body=None, timeout=10):
        seen["called"] = True
        return {"ok": True, "status": 200, "data": {}}

    with patch.object(mod_update_panel, "_forward", fake):
        r = mod_update_panel.dispatch({
        'action': 'trigger'
    })
    assert seen.get("called"), "dispatch did not call _forward"
    assert isinstance(r, dict), f"dispatch returned non-dict: {r!r}"


def test_update_panel_monkey_unknown_action(mod_update_panel):
    r = mod_update_panel.dispatch({"action": "nuke_galaxy_from_orbit"})
    assert r.get("ok") is False, f"Expected ok=False, got {r!r}"
    assert r.get("status") == 400, f"Expected status=400, got {r!r}"

def test_update_panel_monkey_garbage_input(mod_update_panel):
    for bad in [
        {},
        {"action": ""},
        {"action": None},
        {"action": 123},
        {"action": "a" * 1000},
    ]:
        r = mod_update_panel.dispatch(bad)
        assert isinstance(r, dict), f"dispatch({bad!r}) did not return dict: {r!r}"
        assert "ok" in r, f"dispatch({bad!r}) missing ok: {r!r}"
        assert "status" in r, f"dispatch({bad!r}) missing status: {r!r}"
        _assert_safe_envelope(r)


# ── vault proxy ────────────────────────────────────────────────────


@pytest.fixture()
def mod_vault():
    _stub_modules()
    handler = HANDLER_DIR / "vault.py"
    spec = importlib.util.spec_from_file_location(
        "_sweep_vault", handler)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_vault_list(mod_vault):
    seen = {}

    def fake(method, path, body=None, timeout=10):
        seen["called"] = True
        return {"ok": True, "status": 200, "data": {}}

    with patch.object(mod_vault, "_forward", fake):
        r = mod_vault.dispatch({
        'action': 'list',
        'campaign_id': 'c1'
    })
    assert seen.get("called"), "dispatch did not call _forward"
    assert isinstance(r, dict), f"dispatch returned non-dict: {r!r}"


def test_vault_add(mod_vault):
    seen = {}

    def fake(method, path, body=None, timeout=10):
        seen["called"] = True
        return {"ok": True, "status": 200, "data": {}}

    with patch.object(mod_vault, "_forward", fake):
        r = mod_vault.dispatch({
        'action': 'add',
        'campaign_id': 'c1',
        'tenant_key': 'tk',
        'username': 'u',
        'secret': 's'
    })
    assert seen.get("called"), "dispatch did not call _forward"
    assert isinstance(r, dict), f"dispatch returned non-dict: {r!r}"


def test_vault_delete(mod_vault):
    seen = {}

    def fake(method, path, body=None, timeout=10):
        seen["called"] = True
        return {"ok": True, "status": 200, "data": {}}

    with patch.object(mod_vault, "_forward", fake):
        r = mod_vault.dispatch({
        'action': 'delete',
        'campaign_id': 'c1',
        'tenant_key': 'tk'
    })
    assert seen.get("called"), "dispatch did not call _forward"
    assert isinstance(r, dict), f"dispatch returned non-dict: {r!r}"


def test_vault_account(mod_vault):
    seen = {}

    def fake(method, path, body=None, timeout=10):
        seen["called"] = True
        return {"ok": True, "status": 200, "data": {}}

    with patch.object(mod_vault, "_forward", fake):
        r = mod_vault.dispatch({
        'action': 'account',
        'campaign_id': 'c1'
    })
    assert seen.get("called"), "dispatch did not call _forward"
    assert isinstance(r, dict), f"dispatch returned non-dict: {r!r}"


def test_vault_bank_account(mod_vault):
    seen = {}

    def fake(method, path, body=None, timeout=10):
        seen["called"] = True
        return {"ok": True, "status": 200, "data": {}}

    with patch.object(mod_vault, "_forward", fake):
        r = mod_vault.dispatch({
        'action': 'bank_account',
        'campaign_id': 'c1'
    })
    assert seen.get("called"), "dispatch did not call _forward"
    assert isinstance(r, dict), f"dispatch returned non-dict: {r!r}"


def test_vault_rotate_key(mod_vault):
    seen = {}

    def fake(method, path, body=None, timeout=10):
        seen["called"] = True
        return {"ok": True, "status": 200, "data": {}}

    with patch.object(mod_vault, "_forward", fake):
        r = mod_vault.dispatch({
        'action': 'rotate_key',
        'campaign_id': 'c1'
    })
    assert seen.get("called"), "dispatch did not call _forward"
    assert isinstance(r, dict), f"dispatch returned non-dict: {r!r}"


def test_vault_monkey_unknown_action(mod_vault):
    r = mod_vault.dispatch({"action": "nuke_galaxy_from_orbit"})
    assert r.get("ok") is False, f"Expected ok=False, got {r!r}"
    assert r.get("status") == 400, f"Expected status=400, got {r!r}"

def test_vault_monkey_garbage_input(mod_vault):
    for bad in [
        {},
        {"action": ""},
        {"action": None},
        {"action": 123},
        {"action": "a" * 1000},
    ]:
        r = mod_vault.dispatch(bad)
        assert isinstance(r, dict), f"dispatch({bad!r}) did not return dict: {r!r}"
        assert "ok" in r, f"dispatch({bad!r}) missing ok: {r!r}"
        assert "status" in r, f"dispatch({bad!r}) missing status: {r!r}"
        _assert_safe_envelope(r)



# SKIPPED (ApiHandler subclass without dispatch()): base_resume, features, hello