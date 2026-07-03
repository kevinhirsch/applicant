"""Reachability + real data for the Reflexion lessons routes (dark-engine audit #44).

``LearningService.reflect_on_failure``/``recall_lessons`` distilled a per-ATS
verbal lesson but nothing could ever LIST what had been learned — this proves the
wired ``GET /api/admin/lessons`` and ``GET /api/admin/lessons/{ats}`` endpoints
end-to-end (registered + reachable) and that they return REAL ledger contents
(not a fabricated/empty stub), sourced from the same process-lived
``container.learning_service`` instance the pre-fill loop reflects into.

Hermetic: in-memory storage, real container services, LLM gate opened like the
peer router tests (test_prefill_diagnostics_route.py).
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


def test_lessons_routes_are_registered(client):
    paths = _registered_paths(client.app)
    assert "/api/admin/lessons" in paths
    assert "/api/admin/lessons/{ats}" in paths


def test_all_lessons_empty_is_well_formed(client):
    r = client.get("/api/admin/lessons")
    assert r.status_code == 200
    assert r.json() == {"lessons": {}, "status": "live"}


def test_lessons_for_unknown_ats_is_empty_not_error(client):
    r = client.get("/api/admin/lessons/never-seen.example")
    assert r.status_code == 200
    assert r.json() == {"ats": "never-seen.example", "lessons": [], "status": "live"}


def test_lessons_reflect_real_ledger_contents(client):
    # Drive the SAME process-lived LearningService instance the route reads from
    # (container.learning_service) so the response is proven to reflect real
    # ledger state, not a fabricated/hardcoded value.
    container = client.app.state.container
    learning = container.learning_service
    assert learning is not None
    learning.reflect_on_failure(
        {"ats": "greenhouse.io", "step": "resume_upload", "error": "locator not found"}
    )
    learning.reflect_on_failure(
        {"ats": "workday.com", "step": "captcha", "error": "unsolved"}
    )

    r_all = client.get("/api/admin/lessons")
    assert r_all.status_code == 200
    body_all = r_all.json()
    assert body_all["status"] == "live"
    assert set(body_all["lessons"].keys()) == {"greenhouse.io", "workday.com"}
    assert body_all["lessons"]["greenhouse.io"][0]["step"] == "resume_upload"
    assert "locator not found" in body_all["lessons"]["greenhouse.io"][0]["lesson"]

    r_one = client.get("/api/admin/lessons/greenhouse.io")
    assert r_one.status_code == 200
    body_one = r_one.json()
    assert body_one["ats"] == "greenhouse.io"
    assert len(body_one["lessons"]) == 1
    assert body_one["lessons"][0]["step"] == "resume_upload"
    assert "locator not found" in body_one["lessons"][0]["lesson"]

    # A DIFFERENT ats never reflected on stays empty (never fabricated).
    r_other = client.get("/api/admin/lessons/workday.com")
    assert len(r_other.json()["lessons"]) == 1
    r_missing = client.get("/api/admin/lessons/not-recorded.example")
    assert r_missing.json()["lessons"] == []
