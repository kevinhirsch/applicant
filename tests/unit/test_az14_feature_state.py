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
    """Engine up, gate predicate true, dormant surface live -> state 'active'."""
    status_data = {"llm_configured": True, "resume_ready": True, "jobs_ready": True, "apply_ready": True}
    dormant_data = [
        {"key": "interviews", "live": True},
        {"key": "resumes", "live": True},
        {"key": "jobs", "live": False},
        {"key": "applications", "live": True},
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
    sections = {s["key"]: s["state"] for s in result["sections"]}
    assert sections["chat"] == "active"  # llm_configured=True, interviews.live=True
    assert sections["resumes"] == "active"  # resume_ready=True, resumes.live=True
    assert sections["jobs"] == "configured"  # jobs_ready=True, jobs.live=False
    assert sections["applications"] == "active"  # apply_ready=True, applications.live=True


# ── test_configured ───────────────────────────────────────────────


def test_configured(feats):
    """Gate predicate true, engine up, but dormant not live -> 'configured'."""
    status_data = {"llm_configured": True, "resume_ready": True, "jobs_ready": True, "apply_ready": True}
    dormant_data = []  # empty list = no dormant surfaces live

    def _fake_forward(method, path, body=None, timeout=10):
        if path == "/api/setup/status":
            return {"ok": True, "status": 200, "data": status_data}
        if path == "/api/dormant-surfaces":
            return {"ok": True, "status": 200, "data": dormant_data}
        return {"ok": False, "status": 0, "error": "unexpected"}

    with patch.object(feats, "_forward", side_effect=_fake_forward):
        result = feats.compute_features()

    assert result["engine_available"] is True
    sections = {s["key"]: s["state"] for s in result["sections"]}
    for key in ("chat", "resumes", "jobs", "applications"):
        assert sections[key] == "configured", f"{key} should be configured, got {sections[key]}"


# ── test_locked ───────────────────────────────────────────────────


def test_locked(feats):
    """Gate predicate false -> 'locked'."""
    status_data = {"llm_configured": False, "resume_ready": False, "jobs_ready": False, "apply_ready": False}
    dormant_data = [
        {"key": "interviews", "live": True},
        {"key": "resumes", "live": True},
        {"key": "jobs", "live": True},
        {"key": "applications", "live": True},
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
    sections = {s["key"]: s["state"] for s in result["sections"]}
    for key in ("chat", "resumes", "jobs", "applications"):
        assert sections[key] == "locked", f"{key} should be locked, got {sections[key]}"


# ── test_disabled ─────────────────────────────────────────────────


def test_disabled(feats):
    """Section with present_but_disabled=True -> 'disabled'."""
    disabled_section = {
        "key": "legacy",
        "title": "Legacy",
        "requirement": "legacy_ready",
        "dormant_key": "legacy",
        "nav_ids": [],
        "present_but_disabled": True,
    }

    result = feats._section_state(
        disabled_section,
        status={"legacy_ready": True},
        dormant={"legacy": {"key": "legacy", "live": True}},
    )
    assert result["state"] == "disabled"

    # Even when gate predicate is false and dormant is empty, disabled wins
    result2 = feats._section_state(
        disabled_section,
        status={"legacy_ready": False},
        dormant={},
    )
    assert result2["state"] == "disabled"

    # Even when status is None
    result3 = feats._section_state(
        disabled_section,
        status=None,
        dormant=None,
    )
    assert result3["state"] == "disabled"


# ── test_engine_down_never_raises ────────────────────────────────


def test_engine_down_never_raises(feats):
    """Engine unreachable; both endpoints fail -> engine_available=False, all sections locked (except disabled), no exception."""

    def _fake_forward(method, path, body=None, timeout=10):
        return {"ok": False, "status": 0, "error": "URLError: Connection refused"}

    with patch.object(feats, "_forward", side_effect=_fake_forward):
        result = feats.compute_features()

    assert result["engine_available"] is False
    assert "engine_url" in result
    assert isinstance(result["engine_url"], str)
    sections = {s["key"]: s["state"] for s in result["sections"]}
    for key in ("chat", "resumes", "jobs", "applications"):
        assert sections[key] == "locked", f"{key} should be locked when engine down, got {sections[key]}"


# ── test_returns_correct_structure ───────────────────────────────


def test_returns_correct_structure(feats):
    """Verify the payload shape: engine_available, engine_url, sections with full keys."""

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
    assert isinstance(result["sections"], list)
    assert len(result["sections"]) == 4

    # Each section has the required keys (from APPLICANT_SECTIONS plus 'state')
    for sec in result["sections"]:
        assert isinstance(sec, dict)
        assert "key" in sec
        assert "title" in sec
        assert "state" in sec
        assert "requirement" in sec
        assert "dormant_key" in sec
        assert "nav_ids" in sec
        assert isinstance(sec["nav_ids"], list)
        assert "present_but_disabled" in sec

    # Verify specific section keys
    section_keys = {s["key"] for s in result["sections"]}
    assert section_keys == {"chat", "resumes", "jobs", "applications"}
