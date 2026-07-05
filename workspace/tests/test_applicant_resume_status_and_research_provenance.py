"""Front-door proxy coverage for dark-engine audit items #76 and #78 (B7).

* #76 -- ``routes/applicant_documents_routes.py``'s new ``GET
  /api/applicant/documents/research-provenance/{application_id}`` proxy over
  the engine's ``GET /api/admin/research-provenance/{id}`` (which company
  research, if any, informed an application's materials).
* #78 -- ``routes/applicant_tracker_routes.py``'s new ``GET
  /api/applicant/tracker/applications/{application_id}/resume-status`` proxy
  over the engine's ``GET /api/admin/resume-status/{id}`` (countdown to the
  next resume attempt for a blocked application).

Both are plain, side-effect-free reads (mirrors ``jd_match``/``application_documents``
in ``applicant_documents_routes.py`` -- the engine has no owner concept of its
own, single-tenant per deployment), so these tests just prove the route exists,
forwards the engine's real payload unchanged, and degrades soft on an engine
error -- following the exact ``_FakeStuckEngine``-monkeypatch pattern
``test_applicant_tracker_stuck.py`` established.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import routes.applicant_documents_routes as docs_routes
import routes.applicant_tracker_routes as tracker_routes
from routes.applicant_documents_routes import setup_applicant_documents_routes
from routes.applicant_tracker_routes import setup_applicant_tracker_routes
from src.applicant_engine import EngineError


class _FakeEngine:
    calls: list = []
    research_provenance: dict = {}
    resume_status: dict = {}
    raises: dict = {}

    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return None

    async def admin_research_provenance(self, application_id):
        type(self).calls.append(("admin_research_provenance", application_id))
        key = ("admin_research_provenance", application_id)
        if key in type(self).raises:
            raise type(self).raises[key]
        return type(self).research_provenance.get(
            application_id, {"application_id": application_id, "used": False}
        )

    async def admin_resume_status(self, application_id):
        type(self).calls.append(("admin_resume_status", application_id))
        key = ("admin_resume_status", application_id)
        if key in type(self).raises:
            raise type(self).raises[key]
        return type(self).resume_status.get(
            application_id, {"application_id": application_id, "status": "not_blocked"}
        )


@pytest.fixture(autouse=True)
def _reset_fake_engine():
    _FakeEngine.calls = []
    _FakeEngine.research_provenance = {}
    _FakeEngine.resume_status = {}
    _FakeEngine.raises = {}
    yield


def _make_documents_app(authed: bool = True) -> FastAPI:
    app = FastAPI()
    if authed:
        @app.middleware("http")
        async def _auth(request, call_next):
            request.state.current_user = "tester"
            return await call_next(request)
    app.include_router(setup_applicant_documents_routes())
    return app


def _make_tracker_app(authed: bool = True) -> FastAPI:
    app = FastAPI()
    if authed:
        @app.middleware("http")
        async def _auth(request, call_next):
            request.state.current_user = "tester"
            return await call_next(request)
    app.include_router(setup_applicant_tracker_routes())
    return app


@pytest.fixture
def documents_client(monkeypatch):
    monkeypatch.setattr(docs_routes, "ApplicantEngineClient", _FakeEngine)
    return TestClient(_make_documents_app())


@pytest.fixture
def tracker_client(monkeypatch):
    monkeypatch.setattr(tracker_routes, "ApplicantEngineClient", _FakeEngine)
    return TestClient(_make_tracker_app())


# --- #76: research-provenance -------------------------------------------------


def test_research_provenance_forwards_the_engines_real_payload(documents_client):
    _FakeEngine.research_provenance = {
        "app-1": {
            "application_id": "app-1",
            "used": True,
            "company": "Acme Corp",
            "summary_excerpt": "Acme Corp is a logistics company...",
            "sources": [{"title": "Acme — About", "url": "https://acme.example/about"}],
        }
    }

    r = documents_client.get("/api/applicant/documents/research-provenance/app-1")

    assert r.status_code == 200
    body = r.json()
    assert body["used"] is True
    assert body["company"] == "Acme Corp"
    assert ("admin_research_provenance", "app-1") in _FakeEngine.calls


def test_research_provenance_used_false_when_never_researched(documents_client):
    r = documents_client.get("/api/applicant/documents/research-provenance/app-2")
    assert r.status_code == 200
    assert r.json() == {"application_id": "app-2", "used": False}


def test_research_provenance_degrades_soft_on_engine_error(documents_client):
    _FakeEngine.raises = {
        ("admin_research_provenance", "app-3"): EngineError("down", status=None)
    }
    r = documents_client.get("/api/applicant/documents/research-provenance/app-3")
    assert r.status_code == 200
    assert r.json() == {"application_id": "app-3", "used": False}


# --- #78: resume-status -------------------------------------------------------


def test_resume_status_forwards_the_engines_real_payload(tracker_client):
    _FakeEngine.resume_status = {
        "app-9": {
            "application_id": "app-9",
            "status": "blocked",
            "last_resume_at": "2026-06-16T12:00:00+00:00",
            "next_retry_at": "2026-06-16T12:05:00+00:00",
            "seconds_remaining": 120,
        }
    }

    r = tracker_client.get("/api/applicant/tracker/applications/app-9/resume-status")

    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "blocked"
    assert body["next_retry_at"] == "2026-06-16T12:05:00+00:00"
    assert ("admin_resume_status", "app-9") in _FakeEngine.calls


def test_resume_status_not_blocked_by_default(tracker_client):
    r = tracker_client.get("/api/applicant/tracker/applications/app-10/resume-status")
    assert r.status_code == 200
    assert r.json() == {"application_id": "app-10", "status": "not_blocked"}


def test_resume_status_degrades_soft_on_engine_error(tracker_client):
    _FakeEngine.raises = {
        ("admin_resume_status", "app-11"): EngineError("down", status=None)
    }
    r = tracker_client.get("/api/applicant/tracker/applications/app-11/resume-status")
    assert r.status_code == 200
    assert r.json() == {"application_id": "app-11", "status": "not_blocked"}
