"""Integration tests for the manual research-trigger router (Lane B, Stage 2.5).

Hermetic: in-memory storage, the LLM gate opened via the setup endpoint, and the
container's ResearchService swapped for one backed by a fake WorkspacePort (no
network / no real LLM). Covers the owner-scoped manual run, the budget surfaced in
the response, and graceful degrade (200 + unavailable) when the channel is off.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from applicant.app.main import create_app
from applicant.application.services.research_service import ResearchService
from applicant.core.ids import new_id


class _FakeWorkspace:
    def __init__(self, *, available=True):
        self._available = available
        self.calls = []

    def available(self):
        return self._available

    def run_research(self, **kwargs):
        self.calls.append(kwargs)
        return {
            "query": kwargs["query"],
            "summary": "report body",
            "key_findings": ["k1"],
            "sources": [{"url": "https://x", "title": "X"}],
        }


@pytest.fixture
def client():
    app = create_app()
    with TestClient(app) as c:
        yield c


def _open_gate(client):
    assert (
        client.post(
            "/api/setup/llm",
            json={"provider": "ollama", "base_url": "http://x/v1", "model": "llama3.1"},
        ).status_code
        == 204
    )


def _set_research(client, workspace, *, max_calls=3):
    client.app.state.container.research_service = ResearchService(
        workspace=workspace, max_calls=max_calls
    )


def _make_campaign(client) -> str:
    return client.post("/api/campaigns", json={"name": "C"}).json()["id"]


@pytest.mark.integration
def test_manual_run_returns_report(client):
    _open_gate(client)
    ws = _FakeWorkspace()
    _set_research(client, ws)
    cid = _make_campaign(client)
    resp = client.post(f"/api/research/{cid}/run", json={"query": "Acme", "company": "Acme"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["summary"] == "report body"
    assert body["cached"] is False
    assert body["budget_remaining"] == 2
    assert ws.calls[0]["company"] == "Acme"


@pytest.mark.integration
def test_manual_run_cache_hit_is_free(client):
    _open_gate(client)
    ws = _FakeWorkspace()
    _set_research(client, ws)
    cid = _make_campaign(client)
    client.post(f"/api/research/{cid}/run", json={"query": "q"})
    second = client.post(f"/api/research/{cid}/run", json={"query": "q"}).json()
    assert second["cached"] is True
    assert len(ws.calls) == 1  # deduped
    assert second["budget_remaining"] == 2  # cache hit didn't charge budget


@pytest.mark.integration
def test_manual_run_degrades_when_channel_off(client):
    _open_gate(client)
    _set_research(client, _FakeWorkspace(available=False))
    cid = _make_campaign(client)
    resp = client.post(f"/api/research/{cid}/run", json={"query": "q"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["unavailable"] is True
    assert body["reason"] == "workspace_unavailable"


@pytest.mark.integration
def test_manual_run_unknown_campaign_404(client):
    _open_gate(client)
    _set_research(client, _FakeWorkspace())
    resp = client.post(f"/api/research/{new_id()}/run", json={"query": "q"})
    assert resp.status_code == 404


@pytest.mark.integration
def test_manual_run_empty_query_422(client):
    _open_gate(client)
    _set_research(client, _FakeWorkspace())
    cid = _make_campaign(client)
    assert client.post(f"/api/research/{cid}/run", json={"query": " "}).status_code == 422


@pytest.mark.integration
def test_budget_endpoint(client):
    _open_gate(client)
    _set_research(client, _FakeWorkspace(), max_calls=3)
    cid = _make_campaign(client)
    client.post(f"/api/research/{cid}/run", json={"query": "q"})
    b = client.get(f"/api/research/{cid}/budget").json()
    assert b["available"] is True
    assert b["calls_made"] == 1
    assert b["budget_remaining"] == 2


@pytest.mark.integration
def test_research_router_gated_until_llm_configured(client):
    # No gate opened -> 409 from require_llm_configured.
    resp = client.post(f"/api/research/{new_id()}/run", json={"query": "q"})
    assert resp.status_code == 409