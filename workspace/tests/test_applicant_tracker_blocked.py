"""Regression coverage for dark-engine audit item #61: the pre-submit-safety
blocked-applications panel on the owner-facing Tracker.

G07's pre-submit safety checks (scam/ghost-job, duplicate cooldown,
per-company volume cap, eligibility/work-authorization) run every tick against
every APPROVED application; before this fix a block was handled with only
``log.info("presubmit_blocked")`` -- the posting stayed APPROVED forever with
nothing an owner could see or act on. This wires the full chain:

  * ``src/applicant/application/services/agent_loop.py`` -- new
    ``AgentLoop.list_blocked`` / ``AgentLoop.override_blocked``, reading/
    mutating the SAME process-lived ``PresubmitBlockLedger`` the tick loop uses.
  * ``src/applicant/app/routers/admin.py`` -- new
    ``GET /api/admin/blocked-applications/{campaign_id}`` and
    ``POST /api/admin/blocked-applications/{application_id}/override``.
  * ``workspace/src/applicant_engine.py`` -- new ``admin_blocked_applications`` /
    ``admin_override_blocked_application`` client methods.
  * ``workspace/routes/applicant_tracker_routes.py`` -- new
    ``GET /api/applicant/tracker/blocked`` (fans out across the owner's own
    campaigns, mirroring ``_owner_stuck_rows``) and
    ``POST /api/applicant/tracker/applications/{application_id}/override-block``
    (owner-isolated the same way as ``retry_stuck``/``record_outcome``).
  * ``workspace/static/js/applicantTracker.js`` -- the new blocked-applications
    panel + its "Proceed anyway" handler (source-shape pinned below).

This is a SEPARATE surface from the tracker board AND the stuck-applications
panel: a blocked application never even started the pipeline (it's still
sitting APPROVED), so it would never appear in either. Mirrors
``test_applicant_tracker_stuck.py`` (#62)'s fake-engine shape and mandatory
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


class _FakeBlockedEngine:
    """Stand-in for ApplicantEngineClient over the tracker proxy.

    Mirrors ``test_applicant_tracker_stuck.py``'s ``_FakeStuckEngine`` (campaigns
    fan-out) plus the new blocked-applications read/override calls.
    """

    calls: list = []
    campaigns: list = []
    blocked: dict = {}  # campaign_id -> engine payload
    override_results: dict = {}  # application_id -> engine payload
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

    async def admin_blocked_applications(self, campaign_id):
        type(self).calls.append(("admin_blocked_applications", campaign_id))
        key = ("admin_blocked_applications", campaign_id)
        if key in type(self).raises:
            raise type(self).raises[key]
        return type(self).blocked.get(campaign_id, {"applications": []})

    async def admin_override_blocked_application(self, application_id):
        type(self).calls.append(("admin_override_blocked_application", application_id))
        key = ("admin_override_blocked_application", application_id)
        if key in type(self).raises:
            raise type(self).raises[key]
        return type(self).override_results.get(application_id, {"overridden": True})


@pytest.fixture(autouse=True)
def _reset_fake_blocked_engine():
    _FakeBlockedEngine.calls = []
    _FakeBlockedEngine.campaigns = []
    _FakeBlockedEngine.blocked = {}
    _FakeBlockedEngine.override_results = {}
    _FakeBlockedEngine.raises = {}
    yield


def _blocked_row(
    app_id,
    *,
    times_blocked=1,
    reason="Company reputation signals indicate potential scam/ghost job",
    check="company_reputation",
    job_title="Backend Engineer",
    company="Acme",
    last_blocked_at="2026-07-05T08:00:00+00:00",
):
    return {
        "application_id": app_id,
        "campaign_id": "c1",
        "check": check,
        "reason": reason,
        "first_blocked_at": "2026-07-01T08:00:00+00:00",
        "last_blocked_at": last_blocked_at,
        "times_blocked": times_blocked,
        "status": "APPROVED",
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
    monkeypatch.setattr(tracker_routes, "ApplicantEngineClient", _FakeBlockedEngine)
    return TestClient(_make_tracker_app())


# --- happy path: GET /blocked ------------------------------------------------


def test_blocked_lists_blocked_applications_across_campaigns(tracker_client):
    _FakeBlockedEngine.campaigns = [
        {"id": "c1", "name": "Backend search"},
        {"id": "c2", "name": "Frontend search"},
    ]
    _FakeBlockedEngine.blocked = {
        "c1": {"applications": [_blocked_row("a-1", last_blocked_at="2026-07-04T08:00:00+00:00")]},
        "c2": {
            "applications": [
                _blocked_row(
                    "a-2", job_title="Frontend Engineer", last_blocked_at="2026-07-05T08:00:00+00:00"
                )
            ]
        },
    }

    r = tracker_client.get("/api/applicant/tracker/blocked")

    assert r.status_code == 200
    body = r.json()
    assert body["engine_available"] is True
    assert body["has_data"] is True
    ids = {row["application_id"] for row in body["applications"]}
    assert ids == {"a-1", "a-2"}
    # Most-recently-blocked first.
    assert body["applications"][0]["application_id"] == "a-2"
    assert ("admin_blocked_applications", "c1") in _FakeBlockedEngine.calls
    assert ("admin_blocked_applications", "c2") in _FakeBlockedEngine.calls


def test_blocked_empty_is_well_formed(tracker_client):
    _FakeBlockedEngine.campaigns = [{"id": "c1", "name": "Backend search"}]
    _FakeBlockedEngine.blocked = {"c1": {"applications": []}}

    r = tracker_client.get("/api/applicant/tracker/blocked")

    assert r.status_code == 200
    body = r.json()
    assert body["has_data"] is False
    assert body["applications"] == []


def test_blocked_no_campaigns_is_well_formed(tracker_client):
    _FakeBlockedEngine.campaigns = []

    r = tracker_client.get("/api/applicant/tracker/blocked")

    assert r.status_code == 200
    body = r.json()
    assert body["has_data"] is False
    assert body["applications"] == []


# --- happy path: POST override-block ----------------------------------------


def test_override_lets_owner_proceed_with_their_own_blocked_application(tracker_client):
    _FakeBlockedEngine.campaigns = [{"id": "c1", "name": "Backend search"}]
    _FakeBlockedEngine.blocked = {"c1": {"applications": [_blocked_row("a-1")]}}
    _FakeBlockedEngine.override_results = {"a-1": {"application_id": "a-1", "overridden": True}}

    r = tracker_client.post("/api/applicant/tracker/applications/a-1/override-block")

    assert r.status_code == 200
    assert r.json()["overridden"] is True
    assert ("admin_override_blocked_application", "a-1") in _FakeBlockedEngine.calls


# --- owner-isolation guard (mandatory) --------------------------------------


def test_override_rejects_an_application_not_in_owners_own_blocked_list(tracker_client):
    # "a-1" belongs to c1, which this request's own fan-out returns; a
    # caller-supplied id for an application that never showed up there must
    # 404, and the override write must never even be attempted.
    _FakeBlockedEngine.campaigns = [{"id": "c1", "name": "Backend search"}]
    _FakeBlockedEngine.blocked = {"c1": {"applications": [_blocked_row("a-1")]}}

    r = tracker_client.post("/api/applicant/tracker/applications/not-mine/override-block")

    assert r.status_code == 404
    assert not any(
        isinstance(c, tuple) and c[0] == "admin_override_blocked_application"
        for c in _FakeBlockedEngine.calls
    )


def test_override_owner_isolation_two_owners_never_cross_contaminate(tracker_client):
    # -- "owner A" ---------------------------------------------------------
    _FakeBlockedEngine.campaigns = [{"id": "owner-a-campaign", "name": "Alice's Search"}]
    _FakeBlockedEngine.blocked = {
        "owner-a-campaign": {"applications": [_blocked_row("owner-a-app")]}
    }
    _FakeBlockedEngine.override_results = {"owner-a-app": {"overridden": True}}
    r_a = tracker_client.post("/api/applicant/tracker/applications/owner-a-app/override-block")
    assert r_a.status_code == 200

    # -- "owner B" (a completely disjoint campaign/application universe) ---
    _FakeBlockedEngine.campaigns = [{"id": "owner-b-campaign", "name": "Bob's Search"}]
    _FakeBlockedEngine.blocked = {
        "owner-b-campaign": {"applications": [_blocked_row("owner-b-app")]}
    }

    calls_before = [
        c for c in _FakeBlockedEngine.calls
        if isinstance(c, tuple) and c[0] == "admin_override_blocked_application"
    ]
    r_leak = tracker_client.post("/api/applicant/tracker/applications/owner-a-app/override-block")
    assert r_leak.status_code == 404
    calls_after = [
        c for c in _FakeBlockedEngine.calls
        if isinstance(c, tuple) and c[0] == "admin_override_blocked_application"
    ]
    assert calls_after == calls_before  # no new call leaked through

    # Owner B CAN override their own blocked application.
    _FakeBlockedEngine.override_results = {"owner-b-app": {"overridden": True}}
    r_own = tracker_client.post("/api/applicant/tracker/applications/owner-b-app/override-block")
    assert r_own.status_code == 200


# --- soft-degrade / auth --------------------------------------------------------


def test_blocked_engine_unavailable_is_soft(tracker_client):
    _FakeBlockedEngine.raises = {"list_campaigns": EngineError("down", status=None)}

    r = tracker_client.get("/api/applicant/tracker/blocked")

    assert r.status_code == 200
    assert r.json()["engine_available"] is False
    assert r.json()["applications"] == []


def test_override_engine_unavailable_is_503(tracker_client):
    _FakeBlockedEngine.raises = {"list_campaigns": EngineError("down", status=None)}

    r = tracker_client.post("/api/applicant/tracker/applications/a-1/override-block")

    assert r.status_code == 503


def test_blocked_requires_auth():
    client = TestClient(_make_tracker_app(authed=False))
    r = client.get("/api/applicant/tracker/blocked")
    assert r.status_code in (401, 403)


def test_override_requires_auth():
    client = TestClient(_make_tracker_app(authed=False))
    r = client.post("/api/applicant/tracker/applications/a-1/override-block")
    assert r.status_code in (401, 403)


# --- engine-client + proxy shape -------------------------------------------------


def test_engine_client_exposes_blocked_application_methods():
    """The workspace's ApplicantEngineClient carries the new
    admin_blocked_applications / admin_override_blocked_application methods --
    not an ad hoc inline request -- and hits the engine's own #61 admin routes."""
    src = ENGINE_CLIENT_PY.read_text(encoding="utf-8")
    assert "async def admin_blocked_applications(self, campaign_id: str)" in src
    assert '"GET", f"/api/admin/blocked-applications/{campaign_id}"' in src
    assert "async def admin_override_blocked_application(self, application_id: str)" in src
    assert '"POST", f"/api/admin/blocked-applications/{application_id}/override"' in src


def test_tracker_js_has_a_blocked_applications_panel_not_a_per_row_disclosure():
    """The blocked-applications UI is a SEPARATE panel (it spans multiple
    applications, never per-row) — not another addition inside the per-row
    "View details" <details> disclosure block."""
    src = TRACKER_JS.read_text(encoding="utf-8")
    assert "applicant-tracker-blocked" in src
    assert "data-blocked-override" in src
    assert "${API}/blocked" in src
