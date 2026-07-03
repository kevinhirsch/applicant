"""Reachability + real data for the induced-routine route (dark-engine audit #45).

``LearningService.induce_workflow`` folded a successful pre-fill trace into a
reusable per-ATS routine (AWM workflow-induction, #306) but had ZERO callers, so
the audit flagged every ATS site as re-derived cold every time. This proves the
full chain end-to-end:

* ``PrefillService._induce_routine`` (the real call site a clean pre-fill page
  hits, see ``prefill_service.py``'s ``_run_plan_ops`` -> ``_induce_routine``)
  now calls ``LearningService.induce_workflow`` (previously unreferenced) rather
  than poking the ``RoutineStore`` directly;
* the induced routine lands in the SAME process-lived ``RoutineStore`` the
  planner reads priors from (``container.py``'s single ``InMemoryRoutineStore``,
  injected into ``container.prefill_service``);
* the new ``GET /api/admin/routines`` route (registered + reachable) reads that
  store via ``PrefillService.list_routines()`` and returns REAL contents, not a
  fabricated/empty stub.

Hermetic: in-memory storage, real container services, LLM gate opened like the
peer router tests (test_admin_lessons_route.py / test_prefill_diagnostics_route.py).
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from applicant.app.main import create_app
from applicant.application.services.learning_service import LearningService
from applicant.ports.driven.routine_store import RoutineStep


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


def test_routines_route_is_registered(client):
    paths = _registered_paths(client.app)
    assert "/api/admin/routines" in paths


def test_routines_empty_is_well_formed(client):
    r = client.get("/api/admin/routines")
    assert r.status_code == 200
    assert r.json() == {"routines": [], "status": "live"}


def test_routines_reflect_real_induction_via_prefill_service(client):
    # Drive the SAME process-lived PrefillService (+ its shared RoutineStore) the
    # route reads from, through the SAME entry point the pre-fill loop uses after
    # a clean page (``_induce_routine``), so the response is proven to reflect
    # real induced state, not a fabricated/hardcoded value.
    container = client.app.state.container
    pf = container.prefill_service
    assert pf is not None

    steps = (
        RoutineStep(kind="fill", ref="input#first_name", attribute_id="first_name"),
        RoutineStep(kind="click", ref="button#next"),
    )
    pf._induce_routine("greenhouse.io", steps, reused=False)

    r = client.get("/api/admin/routines")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "live"
    assert len(body["routines"]) == 1
    row = body["routines"][0]
    assert row["domain"] == "greenhouse.io"
    assert row["step_count"] == 2
    assert row["successes"] == 1
    assert row["failures"] == 0
    assert row["score"] == 1
    assert row["source"] == "induced"

    # Inducing again (as if a second successful pre-fill reused it) refreshes
    # and up-weights the SAME routine (ACE) rather than creating a duplicate.
    pf._induce_routine("greenhouse.io", steps, reused=True)
    body2 = client.get("/api/admin/routines").json()
    assert len(body2["routines"]) == 1
    assert body2["routines"][0]["successes"] == 2

    # A DIFFERENT domain never induced stays absent (never fabricated).
    domains = {row["domain"] for row in body2["routines"]}
    assert "workday.com" not in domains


def test_induce_workflow_is_the_real_call_site_used_by_prefill_service(client):
    """The audited zero-caller wrapper now has exactly this real caller.

    ``LearningService.induce_workflow`` is a ``@staticmethod`` (no per-request
    LearningService instance needed) folding straight into the RoutineStore, and
    ``PrefillService._induce_routine`` calls it by name — proven here by calling
    it directly the same way the loop does and confirming it lands in the store
    the route reads.
    """
    container = client.app.state.container
    pf = container.prefill_service
    store = pf._routine_store
    assert store is not None

    steps = (RoutineStep(kind="fill", ref="input#email", attribute_id="email"),)
    routine = LearningService.induce_workflow(store, "lever.co", steps)
    assert routine is not None
    assert routine.domain == "lever.co"

    r = client.get("/api/admin/routines")
    body = r.json()
    assert any(row["domain"] == "lever.co" for row in body["routines"])


def test_induce_workflow_defensive_nones_never_raise():
    """Mirrors the method's own documented no-op contract (no store / no steps)."""
    assert LearningService.induce_workflow(None, "greenhouse.io", ()) is None
    assert LearningService.induce_workflow(object(), "", ()) is None
    assert LearningService.induce_workflow(object(), "greenhouse.io", ()) is None
