"""Regression coverage for dark-engine audit item #62: the paused/stuck
applications panel on the owner-facing Tracker.

After 5 consecutive failed resume attempts the engine's ``AgentLoop`` stops
re-driving an application and fires ONE deduped notification (``agent_loop.py``
``_record_resume_failure`` / the process-lived ``ResumeLedger``) — but nothing
LISTED the give-up set and nothing CLEARED it short of a full engine process
restart. This wires the full chain:

  * ``src/applicant/application/services/agent_loop.py`` -- new
    ``AgentLoop.list_given_up`` / ``AgentLoop.retry_given_up``, reading/
    mutating the SAME process-lived ``ResumeLedger`` the tick loop uses.
  * ``src/applicant/app/routers/admin.py`` -- new
    ``GET /api/admin/stuck-applications/{campaign_id}`` and
    ``POST /api/admin/stuck-applications/{application_id}/retry``.
  * ``workspace/src/applicant_engine.py`` -- new ``admin_stuck_applications`` /
    ``admin_retry_stuck_application`` client methods.
  * ``workspace/routes/applicant_tracker_routes.py`` -- new
    ``GET /api/applicant/tracker/stuck`` (fans out across the owner's own
    campaigns, mirroring ``_owner_tracker_rows``) and
    ``POST /api/applicant/tracker/applications/{application_id}/retry``
    (owner-isolated the same way as ``record_outcome``/``scan_email``).
  * ``workspace/static/js/applicantTracker.js`` -- the new paused-applications
    panel + its "Retry now" handler (source-shape pinned below).

This is a SEPARATE surface from the tracker board / "View details" disclosure:
a stuck application is parked in a pre-submission working state, so it would
never appear in ``tracker_board``'s (submitted-only) rows. Mirrors
``test_applicant_tracker_history_detail.py``'s fake-engine shape and mandatory
owner-isolation test. Every assertion below was revert-verified: reverting the
corresponding piece of the chain makes that test fail (RED), restoring it
makes it pass again (GREEN).
"""

from __future__ import annotations

import pathlib

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import routes.applicant_tracker_routes as tracker_routes
from routes.applicant_tracker_routes import setup_applicant_tracker_routes
from src.applicant_engine import EngineError

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
ENGINE_CLIENT_PY = REPO_ROOT / "workspace" / "src" / "applicant_engine.py"
TRACKER_JS = REPO_ROOT / "workspace" / "static" / "js" / "applicantTracker.js"


class _FakeStuckEngine:
    """Stand-in for ApplicantEngineClient over the tracker proxy.

    Mirrors ``test_applicant_tracker_history_detail.py``'s ``_FakeHistoryEngine``
    (campaigns fan-out) plus the new stuck-applications read/retry calls.
    """

    calls: list = []
    campaigns: list = []
    stuck: dict = {}  # campaign_id -> engine payload
    retry_results: dict = {}  # application_id -> engine payload
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

    async def admin_stuck_applications(self, campaign_id):
        type(self).calls.append(("admin_stuck_applications", campaign_id))
        key = ("admin_stuck_applications", campaign_id)
        if key in type(self).raises:
            raise type(self).raises[key]
        return type(self).stuck.get(campaign_id, {"applications": []})

    async def admin_retry_stuck_application(self, application_id):
        type(self).calls.append(("admin_retry_stuck_application", application_id))
        key = ("admin_retry_stuck_application", application_id)
        if key in type(self).raises:
            raise type(self).raises[key]
        return type(self).retry_results.get(application_id, {"retried": True})


@pytest.fixture(autouse=True)
def _reset_fake_stuck_engine():
    _FakeStuckEngine.calls = []
    _FakeStuckEngine.campaigns = []
    _FakeStuckEngine.stuck = {}
    _FakeStuckEngine.retry_results = {}
    _FakeStuckEngine.raises = {}
    yield


