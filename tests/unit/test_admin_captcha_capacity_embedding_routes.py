"""Coverage: ``GET /api/admin/captcha-status`` / ``/capacity`` / ``/embedding-backend``
(dark-engine audit B7 items #67, #72, #79).

* #67 — the captcha strategy is configurable (``CAPTCHA_STRATEGY``) and the
  composite solver (``CaptchaSolver``) decides avoid/solve/handoff, but nothing
  reported the effective strategy or whether it is doing anything. The shipped
  default (``human``) never even builds a solver (``container.py``'s
  ``_build_captcha_solver``), so the route must report ``active: False`` and
  must NOT fabricate attempt/outcome counts that were never tracked; once a
  non-default strategy IS configured, the route must reflect the composite
  solver's real, process-lived counters.
* #72 — ``CapacityService`` admits/defers a sandbox slot every tick via the
  orchestrator's ``SANDBOX_QUEUE``; the route must reflect the SAME live queue
  the scheduler drives, not a fabricated snapshot.
* #79 — ``LocalEmbedding`` is a deterministic offline hashing-trick backend;
  the route must disclose that plainly rather than staying silent.

Two layers, mirroring existing peers:
* direct-function tests against a fake ``Container`` (like
  ``test_admin_workspace_bridge_router.py``) for the defensive/no-service paths;
* a real ``TestClient(create_app())`` end-to-end test (like
  ``test_admin_routines_route.py``) proving the route is registered and reads
  the REAL, process-lived container services.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from applicant.app.main import create_app
from applicant.app.routers.admin import capacity, captcha_status, embedding_backend
from applicant.ports.driven.captcha import CaptchaContext, CaptchaKind

# === direct-function / defensive-path tests =================================


class _FakeSettings:
    captcha_strategy = "human"
    captcha_service = "capsolver"
    captcha_api_key = ""


class _FakeContainerNothingWired:
    settings = _FakeSettings()
    prefill_service = None
    capacity_service = None
    embedding = None


@pytest.mark.unit
def test_captcha_status_defensive_when_prefill_service_missing():
    out = captcha_status(container=_FakeContainerNothingWired())
    assert out["strategy"] == "human"
    assert out["service"] == "capsolver"
    assert out["key_configured"] is False
    assert out["active"] is False
    assert "attempts" not in out  # never fabricate a count that isn't tracked
    assert out["status"] == "live"


@pytest.mark.unit
def test_capacity_defensive_when_capacity_service_missing():
    out = capacity(container=_FakeContainerNothingWired())
    assert out == {
        "active": [],
        "waiting": [],
        "active_count": 0,
        "waiting_count": 0,
        "supported": False,
        "status": "live",
    }


@pytest.mark.unit
def test_embedding_backend_defensive_when_embedding_missing():
    out = embedding_backend(container=_FakeContainerNothingWired())
    assert out["backend"] == "none"
    assert out["quality_tier"] == "unknown"
    assert out["model_backed"] is False
    assert out["status"] == "live"


class _FakePrefillServiceWithSolver:
    def __init__(self, solver):
        self._solver = solver

    @property
    def captcha_solver(self):
        return self._solver


class _FakeCaptchaSolverNoStats:
    """Mirrors a solver that doesn't implement ``stats()`` (defensive path)."""

    strategy = "avoid"


@pytest.mark.unit
def test_captcha_status_tolerates_a_solver_without_stats():
    class _C:
        settings = _FakeSettings()
        prefill_service = _FakePrefillServiceWithSolver(_FakeCaptchaSolverNoStats())
        capacity_service = None
        embedding = None

    out = captcha_status(container=_C())
    assert out["active"] is True
    assert "attempts" not in out


# === real-container end-to-end tests ========================================


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


def test_new_b7_routes_are_registered(client):
    paths = _registered_paths(client.app)
    assert "/api/admin/captcha-status" in paths
    assert "/api/admin/capacity" in paths
    assert "/api/admin/embedding-backend" in paths


def test_captcha_status_reports_the_shipped_default_honestly(client):
    r = client.get("/api/admin/captcha-status")
    assert r.status_code == 200
    body = r.json()
    assert body["strategy"] == "human"
    assert body["active"] is False
    assert "attempts" not in body
    assert body["status"] == "live"


def test_captcha_status_reflects_real_counters_once_a_solver_is_wired(monkeypatch):
    monkeypatch.setenv("CAPTCHA_STRATEGY", "avoid")
    with TestClient(create_app()) as c:
        r = c.post(
            "/api/setup/llm",
            json={"provider": "ollama", "base_url": "http://localhost:11434/v1", "model": "llama3.1"},
        )
        assert r.status_code == 204

        body = c.get("/api/admin/captcha-status").json()
        assert body["strategy"] == "avoid"
        assert body["active"] is True
        assert body["attempts"] == 0
        assert body["solved"] == 0
        assert body["avoided"] == 0
        assert body["handed_off"] == 0

        # Drive the SAME process-lived solver the route reads from — the
        # exact real object the pre-fill loop calls (proves no fabrication).
        container = c.app.state.container
        solver = container.prefill_service.captcha_solver
        assert solver is not None
        solver.resolve(CaptchaContext(url="https://x", kind=CaptchaKind.TURNSTILE))

        body2 = c.get("/api/admin/captcha-status").json()
        assert body2["attempts"] == 1
        assert body2["avoided"] == 1
        assert body2["solved"] == 0
        assert body2["handed_off"] == 0


def test_capacity_reflects_the_real_live_sandbox_queue(client):
    container = client.app.state.container
    svc = container.capacity_service
    assert svc is not None
    concurrency = container.settings.sandbox_concurrency

    for i in range(concurrency):
        assert svc.admit_sandbox(f"app-{i}") is True
    # One more over the cap must wait, not be silently admitted.
    assert svc.admit_sandbox("waiter") is False

    r = client.get("/api/admin/capacity")
    assert r.status_code == 200
    body = r.json()
    assert body["supported"] is True
    assert body["active_count"] == concurrency
    assert body["waiting_count"] == 1
    assert "waiter" in body["waiting"]


def test_embedding_backend_discloses_the_real_hashing_trick_backend(client):
    r = client.get("/api/admin/embedding-backend")
    assert r.status_code == 200
    body = r.json()
    assert body["backend"] == "hashing-trick"
    assert body["quality_tier"] == "basic"
    assert body["model_backed"] is False
    assert body["detail"]
    assert body["status"] == "live"
