"""Reachability + real data for the pre-fill diagnostics route (dark-engine audit #34).

``PrefillService.diagnostics()`` is a bounded, deduped ring of operator-visible
credential/LLM/login failure messages recorded so a silent degradation is
"surfaced rather than lost" (its own docstring) — but until this route existed
nothing read it. Proves the wired endpoint end-to-end (registered + reachable)
and that it returns REAL ring contents (not a fabricated/empty stub), sourced
from the same process-lived ``container.prefill_service`` instance.

Hermetic: in-memory storage, real container services, LLM gate opened like the
peer router tests (test_gallery_router.py).
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from applicant.app.main import create_app


@pytest.fixture
def client():
    with TestClient(create_app()) as c:
        # Open the LLM gate (the router carries require_llm_configured).
        r = c.post(
            "/api/setup/llm",
            json={"provider": "ollama", "base_url": "http://localhost:11434/v1", "model": "llama3.1"},
        )
        assert r.status_code == 204
        yield c


def _registered_paths(app) -> set[str]:
    paths: set[str] = set()
    for r in app.routes:
        p = getattr(r, "path", None)
        if p:
            paths.add(p)
        orig = getattr(r, "original_router", None)
        if orig is not None:
            for sub in getattr(orig, "routes", []):
                sp = getattr(sub, "path", None)
                if sp:
                    paths.add(sp)
    return paths


def test_prefill_diagnostics_route_is_registered(client):
    paths = _registered_paths(client.app)
    assert "/api/admin/prefill-diagnostics" in paths


def test_prefill_diagnostics_empty_ring_is_well_formed(client):
    r = client.get("/api/admin/prefill-diagnostics")
    assert r.status_code == 200
    body = r.json()
    assert body == {"diagnostics": [], "status": "live"}


def test_prefill_diagnostics_returns_real_ring_contents(client):
    # Drive the SAME process-lived PrefillService instance the route reads from
    # (container.prefill_service) so the response is proven to reflect real
    # ring state, not a fabricated/hardcoded value.
    container = client.app.state.container
    pf = container.prefill_service
    assert pf is not None
    pf._record_diagnostic("Every credential scope failed for tenant 'workday' (vault unreachable): boom")
    pf._record_diagnostic("LLM unavailable during field mapping: rate limited")

    r = client.get("/api/admin/prefill-diagnostics")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "live"
    assert body["diagnostics"] == [
        "Every credential scope failed for tenant 'workday' (vault unreachable): boom",
        "LLM unavailable during field mapping: rate limited",
    ]


def test_prefill_diagnostics_dedupes_immediate_repeat(client):
    # Matches PrefillService._record_diagnostic's own dedup contract: an
    # immediate repeat of the last message is dropped, not double-recorded.
    container = client.app.state.container
    pf = container.prefill_service
    pf._record_diagnostic("Browser error during login for application a1 (transient, not an auth rejection): boom")
    pf._record_diagnostic("Browser error during login for application a1 (transient, not an auth rejection): boom")

    r = client.get("/api/admin/prefill-diagnostics")
    assert r.json()["diagnostics"] == [
        "Browser error during login for application a1 (transient, not an auth rejection): boom"
    ]