def _stuck_row(app_id, *, failures=5, job_title="Backend Engineer", company="Acme"):
    return {
        "application_id": app_id,
        "campaign_id": "c1",
        "status": "BLOCKED_QUESTION",
        "failures": failures,
        "job_title": job_title,
        "company": company,
        "role_name": job_title,
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
    monkeypatch.setattr(tracker_routes, "ApplicantEngineClient", _FakeStuckEngine)
    return TestClient(_make_tracker_app())


# --- happy path: GET /stuck ------------------------------------------------


def test_stuck_lists_given_up_applications_across_campaigns(tracker_client):
    _FakeStuckEngine.campaigns = [
        {"id": "c1", "name": "Backend search"},
        {"id": "c2", "name": "Frontend search"},
    ]
    _FakeStuckEngine.stuck = {
        "c1": {"applications": [_stuck_row("a-1", failures=5)]},
        "c2": {"applications": [_stuck_row("a-2", failures=8, job_title="Frontend Engineer")]},
    }

    r = tracker_client.get("/api/applicant/tracker/stuck")

    assert r.status_code == 200
    body = r.json()
    assert body["engine_available"] is True
    assert body["has_data"] is True
    ids = {row["application_id"] for row in body["applications"]}
    assert ids == {"a-1", "a-2"}
    # Worst failure count first.
    assert body["applications"][0]["application_id"] == "a-2"
    assert ("admin_stuck_applications", "c1") in _FakeStuckEngine.calls
    assert ("admin_stuck_applications", "c2") in _FakeStuckEngine.calls


def test_stuck_empty_is_well_formed(tracker_client):
    _FakeStuckEngine.campaigns = [{"id": "c1", "name": "Backend search"}]
    _FakeStuckEngine.stuck = {"c1": {"applications": []}}

    r = tracker_client.get("/api/applicant/tracker/stuck")

    assert r.status_code == 200
    body = r.json()
    assert body["has_data"] is False
    assert body["applications"] == []


def test_stuck_no_campaigns_is_well_formed(tracker_client):
    _FakeStuckEngine.campaigns = []

    r = tracker_client.get("/api/applicant/tracker/stuck")

    assert r.status_code == 200
    body = r.json()
    assert body["has_data"] is False
    assert body["applications"] == []


# --- happy path: POST retry -------------------------------------------------


def test_retry_clears_owners_own_stuck_application(tracker_client):
    _FakeStuckEngine.campaigns = [{"id": "c1", "name": "Backend search"}]
    _FakeStuckEngine.stuck = {"c1": {"applications": [_stuck_row("a-1")]}}
    _FakeStuckEngine.retry_results = {"a-1": {"application_id": "a-1", "retried": True}}

    r = tracker_client.post("/api/applicant/tracker/applications/a-1/retry")

    assert r.status_code == 200
    assert r.json()["retried"] is True
    assert ("admin_retry_stuck_application", "a-1") in _FakeStuckEngine.calls


# --- owner-isolation guard (mandatory) --------------------------------------


def test_retry_rejects_an_application_not_in_owners_own_stuck_list(tracker_client):
    # "a-1" belongs to c1, which this request's own fan-out returns; a
    # caller-supplied id for an application that never showed up there must
    # 404, and the retry write must never even be attempted.
    _FakeStuckEngine.campaigns = [{"id": "c1", "name": "Backend search"}]
    _FakeStuckEngine.stuck = {"c1": {"applications": [_stuck_row("a-1")]}}

    r = tracker_client.post("/api/applicant/tracker/applications/not-mine/retry")

    assert r.status_code == 404
    assert not any(
        isinstance(c, tuple) and c[0] == "admin_retry_stuck_application"
        for c in _FakeStuckEngine.calls
    )


def test_retry_owner_isolation_two_owners_never_cross_contaminate(tracker_client):
    # -- "owner A" ---------------------------------------------------------
    _FakeStuckEngine.campaigns = [{"id": "owner-a-campaign", "name": "Alice's Search"}]
    _FakeStuckEngine.stuck = {
        "owner-a-campaign": {"applications": [_stuck_row("owner-a-app")]}
    }
    _FakeStuckEngine.retry_results = {"owner-a-app": {"retried": True}}
    r_a = tracker_client.post("/api/applicant/tracker/applications/owner-a-app/retry")
    assert r_a.status_code == 200

    # -- "owner B" (a completely disjoint campaign/application universe) ---
    _FakeStuckEngine.campaigns = [{"id": "owner-b-campaign", "name": "Bob's Search"}]
    _FakeStuckEngine.stuck = {
        "owner-b-campaign": {"applications": [_stuck_row("owner-b-app")]}
    }

    calls_before = [
        c for c in _FakeStuckEngine.calls
        if isinstance(c, tuple) and c[0] == "admin_retry_stuck_application"
    ]
    r_leak = tracker_client.post("/api/applicant/tracker/applications/owner-a-app/retry")
    assert r_leak.status_code == 404
    calls_after = [
        c for c in _FakeStuckEngine.calls
        if isinstance(c, tuple) and c[0] == "admin_retry_stuck_application"
    ]
    assert calls_after == calls_before  # no new call leaked through

    # Owner B CAN retry their own stuck application.
    _FakeStuckEngine.retry_results = {"owner-b-app": {"retried": True}}
    r_own = tracker_client.post("/api/applicant/tracker/applications/owner-b-app/retry")
    assert r_own.status_code == 200


# --- soft-degrade / auth --------------------------------------------------------


def test_stuck_engine_unavailable_is_soft(tracker_client):
    _FakeStuckEngine.raises = {"list_campaigns": EngineError("down", status=None)}

    r = tracker_client.get("/api/applicant/tracker/stuck")

    assert r.status_code == 200
    assert r.json()["engine_available"] is False
    assert r.json()["applications"] == []


def test_retry_engine_unavailable_is_503(tracker_client):
    _FakeStuckEngine.raises = {"list_campaigns": EngineError("down", status=None)}

    r = tracker_client.post("/api/applicant/tracker/applications/a-1/retry")

    assert r.status_code == 503


def test_stuck_requires_auth():
    client = TestClient(_make_tracker_app(authed=False))
    r = client.get("/api/applicant/tracker/stuck")
    assert r.status_code in (401, 403)


def test_retry_requires_auth():
    client = TestClient(_make_tracker_app(authed=False))
    r = client.post("/api/applicant/tracker/applications/a-1/retry")
    assert r.status_code in (401, 403)


# --- engine-client + proxy shape -------------------------------------------------


def test_engine_client_exposes_stuck_application_methods():
    """The workspace's ApplicantEngineClient carries the new
    admin_stuck_applications / admin_retry_stuck_application methods -- not an
    ad hoc inline request -- and hits the engine's own #62 admin routes."""
    src = ENGINE_CLIENT_PY.read_text(encoding="utf-8")
    assert "async def admin_stuck_applications(self, campaign_id: str)" in src
    assert '"GET", f"/api/admin/stuck-applications/{campaign_id}"' in src
    assert "async def admin_retry_stuck_application(self, application_id: str)" in src
    assert '"POST", f"/api/admin/stuck-applications/{application_id}/retry"' in src


def test_tracker_js_has_a_paused_applications_panel_not_a_per_row_disclosure():
    """The stuck-applications UI is a SEPARATE panel (it spans multiple
    applications, never per-row) — not another addition inside the per-row
    "View details" <details> disclosure block."""
    src = TRACKER_JS.read_text(encoding="utf-8")
    assert "applicant-tracker-stuck" in src
    assert "data-stuck-retry" in src
    assert "${API}/stuck" in src
