"""Phase 4 surface integration tests over HTTP (hermetic).

Exercises the Phase 4 deliverables end-to-end against the in-process app:

* Tool registry list + toggle persists and is ENFORCED at dispatch (FR-UI-4):
  toggling Chat off 403s the chat endpoint; toggling it back on restores it.
* Debug / observability surface returns REAL data, not pending stubs (FR-OBS-2 /
  FR-LOG-3 / FR-UI-6): history, logs, variants endpoints.
* Chatbot proposes confirmation-gated changes and commits on confirm (FR-CHAT-1 /
  FR-FB-3).
* In-UI Update button is safe by default (FR-OOBE-4).
* UI serves the debug + chat surfaces and the dormant-surface registry exposes
  real status (FR-UI-2).
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from applicant.app.main import create_app


@pytest.fixture
def client():
    app = create_app()
    with TestClient(app) as c:
        c.post(
            "/api/setup/llm",
            json={"provider": "ollama", "base_url": "http://localhost:11434/v1", "model": "llama3.1"},
        )
        yield c


# === Tool registry / toggles (FR-UI-4) ====================================
@pytest.mark.integration
def test_tool_registry_lists_ten_tools_enabled(client):
    payload = client.get("/api/admin/tools").json()
    tools = payload["tools"]
    assert len(tools) == 10
    assert all(t["enabled"] for t in tools)


@pytest.mark.integration
def test_toggling_chat_off_disables_dispatch(client):
    # Chat works while enabled.
    ok = client.post("/api/chat", json={"campaign_id": "c-tool", "message": "hello"})
    assert ok.status_code == 200

    # Toggle the Chat tool off (FR-UI-4) — must be enforced at dispatch.
    off = client.post("/api/admin/tools/chat?enabled=false")
    assert off.status_code == 200 and off.json()["enabled"] is False

    blocked = client.post("/api/chat", json={"campaign_id": "c-tool", "message": "hello"})
    assert blocked.status_code == 403  # dispatch rejected (FR-UI-4)

    # Toggle back on — dispatch restored.
    on = client.post("/api/admin/tools/chat?enabled=true")
    assert on.status_code == 200 and on.json()["enabled"] is True
    restored = client.post("/api/chat", json={"campaign_id": "c-tool", "message": "hi"})
    assert restored.status_code == 200


@pytest.mark.integration
def test_unknown_tool_toggle_404s(client):
    assert client.post("/api/admin/tools/nope?enabled=false").status_code == 404


@pytest.mark.integration
def test_toggling_generation_tools_off_blocks_those_endpoints(client):
    # Cover-letter generation off -> the endpoint 403s (FR-UI-4).
    client.post("/api/admin/tools/cover_letter_generation?enabled=false")
    blocked = client.post(
        "/api/documents/cover-letter",
        json={"campaign_id": "c1", "application_id": "a1", "true_source": "x", "role_requires": True},
    )
    assert blocked.status_code == 403

    # Screening-answer generation off -> the endpoint 403s.
    client.post("/api/admin/tools/screening_answer_generation?enabled=false")
    blocked2 = client.post(
        "/api/documents/screening-answer",
        json={"campaign_id": "c1", "application_id": "a1", "question": "Why?", "true_source": "x"},
    )
    assert blocked2.status_code == 403


# === Debug / observability surface (FR-OBS-2 / FR-LOG-3) ==================
@pytest.mark.integration
def test_debug_history_and_logs_return_real_data(client):
    # History for an empty campaign is an explicit empty list (not a fake row).
    hist = client.get("/api/admin/history/c-empty").json()
    assert hist["applications"] == []

    # Logs endpoint is live (not pending) and returns redacted structured entries.
    logs = client.get("/api/admin/logs?limit=10").json()
    assert logs["status"] == "live"
    assert isinstance(logs["entries"], list)

    # Screenshots endpoint is live and empty for an unknown application.
    shots = client.get("/api/admin/screenshots/app-x").json()
    assert shots["status"] == "live"
    assert shots["screenshots"] == []

    # Variant library is live and empty for an empty campaign.
    variants = client.get("/api/admin/variants/c-empty").json()
    assert variants["variants"] == []


@pytest.mark.integration
def test_workflow_state_introspects_orchestrator(client):
    state = client.get("/api/admin/workflow/app-y").json()
    assert state["workflow_id"] == "application:app-y"
    assert "completed_steps" in state
    assert state["pending_recovery"] is False


# === Chatbot (FR-CHAT-1 / FR-FB-3) ========================================
@pytest.mark.integration
def test_chatbot_identifies_gaps_and_gates_integral_change(client):
    cid = "c-chat"
    r = client.post(
        "/api/chat", json={"campaign_id": cid, "message": "my first name is Kevin"}
    ).json()
    # Gaps are surfaced (FR-CHAT-1).
    assert "first name" in r["gaps"]
    # The integral first-name change is proposed but NOT auto-applied (FR-FB-3).
    proposals = r["proposed_changes"]
    assert proposals and proposals[0]["requires_confirmation"] is True
    assert proposals[0]["applied"] is False

    # Confirm commits it (FR-FB-3).
    confirmed = client.post(
        "/api/chat/confirm", json={"campaign_id": cid, "name": "first name", "value": "Kevin"}
    )
    assert confirmed.status_code == 200 and confirmed.json()["committed"] is True


@pytest.mark.integration
def test_chatbot_autoapplies_non_integral_change(client):
    cid = "c-chat2"
    r = client.post(
        "/api/chat", json={"campaign_id": cid, "message": "my years of python is 8"}
    ).json()
    proposals = r["proposed_changes"]
    assert proposals and proposals[0]["applied"] is True
    assert proposals[0]["requires_confirmation"] is False


# === In-UI Update button (FR-OOBE-4) ======================================
@pytest.mark.integration
def test_update_trigger_safe_by_default(client, monkeypatch):
    monkeypatch.delenv("APPLICANT_UPDATE_ENABLED", raising=False)
    r = client.post("/api/update/trigger").json()
    assert r["started"] is False
    assert r["message"]


# === UI surfaces + dormant registry (FR-UI-2 / FR-UI-6) ===================
@pytest.mark.integration
def test_debug_and_chat_surfaces_served(client):
    debug = client.get("/debug").text
    assert "tools-section" in debug
    # FR-STEALTH-5: the honest caveat is surfaced in the debug UI.
    assert "stealth-section" in debug
    assert "chat-section" in client.get("/chat").text


# === Criteria + attribute editor surfaces (FR-UI-6 / FR-CRIT / FR-ATTR / FR-FB-3) ===
@pytest.mark.integration
def test_criteria_and_attribute_surfaces_served(client):
    crit = client.get("/criteria").text
    assert "criteria-section" in crit
    assert "Learned adjustments" in crit  # learned-but-overridable surfaced
    attrs = client.get("/attributes").text
    assert "attributes-section" in attrs
    # Equal-opportunity policy is surfaced in plain language.
    assert "never auto-filled" in attrs


@pytest.mark.integration
def test_criteria_integral_edit_is_confirmation_gated(client):
    # FR-FB-3: an integral criteria change (titles) without confirm 409s; with
    # confirm it applies — the surface routes the 409 path to a re-ask + retry.
    cid = "c-crit"
    blocked = client.put(
        f"/api/criteria/{cid}", json={"titles": ["Staff Engineer"], "confirm": False}
    )
    assert blocked.status_code == 409
    ok = client.put(
        f"/api/criteria/{cid}", json={"titles": ["Staff Engineer"], "confirm": True}
    )
    assert ok.status_code == 200


@pytest.mark.integration
def test_attribute_integral_edit_is_confirmation_gated(client):
    # FR-FB-3: an integral attribute upsert without confirm 409s; with confirm 201.
    cid = "c-attr"
    blocked = client.post(
        "/api/attributes",
        json={"campaign_id": cid, "name": "First Name", "value": "Kevin", "is_integral": True},
    )
    assert blocked.status_code == 409
    ok = client.post(
        "/api/attributes",
        json={
            "campaign_id": cid,
            "name": "First Name",
            "value": "Kevin",
            "is_integral": True,
            "confirm": True,
        },
    )
    assert ok.status_code == 201


# CRIT-profile: explicit attribute delete (FR-ATTR-3).
@pytest.mark.integration
def test_attribute_delete_removes_it(client):
    cid = "c-attr-del"
    made = client.post(
        "/api/attributes",
        json={"campaign_id": cid, "name": "Phone", "value": "+1 555 0100"},
    )
    assert made.status_code == 201
    attr_id = made.json()["id"]
    assert any(a["id"] == attr_id for a in client.get(f"/api/attributes/{cid}").json()["items"])

    deleted = client.delete(f"/api/attributes/{cid}/{attr_id}")
    assert deleted.status_code == 200
    assert deleted.json() == {"deleted": True, "id": attr_id}
    assert not any(a["id"] == attr_id for a in client.get(f"/api/attributes/{cid}").json()["items"])


# === Stealth honesty caveat + egress (FR-STEALTH-4 / FR-STEALTH-5) ========
@pytest.mark.integration
def test_stealth_endpoint_surfaces_caveat_and_egress(client):
    body = client.get("/api/admin/stealth").json()
    # FR-STEALTH-5: the honest best-effort caveat is returned by the endpoint.
    assert "best-effort" in body["caveat"]
    assert body["egress_caveat"]
    # FR-STEALTH-4: the live egress posture is reported (default: direct residential).
    assert body["egress"]["mode"] == "direct"
    assert body["egress"]["is_direct_residential"] is True
    assert body["egress"]["proxy_configured"] is False


@pytest.mark.integration
def test_dormant_registry_exposes_real_status(client):
    rows = {r["key"]: r for r in client.get("/api/dormant-surfaces").json()}
    # Surfaces whose backend now exists report live.
    assert rows["debug_surface"]["status"] == "live"
    assert rows["chatbot"]["status"] == "live"
    assert rows["tool_toggle_registry"]["status"] == "live"
    # Genuinely dormant surfaces stay dormant.
    assert rows["resume_aggressiveness"]["status"] == "dormant"
    assert rows["multi_campaign_switcher"]["status"] == "dormant"
