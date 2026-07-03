"""Hermetic tests for the cached-read research endpoint (dark-engine audit
item 38) — ``GET /api/research/{campaign_id}/cached``.

``ResearchService.cached_report(campaign_id, query)`` already returns an
already-paid-for report for free (no fresh run, no budget spent), but before
this change the ``research.py`` router only exposed ``run`` (which always goes
through the capped/deduped path and, on a cache miss, burns budget) and
``budget``. There was no way for a caller to just PEEK at whether a report is
already cached without invoking a run. This adds that peek.

In-memory storage (unreachable ``DATABASE_URL``), the LLM gate opened via the
setup endpoint, and the container's ``ResearchService`` swapped for one backed
by a fake ``WorkspacePort`` — no network, no real LLM. Mirrors the sibling
``tests/integration/test_research_endpoints.py`` fixtures.
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
    # Container is frozen after construction (#183); bypass with object.__setattr__ for test.
    object.__setattr__(
        client.app.state.container,
        "research_service",
        ResearchService(workspace=workspace, max_calls=max_calls),
    )


def _make_campaign(client) -> str:
    return client.post("/api/campaigns", json={"name": "C"}).json()["id"]


def test_cached_read_before_any_run_is_404(client):
    _open_gate(client)
    _set_research(client, _FakeWorkspace())
    cid = _make_campaign(client)
    resp = client.get(f"/api/research/{cid}/cached", params={"query": "Acme"})
    assert resp.status_code == 404


def test_cached_read_after_a_run_returns_the_report_for_free(client):
    _open_gate(client)
    ws = _FakeWorkspace()
    _set_research(client, ws)
    cid = _make_campaign(client)
    run_resp = client.post(f"/api/research/{cid}/run", json={"query": "Acme platform team"})
    assert run_resp.json()["budget_remaining"] == 2

    cached_resp = client.get(f"/api/research/{cid}/cached", params={"query": "Acme platform team"})
    assert cached_resp.status_code == 200
    body = cached_resp.json()
    assert body["summary"] == "report body"
    assert body["cached"] is True
    # The peek did not spend any additional budget (still 1 fresh call charged).
    assert body["budget_remaining"] == 2
    assert len(ws.calls) == 1


def test_cached_read_normalizes_the_query_like_the_run_path(client):
    """Whitespace/case differences must still hit the same cache entry — the
    cached-read key must match ``_normalize_query`` used by the run path,
    otherwise the UI's cache-peek would always miss for a query that differs
    only cosmetically from the one that was actually run."""
    _open_gate(client)
    _set_research(client, _FakeWorkspace())
    cid = _make_campaign(client)
    client.post(f"/api/research/{cid}/run", json={"query": "  Acme   Platform Team  "})
    resp = client.get(f"/api/research/{cid}/cached", params={"query": "acme platform team"})
    assert resp.status_code == 200


def test_cached_read_unknown_campaign_404(client):
    _open_gate(client)
    _set_research(client, _FakeWorkspace())
    resp = client.get(f"/api/research/{new_id()}/cached", params={"query": "q"})
    assert resp.status_code == 404


def test_cached_read_empty_query_422(client):
    _open_gate(client)
    _set_research(client, _FakeWorkspace())
    cid = _make_campaign(client)
    resp = client.get(f"/api/research/{cid}/cached", params={"query": "  "})
    assert resp.status_code == 422


def test_cached_read_does_not_consume_a_fresh_run_even_when_channel_off(client):
    """A cache hit must be servable even if the workspace channel later goes
    unavailable — reading a cache entry never re-touches the workspace."""
    _open_gate(client)
    ws = _FakeWorkspace(available=True)
    _set_research(client, ws)
    cid = _make_campaign(client)
    client.post(f"/api/research/{cid}/run", json={"query": "q"})
    # Flip the channel off after the run; the cached copy must still be readable.
    ws._available = False
    resp = client.get(f"/api/research/{cid}/cached", params={"query": "q"})
    assert resp.status_code == 200
    assert resp.json()["cached"] is True


def test_cached_read_gated_until_llm_configured(client):
    # No gate opened -> 409 from require_llm_configured, same as run/budget.
    resp = client.get(f"/api/research/{new_id()}/cached", params={"query": "q"})
    assert resp.status_code == 409
