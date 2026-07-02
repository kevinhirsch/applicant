"""Hermetic tests for the front-door proxy half of product-gaps backlog #20
(screening-answer library, ``routes/applicant_documents_routes.py``) and #30
(interview-prep generation, ``routes/applicant_tracker_routes.py``).

Zero network: the engine client is replaced with a fake async-context-manager,
exactly like ``test_applicant_documents_routes.py`` / ``test_applicant_tracker_
routes.py`` (whose fakes this mirrors but extends with the new engine calls:
``screening_answer_library``, ``reuse_screening_answer``, ``interview_prep``).

Both new documents-proxy endpoints (library read, reuse write) are CAMPAIGN-
scoped and validated against this request's own ``list_campaigns()`` fan-out
before being forwarded -- mirrors ``applicant_campaigns_routes``'s owner-scoping
-- because the engine itself has no owner concept (CLAUDE.md: single-tenant per
deployment). The interview-prep endpoint is APPLICATION-scoped and reuses the
tracker's existing ``_owner_tracker_rows``/``_owner_application_ids`` fan-out
unchanged. Per this series' standing DoD, each assertion below was verified, by
hand, to actually go red when the corresponding piece of the chain is reverted,
then confirmed green again after restoring.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

import routes.applicant_documents_routes as docs_routes
import routes.applicant_tracker_routes as tracker_routes
from routes.applicant_documents_routes import setup_applicant_documents_routes
from routes.applicant_tracker_routes import setup_applicant_tracker_routes
from src.applicant_engine import EngineError

# === screening-answer library (routes/applicant_documents_routes.py, #20) ===


class _FakeDocsEngine:
    """Stand-in for ApplicantEngineClient over the documents proxy.

    Extends the ``test_applicant_documents_routes.py`` fake with the calls the
    owner-scoping check needs (``list_campaigns``) plus the two new library
    calls, scripted independently so a campaigns-read failure and a
    library-call failure can be tested separately.
    """

    campaigns: list = []
    library_results: dict = {}   # campaign_id -> engine payload
    reuse_result: dict | None = None
    raises: dict = {}            # key -> EngineError
    calls: list = []

    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def list_campaigns(self):
        type(self).calls.append("list_campaigns")
        if "list_campaigns" in type(self).raises:
            raise type(self).raises["list_campaigns"]
        return type(self).campaigns

    async def screening_answer_library(self, campaign_id):
        type(self).calls.append(("screening_answer_library", campaign_id))
        key = ("screening_answer_library", campaign_id)
        if key in type(self).raises:
            raise type(self).raises[key]
        return type(self).library_results.get(campaign_id, {"campaign_id": campaign_id, "items": []})

    async def reuse_screening_answer(self, body):
        type(self).calls.append(("reuse_screening_answer", body))
        if "reuse_screening_answer" in type(self).raises:
            raise type(self).raises["reuse_screening_answer"]
        return type(self).reuse_result or {"found": False}


@pytest.fixture(autouse=True)
def _reset_fake_docs_engine():
    _FakeDocsEngine.campaigns = []
    _FakeDocsEngine.library_results = {}
    _FakeDocsEngine.reuse_result = None
    _FakeDocsEngine.raises = {}
    _FakeDocsEngine.calls = []
    yield


def _make_docs_client(*, authed: bool = True):
    app = FastAPI()
    if authed:
        @app.middleware("http")
        async def _set_user(request: Request, call_next):
            request.state.current_user = "tester"
            return await call_next(request)
    app.include_router(setup_applicant_documents_routes())
    return TestClient(app, raise_server_exceptions=True)


@pytest.fixture
def docs_client(monkeypatch):
    monkeypatch.setattr(docs_routes, "ApplicantEngineClient", _FakeDocsEngine)
    return _make_docs_client()


# ── GET screening-answer-library/{campaign_id} ──────────────────────────────


def test_library_forwards_for_an_owned_campaign(docs_client):
    _FakeDocsEngine.campaigns = [{"id": "c1", "name": "Backend"}]
    _FakeDocsEngine.library_results = {
        "c1": {"campaign_id": "c1", "items": [{"question": "Why us?", "answer": "...", "essay": True}]}
    }

    r = docs_client.get("/api/applicant/documents/screening-answer-library/c1")

    assert r.status_code == 200
    body = r.json()
    assert body["engine_available"] is True
    assert body["items"] == [{"question": "Why us?", "answer": "...", "essay": True}]
    assert ("screening_answer_library", "c1") in _FakeDocsEngine.calls


def test_library_never_reads_a_campaign_the_owner_does_not_have(docs_client):
    # "c1" belongs to THIS request's own list_campaigns() fan-out; "not-mine"
    # never appears in it -- the library read must never even be attempted.
    _FakeDocsEngine.campaigns = [{"id": "c1", "name": "Backend"}]

    r = docs_client.get("/api/applicant/documents/screening-answer-library/not-mine")

    assert r.status_code == 200
    body = r.json()
    assert body["engine_available"] is True
    assert body["items"] == []
    assert not any(
        isinstance(c, tuple) and c[0] == "screening_answer_library" for c in _FakeDocsEngine.calls
    )


def test_library_engine_unavailable_degrades_soft(docs_client):
    _FakeDocsEngine.raises = {"list_campaigns": EngineError("down", status=None)}

    r = docs_client.get("/api/applicant/documents/screening-answer-library/c1")

    assert r.status_code == 200
    body = r.json()
    assert body["engine_available"] is False
    assert body["items"] == []


def test_library_requires_auth():
    client = _make_docs_client(authed=False)
    r = client.get("/api/applicant/documents/screening-answer-library/c1")
    assert r.status_code in (401, 403)


# ── POST screening-answer-library/reuse ─────────────────────────────────────


def test_reuse_forwards_for_an_owned_campaign(docs_client):
    _FakeDocsEngine.campaigns = [{"id": "c1", "name": "Backend"}]
    _FakeDocsEngine.reuse_result = {
        "found": True, "id": "doc-9", "type": "screening_answer", "approved": False, "content": "Two weeks."
    }

    r = docs_client.post(
        "/api/applicant/documents/screening-answer-library/reuse",
        json={"campaign_id": "c1", "application_id": "a1", "question": "Notice period?"},
    )

    assert r.status_code == 201
    assert r.json()["found"] is True
    assert r.json()["id"] == "doc-9"
    name, body = next(c for c in _FakeDocsEngine.calls if isinstance(c, tuple))
    assert name == "reuse_screening_answer"
    assert body == {"campaign_id": "c1", "application_id": "a1", "question": "Notice period?"}


def test_reuse_not_found_still_passes_through(docs_client):
    _FakeDocsEngine.campaigns = [{"id": "c1", "name": "Backend"}]
    _FakeDocsEngine.reuse_result = {"found": False}

    r = docs_client.post(
        "/api/applicant/documents/screening-answer-library/reuse",
        json={"campaign_id": "c1", "application_id": "a1", "question": "Never asked?"},
    )

    assert r.status_code == 201
    assert r.json() == {"found": False}


def test_reuse_rejects_a_campaign_the_owner_does_not_have(docs_client):
    _FakeDocsEngine.campaigns = [{"id": "c1", "name": "Backend"}]

    r = docs_client.post(
        "/api/applicant/documents/screening-answer-library/reuse",
        json={"campaign_id": "not-mine", "application_id": "a1", "question": "Notice period?"},
    )

    assert r.status_code == 404
    assert not any(
        isinstance(c, tuple) and c[0] == "reuse_screening_answer" for c in _FakeDocsEngine.calls
    )


def test_reuse_engine_unavailable_is_503(docs_client):
    _FakeDocsEngine.raises = {"list_campaigns": EngineError("down", status=None)}

    r = docs_client.post(
        "/api/applicant/documents/screening-answer-library/reuse",
        json={"campaign_id": "c1", "application_id": "a1", "question": "Notice period?"},
    )

    assert r.status_code == 503


def test_reuse_requires_can_use_documents_privilege_path():
    # No auth at all -> the privilege gate's own auth check rejects first.
    client = _make_docs_client(authed=False)
    r = client.post(
        "/api/applicant/documents/screening-answer-library/reuse",
        json={"campaign_id": "c1", "application_id": "a1", "question": "Notice period?"},
    )
    assert r.status_code in (401, 403)


# ── owner isolation: one owner's request never leaks/writes into another's ──


def test_owner_isolation_two_owners_never_cross_contaminate(docs_client):
    # -- "owner A" ---------------------------------------------------------
    _FakeDocsEngine.campaigns = [{"id": "owner-a-campaign", "name": "Alice's Search"}]
    _FakeDocsEngine.library_results = {
        "owner-a-campaign": {
            "campaign_id": "owner-a-campaign",
            "items": [{"question": "Alice's secret question", "answer": "Alice's answer", "essay": False}],
        }
    }
    r_a = docs_client.get("/api/applicant/documents/screening-answer-library/owner-a-campaign")
    assert r_a.status_code == 200
    assert r_a.json()["items"][0]["question"] == "Alice's secret question"

    # -- "owner B" (a completely disjoint campaign universe) ---------------
    _FakeDocsEngine.campaigns = [{"id": "owner-b-campaign", "name": "Bob's Search"}]
    _FakeDocsEngine.library_results = {
        "owner-b-campaign": {
            "campaign_id": "owner-b-campaign",
            "items": [{"question": "Bob's question", "answer": "Bob's answer", "essay": False}],
        }
    }

    # Owner B can never read owner A's library, even by guessing the id --
    # "owner-a-campaign" never appears in B's own list_campaigns() fan-out.
    r_leak = docs_client.get("/api/applicant/documents/screening-answer-library/owner-a-campaign")
    assert r_leak.status_code == 200
    body_leak = r_leak.json()
    assert body_leak["items"] == []
    assert "Alice" not in str(body_leak)

    # Owner B can never reuse/write into owner A's campaign either.
    r_write_leak = docs_client.post(
        "/api/applicant/documents/screening-answer-library/reuse",
        json={
            "campaign_id": "owner-a-campaign",
            "application_id": "owner-a-app",
            "question": "Alice's secret question",
        },
    )
    assert r_write_leak.status_code == 404
    assert not any(
        isinstance(c, tuple) and c[0] == "reuse_screening_answer" for c in _FakeDocsEngine.calls
    )

    # Owner B's own board is untouched and correct.
    r_b = docs_client.get("/api/applicant/documents/screening-answer-library/owner-b-campaign")
    assert r_b.status_code == 200
    assert r_b.json()["items"][0]["question"] == "Bob's question"


# === interview prep (routes/applicant_tracker_routes.py, #30) ===============


class _FakeTrackerEngine:
    """Stand-in for ApplicantEngineClient over the tracker proxy.

    Mirrors ``test_applicant_tracker_routes.py``'s ``FakeEngine`` (campaigns +
    per-campaign boards) plus the new ``interview_prep`` call.
    """

    calls: list = []
    campaigns: list = []
    boards: dict = {}
    prep_results: dict = {}   # (campaign_id, application_id) -> engine payload
    raises: dict = {}

    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return None

    async def list_campaigns(self):
        type(self).calls.append("list_campaigns")
        if "list_campaigns" in type(self).raises:
            raise type(self).raises["list_campaigns"]
        return type(self).campaigns

    async def tracker_board(self, campaign_id):
        type(self).calls.append(("tracker_board", campaign_id))
        if ("tracker_board", campaign_id) in type(self).raises:
            raise type(self).raises[("tracker_board", campaign_id)]
        return type(self).boards.get(campaign_id, {"applications": []})

    async def interview_prep(self, campaign_id, application_id):
        type(self).calls.append(("interview_prep", campaign_id, application_id))
        key = ("interview_prep", campaign_id, application_id)
        if key in type(self).raises:
            raise type(self).raises[key]
        return type(self).prep_results.get(
            (campaign_id, application_id), {"generated": False}
        )


@pytest.fixture(autouse=True)
def _reset_fake_tracker_engine():
    _FakeTrackerEngine.calls = []
    _FakeTrackerEngine.campaigns = []
    _FakeTrackerEngine.boards = {}
    _FakeTrackerEngine.prep_results = {}
    _FakeTrackerEngine.raises = {}
    yield


def _tracker_row(app_id, *, status="AWAITING_RESPONSE", signals=None):
    return {
        "application_id": app_id,
        "status": status,
        "role_name": "Backend Engineer",
        "job_title": "Backend Engineer",
        "signals": signals or [],
        "submitted_at": "2026-06-01T00:00:00+00:00",
        "created_at": "2026-05-30T00:00:00+00:00",
    }


def _make_tracker_app(authed: bool = True):
    app = FastAPI()
    if authed:
        @app.middleware("http")
        async def _auth(request, call_next):
            request.state.current_user = "tester"
            return await call_next(request)
    app.include_router(setup_applicant_tracker_routes())
    return app


@pytest.fixture
def tracker_client(monkeypatch):
    monkeypatch.setattr(tracker_routes, "ApplicantEngineClient", _FakeTrackerEngine)
    return TestClient(_make_tracker_app())


def test_interview_prep_forwards_the_rows_own_campaign_id(tracker_client):
    _FakeTrackerEngine.campaigns = [{"id": "c1", "name": "Backend"}]
    _FakeTrackerEngine.boards = {
        "c1": {"applications": [_tracker_row("a-1", signals=["interview_invited"])]}
    }
    _FakeTrackerEngine.prep_results = {
        ("c1", "a-1"): {
            "generated": True,
            "company": "Acme",
            "role": "Backend Engineer",
            "notes": ["You're interviewing for Backend Engineer at Acme."],
            "key_requirements": ["Own the deployment pipeline."],
            "company_research": "Acme background brief.",
        }
    }

    r = tracker_client.get("/api/applicant/tracker/applications/a-1/interview-prep")

    assert r.status_code == 200
    body = r.json()
    assert body["generated"] is True
    assert body["company"] == "Acme"
    assert ("interview_prep", "c1", "a-1") in _FakeTrackerEngine.calls


def test_interview_prep_rejects_an_application_not_in_owners_own_board(tracker_client):
    # Mirrors record_outcome/scan_email's owner-isolation guard: "a-1" belongs to
    # c1, which this request's own fan-out returns; a caller-supplied id for an
    # application that never showed up there must 404, and the engine read must
    # never even be attempted.
    _FakeTrackerEngine.campaigns = [{"id": "c1", "name": "Backend"}]
    _FakeTrackerEngine.boards = {"c1": {"applications": [_tracker_row("a-1")]}}

    r = tracker_client.get("/api/applicant/tracker/applications/not-mine/interview-prep")

    assert r.status_code == 404
    assert not any(
        isinstance(c, tuple) and c[0] == "interview_prep" for c in _FakeTrackerEngine.calls
    )


def test_interview_prep_engine_unavailable_degrades_soft(tracker_client):
    _FakeTrackerEngine.raises = {"list_campaigns": EngineError("down", status=None)}

    r = tracker_client.get("/api/applicant/tracker/applications/a-1/interview-prep")

    assert r.status_code == 200
    assert r.json()["generated"] is False


def test_interview_prep_not_yet_generated_passes_through(tracker_client):
    # The application is the owner's own, but hasn't reached interview_invited
    # yet -- the ENGINE decides that (never a caller-supplied flag); the proxy
    # just forwards whatever the engine says.
    _FakeTrackerEngine.campaigns = [{"id": "c1", "name": "Backend"}]
    _FakeTrackerEngine.boards = {"c1": {"applications": [_tracker_row("a-1")]}}
    _FakeTrackerEngine.prep_results = {("c1", "a-1"): {"generated": False}}

    r = tracker_client.get("/api/applicant/tracker/applications/a-1/interview-prep")

    assert r.status_code == 200
    assert r.json() == {"generated": False}


def test_interview_prep_requires_auth():
    client = TestClient(_make_tracker_app(authed=False))
    r = client.get("/api/applicant/tracker/applications/a-1/interview-prep")
    assert r.status_code in (401, 403)


def test_interview_prep_owner_isolation_two_owners_never_cross_contaminate(tracker_client):
    # -- "owner A" ---------------------------------------------------------
    _FakeTrackerEngine.campaigns = [{"id": "owner-a-campaign", "name": "Alice's Search"}]
    _FakeTrackerEngine.boards = {
        "owner-a-campaign": {"applications": [_tracker_row("owner-a-app", signals=["interview_invited"])]}
    }
    _FakeTrackerEngine.prep_results = {
        ("owner-a-campaign", "owner-a-app"): {"generated": True, "company": "Alice's Employer"}
    }
    r_a = tracker_client.get("/api/applicant/tracker/applications/owner-a-app/interview-prep")
    assert r_a.status_code == 200
    assert r_a.json()["company"] == "Alice's Employer"

    # -- "owner B" (a completely disjoint campaign/application universe) ---
    _FakeTrackerEngine.campaigns = [{"id": "owner-b-campaign", "name": "Bob's Search"}]
    _FakeTrackerEngine.boards = {
        "owner-b-campaign": {"applications": [_tracker_row("owner-b-app", signals=["interview_invited"])]}
    }

    # Owner B can never fetch owner A's interview-prep brief by guessing the id.
    # (Owner A's OWN earlier request above legitimately made ONE interview_prep
    # call already -- what matters is that owner B's attempt never makes a
    # SECOND one; the fan-out reads (list_campaigns/tracker_board) are fine.)
    prep_calls_before = [c for c in _FakeTrackerEngine.calls if c[0] == "interview_prep"]
    r_leak = tracker_client.get("/api/applicant/tracker/applications/owner-a-app/interview-prep")
    assert r_leak.status_code == 404
    prep_calls_after = [c for c in _FakeTrackerEngine.calls if c[0] == "interview_prep"]
    assert prep_calls_after == prep_calls_before  # no new interview_prep call
