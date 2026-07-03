"""Hermetic tests for the emergency copy/paste handoff proxy
(``applicant_remote_routes.py`` -- ``GET /api/applicant/remote/applications/
{id}/emergency-handoff``, dark-engine audit item 35, FR-PREFILL-7).

Mirrors ``test_applicant_remote_routes.py``'s fake-engine style, extended with
``list_campaigns`` / ``list_pending_actions`` so the owner-scoping fan-out
(``_owner_application_ids``, mirrors ``applicant_tracker_routes.py``) can be
exercised without a real engine. Zero network.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

import routes.applicant_remote_routes as remote_routes
from routes.applicant_remote_routes import setup_applicant_remote_routes
from src.applicant_engine import EngineError


class _FakeEngine:
    """Stands in for ApplicantEngineClient as an async context manager."""

    calls: list = []
    campaigns: list = []
    pending_by_campaign: dict = {}   # campaign_id -> {"items": [...]}
    handoff_by_app: dict = {}        # application_id -> engine response dict
    raises: dict = {}                # call-name (or (name, arg)) -> EngineError

    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def list_campaigns(self):
        _FakeEngine.calls.append("list_campaigns")
        if "list_campaigns" in _FakeEngine.raises:
            raise _FakeEngine.raises["list_campaigns"]
        return _FakeEngine.campaigns

    async def list_pending_actions(self, campaign_id):
        _FakeEngine.calls.append(("list_pending_actions", campaign_id))
        key = ("list_pending_actions", campaign_id)
        if key in _FakeEngine.raises:
            raise _FakeEngine.raises[key]
        return _FakeEngine.pending_by_campaign.get(campaign_id, {"items": []})

    async def emergency_handoff(self, application_id):
        _FakeEngine.calls.append(("emergency_handoff", application_id))
        key = ("emergency_handoff", application_id)
        if key in _FakeEngine.raises:
            raise _FakeEngine.raises[key]
        return _FakeEngine.handoff_by_app.get(
            application_id,
            {
                "application_id": application_id,
                "available": True,
                "kind": "emergency_handoff",
                "title": "Emergency handoff + mark submitted",
                "handoff_values": {"First Name": "Kevin"},
                "state": "EMERGENCY_DATA_HANDOFF",
            },
        )


@pytest.fixture(autouse=True)
def _reset_fake():
    _FakeEngine.calls = []
    _FakeEngine.campaigns = []
    _FakeEngine.pending_by_campaign = {}
    _FakeEngine.handoff_by_app = {}
    _FakeEngine.raises = {}
    yield


def _pending_item(application_id, kind="emergency_handoff"):
    return {
        "id": f"pa-{application_id}",
        "kind": kind,
        "title": "Emergency handoff + mark submitted",
        "application_id": application_id,
        "campaign_id": "c-1",
        "payload": {"handoff_values": {"First Name": "Kevin"}},
    }


def _make_client(monkeypatch, *, authed: bool = True):
    monkeypatch.setattr(remote_routes, "ApplicantEngineClient", _FakeEngine)
    app = FastAPI()
    if authed:
        @app.middleware("http")
        async def _set_user(request: Request, call_next):
            request.state.current_user = "tester"
            return await call_next(request)
    app.include_router(setup_applicant_remote_routes())
    return TestClient(app, raise_server_exceptions=True)


# ── happy path ────────────────────────────────────────────────────────────


def test_returns_handoff_for_an_owned_application(monkeypatch):
    _FakeEngine.campaigns = [{"id": "c-1", "name": "My Search"}]
    _FakeEngine.pending_by_campaign = {"c-1": {"items": [_pending_item("app-1")]}}
    client = _make_client(monkeypatch)

    resp = client.get("/api/applicant/remote/applications/app-1/emergency-handoff")

    assert resp.status_code == 200
    body = resp.json()
    assert body["available"] is True
    assert body["handoff_values"] == {"First Name": "Kevin"}
    assert ("emergency_handoff", "app-1") in _FakeEngine.calls


def test_wrong_ats_kind_also_counts_as_owned(monkeypatch):
    """The owner-scoping fan-out must recognise BOTH handoff kinds
    (``emergency_handoff`` and ``wrong_ats``) as belonging to the owner — the
    fan-out lists every open pending action, not just one kind."""
    _FakeEngine.campaigns = [{"id": "c-1", "name": "My Search"}]
    _FakeEngine.pending_by_campaign = {
        "c-1": {"items": [_pending_item("app-2", kind="wrong_ats")]}
    }
    client = _make_client(monkeypatch)

    resp = client.get("/api/applicant/remote/applications/app-2/emergency-handoff")

    assert resp.status_code == 200
    assert ("emergency_handoff", "app-2") in _FakeEngine.calls


# ── auth ──────────────────────────────────────────────────────────────────


def test_requires_authentication(monkeypatch):
    def _boom(*a, **k):  # pragma: no cover - must not run
        raise AssertionError("engine must not be called when unauthenticated")

    monkeypatch.setattr(remote_routes, "ApplicantEngineClient", _boom)
    app = FastAPI()

    class _Configured:
        is_configured = True

    app.state.auth_manager = _Configured()
    app.include_router(setup_applicant_remote_routes())
    client = TestClient(app)
    resp = client.get("/api/applicant/remote/applications/app-1/emergency-handoff")
    assert resp.status_code == 401


# ── owner isolation (mandatory) ──────────────────────────────────────────
#
# The engine has no owner concept of its own (single-tenant per deployment) --
# THIS request's own list_campaigns() -> list_pending_actions() fan-out is the
# ONLY scoping boundary (mirrors applicant_tracker_routes.py). These prove a
# caller cannot read another owner's handoff values by guessing/knowing an
# application id that never appeared in their own campaigns.


def test_owner_isolation_unowned_application_id_is_404(monkeypatch):
    # "owner A" only has campaign c-1 with a pending action for app-owned-by-a.
    _FakeEngine.campaigns = [{"id": "c-1", "name": "Owner A's Search"}]
    _FakeEngine.pending_by_campaign = {
        "c-1": {"items": [_pending_item("app-owned-by-a")]}
    }
    client = _make_client(monkeypatch)

    # A caller guesses/knows another owner's application id.
    resp = client.get(
        "/api/applicant/remote/applications/app-owned-by-b/emergency-handoff"
    )

    assert resp.status_code == 404
    assert resp.json()["detail"] == "No such application."
    # The ownership fan-out must actually have run (proves the 404 came from the
    # owner-scoping check, not merely "no such route" — a missing route also 404s
    # with FastAPI's own generic body, which would let this test pass vacuously).
    assert "list_campaigns" in _FakeEngine.calls
    # The engine's actual handoff data must NEVER be fetched for an unowned id.
    assert ("emergency_handoff", "app-owned-by-b") not in _FakeEngine.calls


def test_owner_isolation_two_owners_never_cross_contaminate(monkeypatch):
    # -- "owner A" ------------------------------------------------------
    _FakeEngine.campaigns = [{"id": "owner-a-campaign", "name": "Alice's Search"}]
    _FakeEngine.pending_by_campaign = {
        "owner-a-campaign": {"items": [_pending_item("owner-a-app")]}
    }
    _FakeEngine.handoff_by_app = {
        "owner-a-app": {
            "application_id": "owner-a-app",
            "available": True,
            "handoff_values": {"Secret": "alice-only"},
        }
    }
    client = _make_client(monkeypatch)
    resp_a = client.get(
        "/api/applicant/remote/applications/owner-a-app/emergency-handoff"
    )
    assert resp_a.status_code == 200
    assert resp_a.json()["handoff_values"] == {"Secret": "alice-only"}

    # Owner A's own request can never see owner B's (disjoint) application --
    # simulated by a second application id that never appeared in Alice's own
    # campaign fan-out.
    resp_cross = client.get(
        "/api/applicant/remote/applications/owner-b-app/emergency-handoff"
    )
    assert resp_cross.status_code == 404
    assert ("emergency_handoff", "owner-b-app") not in _FakeEngine.calls


# ── engine degradation ───────────────────────────────────────────────────


def test_engine_unreachable_during_ownership_check_degrades_soft(monkeypatch):
    _FakeEngine.raises = {"list_campaigns": EngineError("down", is_timeout=True)}
    client = _make_client(monkeypatch)

    resp = client.get("/api/applicant/remote/applications/app-1/emergency-handoff")

    # A transport failure while resolving ownership must not leak a 500/502 --
    # the panel simply reports itself unavailable.
    assert resp.status_code == 200
    body = resp.json()
    assert body["available"] is False
    assert body["engine_available"] is False


def test_engine_error_fetching_handoff_data_passes_through(monkeypatch):
    _FakeEngine.campaigns = [{"id": "c-1", "name": "My Search"}]
    _FakeEngine.pending_by_campaign = {"c-1": {"items": [_pending_item("app-1")]}}
    _FakeEngine.raises = {
        ("emergency_handoff", "app-1"): EngineError("boom", status=502, detail="down")
    }
    client = _make_client(monkeypatch)

    resp = client.get("/api/applicant/remote/applications/app-1/emergency-handoff")

    assert resp.status_code == 502
