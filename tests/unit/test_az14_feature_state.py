from pathlib import Path
from unittest.mock import patch
import importlib.util
import sys
import types

import pytest

HANDLER = Path(__file__).resolve().parents[2] / "a0-applicant/api/features.py"


@pytest.fixture()
def feats():
    # Stub framework imports
    api = types.ModuleType("helpers.api")
    class _AH:
        pass
    api.ApiHandler = _AH
    helpers = sys.modules.setdefault("helpers", types.ModuleType("helpers"))
    helpers.api = api
    sys.modules["helpers.api"] = api
    flask = sys.modules.setdefault("flask", types.ModuleType("flask"))
    flask.Request = object
    spec = importlib.util.spec_from_file_location("_az14_feats", HANDLER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ── test_active ───────────────────────────────────────────────────


def test_active(feats):
    """Engine up, gate predicates true, dormant surfaces with status=="live" -> state "active"."""
    status_data = {
        "onboarding_complete": True,
        "llm_configured": True,
        "channels_configured": True,
    }
    dormant_data = [
        {"key": "redline_surface", "status": "live"},
        {"key": "attribute_editor", "status": "live"},
        {"key": "criteria_editor", "status": "live"},
        {"key": "chatbot", "status": "live"},
        {"key": "assistant_memory", "status": "live"},
        {"key": "saved_playbooks", "status": "live"},
        {"key": "curation_approvals", "status": "live"},
        {"key": "digest_in_app", "status": "live"},
        {"key": "debug_surface", "status": "live"},
        {"key": "tool_toggle_registry", "status": "live"},
        {"key": "update_button", "status": "live"},
        {"key": "remote_takeover", "status": "live"},
        {"key": "desktop_assist", "status": "live"},
        {"key": "multi_campaign_switcher", "status": "live"},
    ]

    def _fake_forward(method, path, body=None, timeout=10):
        if path == "/api/setup/status":
            return {"ok": True, "status": 200, "data": status_data}
        if path == "/api/dormant-surfaces":
            return {"ok": True, "status": 200, "data": dormant_data}
        return {"ok": False, "status": 0, "error": "unexpected"}

    with patch.object(feats, "_forward", side_effect=_fake_forward):
        result = feats.compute_features()

    assert result["engine_available"] is True
    sections = result["sections"]
    # Sections with requires=onboarding_complete and all dormant_keys live -> active
    assert sections["documents"]["state"] == "active"
    assert sections["memory"]["state"] == "active"
    # Sections with requires=llm_configured and all dormant_keys live -> active
    assert sections["chat"]["state"] == "active"
    assert sections["mind"]["state"] == "active"
    assert sections["debug"]["state"] == "active"
    assert sections["update"]["state"] == "active"
    assert sections["takeover"]["state"] == "active"
    assert sections["desktop_assist"]["state"] == "active"
    assert sections["multi_campaign_switcher"]["state"] == "active"
    # Sections with requires=channels_configured and all dormant_keys live -> active
    assert sections["email"]["state"] == "active"
    # Sections with empty dormant_keys (no dormant gate) and requires met -> active
    assert sections["vault"]["state"] == "active"
    assert sections["gallery"]["state"] == "active"
    assert sections["compare"]["state"] == "active"
    assert sections["results"]["state"] == "active"


# ── test_configured (via _section_state directly) ────────────────


def test_configured_via_section_state(feats):
    """Gate predicate true, backing live, but engine_up=False -> 'configured'.
    This tests _section_state directly since compute_features cannot reach
    configured without the last-known-good cache."""
    section = {
        "key": "chat",
        "lane": "C",
        "title": "Chat / assistant (job actions)",
        "nav_ids": ["tool-assistant-btn", "rail-assistant"],
        "dormant_keys": ["chatbot"],
        "requires": "llm_configured",
        "present_but_disabled": False,
    }
    status = {"llm_configured": True}
    dormant_by_key = {"chatbot": {"key": "chatbot", "status": "live"}}

    state = feats._section_state(
        section,
        engine_up=False,
        status=status,
        dormant_by_key=dormant_by_key,
    )
    assert state == "configured"


def test_configured_via_section_state_empty_dormant_keys(feats):
    """Section with no dormant_keys, gate met, engine_down -> configured."""
    section = {
        "key": "vault",
        "lane": None,
        "title": "Credential vault",
        "nav_ids": ["settings-open-vault"],
        "dormant_keys": [],
        "requires": "onboarding_complete",
        "present_but_disabled": False,
    }
    status = {"onboarding_complete": True}

    state = feats._section_state(
        section,
        engine_up=False,
        status=status,
        dormant_by_key={},
    )
    assert state == "configured"


# ── test_locked ───────────────────────────────────────────────────


def test_locked_gate_false(feats):
    """Gate predicate false (requires llm_configured but llm_configured=False) -> locked."""
    status_data = {
        "onboarding_complete": True,
        "llm_configured": False,
        "channels_configured": False,
    }
    dormant_data = [
        {"key": "redline_surface", "status": "live"},
        {"key": "attribute_editor", "status": "live"},
        {"key": "criteria_editor", "status": "live"},
        {"key": "chatbot", "status": "live"},
        {"key": "digest_in_app", "status": "live"},
    ]

    def _fake_forward(method, path, body=None, timeout=10):
        if path == "/api/setup/status":
            return {"ok": True, "status": 200, "data": status_data}
        if path == "/api/dormant-surfaces":
            return {"ok": True, "status": 200, "data": dormant_data}
        return {"ok": False, "status": 0, "error": "unexpected"}

    with patch.object(feats, "_forward", side_effect=_fake_forward):
        result = feats.compute_features()

    assert result["engine_available"] is True
    sections = result["sections"]
    # Sections that require llm_configured should be locked
    assert sections["chat"]["state"] == "locked"
    assert sections["mind"]["state"] == "locked"
    assert sections["email"]["state"] == "locked"  # channels_configured=False
    assert sections["debug"]["state"] == "locked"
    assert sections["update"]["state"] == "locked"
    assert sections["takeover"]["state"] == "locked"
    assert sections["desktop_assist"]["state"] == "locked"
    assert sections["multi_campaign_switcher"]["state"] == "locked"
    assert sections["gallery"]["state"] == "locked"
    assert sections["compare"]["state"] == "locked"
    assert sections["results"]["state"] == "locked"
    # Sections that require onboarding_complete which IS met -> should still be active
    # because onboarding_complete=True and dormant_keys are live
    assert sections["documents"]["state"] == "active"
    assert sections["memory"]["state"] == "active"
    assert sections["vault"]["state"] == "active"


# ── test_disabled ─────────────────────────────────────────────────


def test_disabled_via_section_state(feats):
    """Section with present_but_disabled=True -> 'disabled' regardless of other args."""
    disabled_section = {
        "key": "legacy",
        "lane": None,
        "title": "Legacy feature",
        "nav_ids": [],
        "dormant_keys": [],
        "requires": "onboarding_complete",
        "present_but_disabled": True,
    }

    result = feats._section_state(
        disabled_section,
        engine_up=True,
        status={"onboarding_complete": True},
        dormant_by_key={},
    )
    assert result == "disabled"

    result2 = feats._section_state(
        disabled_section,
        engine_up=False,
        status=None,
        dormant_by_key=None,
    )
    assert result2 == "disabled"


# ── test_engine_down_never_raises ────────────────────────────────


def test_engine_down_never_raises(feats):
    """Both endpoints fail -> engine_available=False, all sections locked, no exception."""

    def _fake_forward(method, path, body=None, timeout=10):
        return {"ok": False, "status": 0, "error": "URLError: Connection refused"}

    with patch.object(feats, "_forward", side_effect=_fake_forward):
        result = feats.compute_features()

    assert result["engine_available"] is False
    assert "engine_url" in result
    assert isinstance(result["engine_url"], str)
    sections = result["sections"]
    for key in sections:
        assert sections[key]["state"] == "locked"


# ── test_returns_correct_structure ───────────────────────────────


def test_returns_correct_structure(feats):
    """Verify the payload shape: engine_available, engine_url, sections as dict."""

    def _fake_forward(method, path, body=None, timeout=10):
        if path == "/api/setup/status":
            return {"ok": True, "status": 200, "data": {"llm_configured": False}}
        if path == "/api/dormant-surfaces":
            return {"ok": True, "status": 200, "data": []}
        return {"ok": False, "status": 0, "error": "unexpected"}

    with patch.object(feats, "_forward", side_effect=_fake_forward):
        result = feats.compute_features()

    # Top-level keys
    assert "engine_available" in result
    assert "engine_url" in result
    assert "sections" in result
    assert isinstance(result["sections"], dict)
    assert len(result["sections"]) == 14

    # Each section has the required keys
    for key, sec in result["sections"].items():
        assert isinstance(sec, dict)
        assert "key" in sec
        assert "title" in sec
        assert "lane" in sec
        assert "state" in sec
        assert "nav_ids" in sec
        assert isinstance(sec["nav_ids"], list)
        assert "requirement" in sec
        assert "present_but_disabled" in sec
        assert sec["key"] == key

    # Verify specific section keys exist
    section_keys = set(result["sections"].keys())
    expected_keys = {
        "documents", "memory", "chat", "mind", "email",
        "debug", "update", "takeover", "vault", "desktop_assist",
        "multi_campaign_switcher", "gallery", "compare", "results",
    }
    assert section_keys == expected_keys


# ── test_requirement_met ──────────────────────────────────────────


def test_requirement_met_true(feats):
    assert feats._requirement_met("llm_configured", {"llm_configured": True}) is True


def test_requirement_met_false(feats):
    assert feats._requirement_met("llm_configured", {"llm_configured": False}) is False


def test_requirement_met_none(feats):
    assert feats._requirement_met(None, {"llm_configured": False}) is True


def test_requirement_met_missing_key(feats):
    assert feats._requirement_met("missing_key", {"llm_configured": True}) is False


# ── test_dormant_live ─────────────────────────────────────────────


def test_dormant_live_all_live(feats):
    dormant_by_key = {"chatbot": {"key": "chatbot", "status": "live"}}
    assert feats._dormant_live(["chatbot"], dormant_by_key) is True


def test_dormant_live_one_not_live(feats):
    dormant_by_key = {
        "attribute_editor": {"key": "attribute_editor", "status": "live"},
        "criteria_editor": {"key": "criteria_editor", "status": "dormant"},
    }
    assert feats._dormant_live(["attribute_editor", "criteria_editor"], dormant_by_key) is False


def test_dormant_live_empty_keys(feats):
    assert feats._dormant_live([], {}) is True


def test_dormant_live_missing_key(feats):
    assert feats._dormant_live(["nonexistent"], {"chatbot": {"key": "chatbot", "status": "live"}}) is False
