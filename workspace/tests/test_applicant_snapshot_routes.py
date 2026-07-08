"""Hermetic tests for the pre-submit submission-snapshot proxy (surfacing-only).

Mounts only ``routes/applicant_snapshot_routes.py`` on a bare FastAPI app with a
tiny middleware that authenticates the request (the real global auth gate lives in
``app.py`` and is out of scope here). The engine is faked two ways:

* a scripted ``FakeEngine`` patched in for ``ApplicantEngineClient`` (covers the
  proxied shape, the pre-submit 404 empty state, and the soft-degrade paths), and
* a real :class:`ApplicantEngineClient` over an ``httpx.MockTransport`` proving the
  exact engine path is hit.

Zero network either way.
"""

from __future__ import annotations

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import routes.applicant_snapshot_routes as mod
from routes.applicant_snapshot_routes import setup_applicant_snapshot_routes
from src.applicant_engine import ApplicantEngineClient, EngineError


# --- test app with a stand-in auth middleware -------------------------------


def _make_app(authed: bool = True) -> FastAPI:
    app = FastAPI()

    @app.middleware("http")
    async def _auth(request, call_next):
        request.state.current_user = "tester" if authed else None
        return await call_next(request)

    app.include_router(setup_applicant_snapshot_routes())
    return app


# --- a scripted fake engine -------------------------------------------------


class FakeEngine:
    """Stands in for ApplicantEngineClient as an async context manager."""

    calls: list = []
    snapshots: dict = {}        # application_id -> engine snapshot payload
    raises: dict = {}           # application_id -> EngineError

    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return None

    async def submission_snapshot(self, application_id):
        FakeEngine.calls.append(("submission_snapshot", application_id))
        if application_id in FakeEngine.raises:
            raise FakeEngine.raises[application_id]
        return FakeEngine.snapshots.get(application_id, {})


@pytest.fixture(autouse=True)
def _reset_fake():
    FakeEngine.calls = []
    FakeEngine.snapshots = {}
    FakeEngine.raises = {}
    yield


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(mod, "ApplicantEngineClient", FakeEngine)
    return TestClient(_make_app())


# --- auth -------------------------------------------------------------------


def test_unauthenticated_is_rejected(monkeypatch):
    monkeypatch.setattr(mod, "ApplicantEngineClient", FakeEngine)
    c = TestClient(_make_app(authed=False))
    r = c.get("/api/applicant/snapshot/app-1")
    assert r.status_code == 401


# --- happy path -------------------------------------------------------------


def test_snapshot_proxies_recorded_shape(client):
    FakeEngine.snapshots = {
        "app-1": {
            "application_id": "app-1",
            "answers": {"Why do you want this role?": "Because it fits."},
            "material_versions": {"resume": "variant-9"},
            "materials": [{"kind": "resume", "name": "resume.pdf"}],
            "posting_url": "https://jobs.example.com/postings/42",
            "timestamp": "2026-07-02T12:00:00+00:00",
        }
    }
    r = client.get("/api/applicant/snapshot/app-1")
    assert r.status_code == 200
    body = r.json()
    assert body["engine_available"] is True
    assert body["has_snapshot"] is True
    assert body["application_id"] == "app-1"
    # The engine's exact fields pass straight through — this is "what will be sent".
    assert body["answers"]["Why do you want this role?"] == "Because it fits."
    assert body["material_versions"]["resume"] == "variant-9"
    assert body["materials"][0]["name"] == "resume.pdf"
    assert body["posting_url"] == "https://jobs.example.com/postings/42"
    assert body["timestamp"] == "2026-07-02T12:00:00+00:00"
    assert ("submission_snapshot", "app-1") in FakeEngine.calls


# --- pre-submit gap: a 404 is "nothing recorded yet", NOT offline -----------


def test_snapshot_404_is_empty_not_offline(client):
    # Before the terminal submit the engine has no snapshot -> 404. That must read
    # as an honest empty preview (engine reachable), never as engine-offline and
    # never as a fabricated snapshot.
    FakeEngine.raises["app-1"] = EngineError("not found", status=404)
    r = client.get("/api/applicant/snapshot/app-1")
    assert r.status_code == 200
    body = r.json()
    assert body["engine_available"] is True
    assert body["has_snapshot"] is False
    assert body["answers"] == {}
    assert body["materials"] == []
    assert body["posting_url"] == ""
    assert body["timestamp"] is None
    assert body.get("gated") is not True


def test_snapshot_empty_payload_has_no_snapshot(client):
    # Engine returns 200 with an empty body — still "nothing to show".
    FakeEngine.snapshots = {"app-1": {"application_id": "app-1"}}
    r = client.get("/api/applicant/snapshot/app-1")
    assert r.status_code == 200
    body = r.json()
    assert body["engine_available"] is True
    assert body["has_snapshot"] is False


# --- soft-degrade -----------------------------------------------------------


def test_snapshot_soft_degrades_when_engine_down(client):
    FakeEngine.raises["app-1"] = EngineError("down", status=None, is_timeout=True)
    r = client.get("/api/applicant/snapshot/app-1")
    assert r.status_code == 200
    body = r.json()
    assert body["engine_available"] is False
    assert body["has_snapshot"] is False
    assert body.get("gated") is not True


_GATE_MSG = "This view is available once setup is complete."


