"""App-boot integration: app constructs, static resolves, LLM gate returns 409."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from applicant.app.main import create_app


@pytest.fixture
def client():
    app = create_app()
    with TestClient(app) as c:
        yield c


@pytest.mark.integration
def test_app_constructs_and_healthz(client):
    res = client.get("/healthz")
    assert res.status_code == 200
    assert res.json()["status"] == "ok"


@pytest.mark.integration
def test_wizard_static_resolves(client):
    res = client.get("/static/applicant/wizard.html")
    assert res.status_code == 200
    assert "Applicant setup" in res.text


@pytest.mark.integration
def test_vendored_asset_resolves(client):
    # A vendored Odysseus asset is served verbatim (FR-UI-1).
    res = client.get("/static/style.css")
    assert res.status_code == 200
    assert len(res.content) > 0


@pytest.mark.integration
def test_llm_gate_blocks_until_configured(client):
    # Gated route 409s before LLM is configured (FR-UI-5).
    res = client.get("/api/campaigns")
    assert res.status_code == 409

    # Configure the LLM via the OOBE settings endpoint.
    ok = client.post(
        "/api/setup/llm",
        json={"provider": "ollama", "base_url": "http://localhost:11434/v1", "model": "llama3.1"},
    )
    assert ok.status_code == 204

    # Now the gate is open.
    res2 = client.get("/api/campaigns")
    assert res2.status_code == 200


@pytest.mark.integration
def test_dormant_surfaces_exposed(client):
    res = client.get("/api/dormant-surfaces")
    assert res.status_code == 200
    keys = {s["key"] for s in res.json()}
    assert "redline_surface" in keys and "chatbot" in keys
