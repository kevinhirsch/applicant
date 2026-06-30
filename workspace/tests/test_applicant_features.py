"""Hermetic tests for the Applicant feature-state layer (src/applicant_features.py).

The engine is mocked with an ``httpx.MockTransport`` that routes by path, so we
drive every section state — active / configured / locked / disabled — with no
network. Also covers the engine-down degrade path and the Compare
present-but-disabled rule.
"""

import httpx

from src.applicant_features import (
    APPLICANT_SECTIONS,
    STATE_ACTIVE,
    STATE_DISABLED,
    STATE_LOCKED,
    compute_features,
)


def _router(*, healthz_ok=True, status=None, dormant=None, fail_status=False):
    """Build a MockTransport handler keyed on request path."""

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/healthz":
            if healthz_ok:
                return httpx.Response(200, json={"status": "ok"})
            raise httpx.ConnectError("refused", request=request)
        if path == "/api/setup/status":
            if fail_status:
                return httpx.Response(500, text="boom")
            return httpx.Response(200, json=status or {})
        if path == "/api/dormant-surfaces":
            return httpx.Response(200, json=dormant or [])
        return httpx.Response(404, text="unmapped")

    return httpx.MockTransport(handler)


ALL_LIVE = [
    {"key": "redline_surface", "status": "live"},
    {"key": "attribute_editor", "status": "live"},
    {"key": "criteria_editor", "status": "live"},
    {"key": "chatbot", "status": "live"},
    {"key": "digest_in_app", "status": "live"},
]

FULLY_CONFIGURED = {
    "llm_configured": True,
    "channels_configured": True,
    "onboarding_complete": True,
    "gate_open": True,
}


def _features(transport):
    return compute_features(base_url="http://api:8000", transport=transport)


def test_payload_shape_and_compare_engine_backed():
    out = _features(_router(status=FULLY_CONFIGURED, dormant=ALL_LIVE))
    assert set(out) == {"engine_available", "engine_url", "sections"}
    assert out["engine_url"] == "http://api:8000"
    # Every registered section is present.
    assert set(out["sections"]) == {s["key"] for s in APPLICANT_SECTIONS}
    # Compare is now engine-backed (#297): no longer present-but-disabled; it
    # activates with the other llm-gated surfaces when a model is configured.
    compare = out["sections"]["compare"]
    assert compare["present_but_disabled"] is False
    assert compare["state"] == STATE_ACTIVE
    assert compare["lane"] is None


def test_all_active_when_engine_up_and_configured():
    out = _features(_router(healthz_ok=True, status=FULLY_CONFIGURED, dormant=ALL_LIVE))
    assert out["engine_available"] is True
    for key in ("documents", "memory", "chat", "email"):
        assert out["sections"][key]["state"] == STATE_ACTIVE, key
    # Compare is engine-backed now — it activates with the rest.
    assert out["sections"]["compare"]["state"] == STATE_ACTIVE


def test_sections_locked_when_gates_not_met():
    # Engine up + all surfaces live, but nothing configured -> gated sections lock.
    out = _features(_router(healthz_ok=True, status={}, dormant=ALL_LIVE))
    assert out["engine_available"] is True
    for key in ("documents", "memory", "chat", "email"):
        assert out["sections"][key]["state"] == STATE_LOCKED, key


def test_partial_gates_activate_only_matching_sections():
    # Only LLM configured -> chat active; the rest stay locked.
    status = {"llm_configured": True}
    out = _features(_router(healthz_ok=True, status=status, dormant=ALL_LIVE))
    assert out["sections"]["chat"]["state"] == STATE_ACTIVE
    assert out["sections"]["documents"]["state"] == STATE_LOCKED
    assert out["sections"]["email"]["state"] == STATE_LOCKED


def test_dormant_not_live_keeps_section_locked():
    # Gate met but the engine surface is still dormant -> locked.
    dormant = [{"key": "chatbot", "status": "dormant"}]
    out = _features(_router(healthz_ok=True, status={"llm_configured": True}, dormant=dormant))
    assert out["sections"]["chat"]["state"] == STATE_LOCKED


def test_engine_down_degrades_to_locked_never_raises():
    out = _features(_router(healthz_ok=False))
    assert out["engine_available"] is False
    for key in ("documents", "memory", "chat", "email"):
        assert out["sections"][key]["state"] == STATE_LOCKED, key
    # Compare is engine-backed now, so it degrades to locked with the rest when
    # the engine is unreachable (no longer a standalone present-but-disabled).
    assert out["sections"]["compare"]["state"] == STATE_LOCKED


def test_status_error_degrades_without_raising():
    # /healthz ok but /api/setup/status 500s -> no status data -> locked.
    out = _features(_router(healthz_ok=True, fail_status=True, dormant=ALL_LIVE))
    assert out["engine_available"] is True
    assert out["sections"]["documents"]["state"] == STATE_LOCKED


def test_nav_ids_and_requirement_exposed():
    out = _features(_router(status=FULLY_CONFIGURED, dormant=ALL_LIVE))
    docs = out["sections"]["documents"]
    assert "rail-documents" in docs["nav_ids"]
    assert docs["requirement"] == "onboarding_complete"
    assert docs["lane"] == "A"
