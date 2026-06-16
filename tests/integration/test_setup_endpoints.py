"""OOBE setup endpoints: tier ladder + wizard advance, zero-CLI (FR-OOBE, FR-LLM-3)."""

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
def test_status_then_configure_then_advance(client):
    s = client.get("/api/setup/status").json()
    assert s["gate_open"] is False
    assert s["current_step"] == "llm"

    r = client.post(
        "/api/setup/llm",
        json={"provider": "ollama", "base_url": "http://localhost:11434/v1", "model": "llama3.1"},
    )
    assert r.status_code == 204

    s2 = client.get("/api/setup/status").json()
    assert s2["gate_open"] is True
    assert s2["current_step"] == "channels"

    # Advance the channels gate (FR-OOBE-3).
    adv = client.post("/api/setup/advance/channels")
    assert adv.status_code == 200
    assert adv.json()["channels_configured"] is True


@pytest.mark.integration
def test_tier_ladder_crud(client):
    put = client.put(
        "/api/setup/llm/tiers",
        json={
            "tiers": [
                {"provider": "ollama", "base_url": "http://localhost:11434", "model": "llama3.1", "context_window": 8192},
                {"provider": "openrouter", "base_url": "https://openrouter.ai/api/v1", "model": "gpt-4o-mini", "api_key": "sk-x", "context_window": 128000},
            ]
        },
    )
    assert put.status_code == 204

    tiers = client.get("/api/setup/llm/tiers").json()["tiers"]
    assert len(tiers) == 2
    assert tiers[0]["model"] == "llama3.1"
    # Secret never echoed back.
    assert all("api_key" not in t for t in tiers)
    # Gate now open since a ladder exists.
    assert client.get("/api/setup/status").json()["gate_open"] is True


@pytest.mark.integration
def test_set_tiers_rejects_empty(client):
    r = client.put("/api/setup/llm/tiers", json={"tiers": []})
    assert r.status_code == 422  # pydantic min_length


@pytest.mark.integration
def test_advance_unknown_step_404(client):
    assert client.post("/api/setup/advance/bogus").status_code == 404