def test_snapshot_409_gate_is_not_offline(client):
    FakeEngine.raises["app-1"] = EngineError("gated", status=409, detail=_GATE_MSG)
    r = client.get("/api/applicant/snapshot/app-1")
    assert r.status_code == 200
    body = r.json()
    assert body["gated"] is True
    assert body["engine_available"] is True
    assert body["message"] == _GATE_MSG
    assert body["has_snapshot"] is False


def test_snapshot_5xx_is_offline(client):
    FakeEngine.raises["app-1"] = EngineError("boom", status=500)
    r = client.get("/api/applicant/snapshot/app-1")
    assert r.status_code == 200
    body = r.json()
    assert body["engine_available"] is False
    assert body.get("gated") is not True


# --- exact engine path via a real client over MockTransport -----------------


def _mock_transport_app(handler):
    class TransportEngine(ApplicantEngineClient):
        def __init__(self, *a, **k):
            super().__init__(base_url="http://api:8000", transport=httpx.MockTransport(handler))

    app = FastAPI()

    @app.middleware("http")
    async def _auth(request, call_next):
        request.state.current_user = "tester"
        return await call_next(request)

    app.include_router(setup_applicant_snapshot_routes())
    return app, TransportEngine


def test_snapshot_hits_exact_engine_path(monkeypatch):
    paths = []

    def handler(request: httpx.Request) -> httpx.Response:
        paths.append((request.method, request.url.path))
        if request.url.path == "/api/outcomes/applications/app-9/snapshot":
            return httpx.Response(200, json={"application_id": "app-9", "answers": {"q": "a"}})
        return httpx.Response(404, json={"detail": "unexpected"})

    app, engine_cls = _mock_transport_app(handler)
    monkeypatch.setattr(mod, "ApplicantEngineClient", engine_cls)
    c = TestClient(app)

    r = c.get("/api/applicant/snapshot/app-9")
    assert r.status_code == 200
    assert ("GET", "/api/outcomes/applications/app-9/snapshot") in paths
    assert r.json()["has_snapshot"] is True


def test_snapshot_pre_submit_404_from_engine_is_empty(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"detail": "No submission snapshot recorded for this application."})

    app, engine_cls = _mock_transport_app(handler)
    monkeypatch.setattr(mod, "ApplicantEngineClient", engine_cls)
    c = TestClient(app)

    r = c.get("/api/applicant/snapshot/app-9")
    assert r.status_code == 200
    body = r.json()
    assert body["engine_available"] is True
    assert body["has_snapshot"] is False


# --- H3 (full-fidelity review): the capture stage passes through -------------


def test_snapshot_stage_reviewed_passes_through(client):
    """The engine now records a provisional ``stage: "reviewed"`` snapshot AT the
    review stop-boundary (H3) — the preview needs the stage to say honestly
    whether it is showing what WILL be sent or what WAS sent."""
    FakeEngine.snapshots = {
        "app-1": {
            "application_id": "app-1",
            "answers": {"Why this role?": "Because it fits."},
            "stage": "reviewed",
        }
    }
    r = client.get("/api/applicant/snapshot/app-1")
    assert r.status_code == 200
    body = r.json()
    assert body["has_snapshot"] is True
    assert body["stage"] == "reviewed"


def test_snapshot_stage_defaults_empty_when_engine_omits_it(client):
    FakeEngine.snapshots = {"app-1": {"application_id": "app-1", "answers": {"q": "a"}}}
    body = client.get("/api/applicant/snapshot/app-1").json()
    assert body["stage"] == ""
    # The soft-degrade empty body carries the field too (stable shape).
    FakeEngine.raises["app-2"] = EngineError("not found", status=404)
    body = client.get("/api/applicant/snapshot/app-2").json()
    assert body["stage"] == ""


# --- H3 hardening: the snapshot is the OWNER's literal application -----------
#
# Mirrors test_applicant_crossuser_isolation_disc15.py's two-account convention:
# the engine is single-tenant, so once the workspace is configured for multiple
# accounts only the owner/admin may read the snapshot (require_engine_owner).


class _AuthMgr:
    def __init__(self, *, configured: bool, admins: set | None = None):
        self.is_configured = configured
        self._admins = set(admins or ())

    def is_admin(self, user: str) -> bool:
        return user in self._admins


def _make_configured_app(user: str, admins=("owner",)) -> FastAPI:
    app = FastAPI()
    app.state.auth_manager = _AuthMgr(configured=True, admins=admins)

    @app.middleware("http")
    async def _auth(request, call_next):
        request.state.current_user = user
        return await call_next(request)

    app.include_router(setup_applicant_snapshot_routes())
    return app


def test_snapshot_non_owner_second_account_is_denied(monkeypatch):
    monkeypatch.setattr(mod, "ApplicantEngineClient", FakeEngine)
    FakeEngine.snapshots = {"app-1": {"application_id": "app-1", "answers": {"q": "a"}}}
    c = TestClient(_make_configured_app("intruder"))
    r = c.get("/api/applicant/snapshot/app-1")
    assert r.status_code in (401, 403)
    # The engine was never consulted for the denied account.
    assert ("submission_snapshot", "app-1") not in FakeEngine.calls


def test_snapshot_owner_account_still_passes(monkeypatch):
    monkeypatch.setattr(mod, "ApplicantEngineClient", FakeEngine)
    FakeEngine.snapshots = {"app-1": {"application_id": "app-1", "answers": {"q": "a"}}}
    c = TestClient(_make_configured_app("owner"))
    r = c.get("/api/applicant/snapshot/app-1")
    assert r.status_code == 200
    assert r.json()["has_snapshot"] is True
