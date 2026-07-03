"""Regression coverage for dark-engine audit item #25: the application-history
drill-down list, promoted out of admin-only.

``GET /api/admin/history/{campaign_id}`` (``src/applicant/app/routers/
admin.py``) already returns per-application ``status``/``work_mode``/
``screenshot_count``/``outcomes[]`` -- exactly the tracker-board drill-down
payload -- but it was proxied ONLY through the admin-gated
``routes/applicant_admin_routes.py`` and rendered only inside the admin-only
Debug modal (``applicantDebug.js``). This wires an OWNER-scoped (not
admin-gated) equivalent:

  * ``workspace/src/applicant_engine.py`` -- new ``tracker_application_history``
    client method hitting the SAME engine path
    (``GET /api/admin/history/{campaign_id}``) the admin proxy's
    ``admin_application_history`` already hits.
  * ``workspace/routes/applicant_tracker_routes.py`` -- new
    ``GET /api/applicant/tracker/applications/{application_id}/history`` proxy,
    APPLICATION-scoped, reusing the tracker's existing ``_owner_tracker_rows``
    fan-out unchanged (mirrors ``interview_prep`` exactly: derive the
    campaign id from THIS request's own board fan-out, never a
    caller-supplied one).
  * ``workspace/static/js/applicantTracker.js`` -- the new per-row "View
    details" disclosure + its toggle handler. Source-level shape of that
    module is pinned in ``test_applicant_tracker_history_detail_ui.py``.

Mirrors ``test_applicant_backlog_screeninglibrary.py``'s ``interview_prep``
test block (same fake engine shape, same owner-isolation mandatory test). Per
this series' standing DoD, each assertion below was verified, by hand, to
actually go RED when the corresponding piece of the chain is reverted, then
confirmed GREEN again after restoring.
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


class _FakeHistoryEngine:
    """Stand-in for ApplicantEngineClient over the tracker proxy.

    Mirrors ``test_applicant_tracker_routes.py``'s ``FakeEngine`` (campaigns +
    per-campaign boards) plus the new ``tracker_application_history`` call.
    """

    calls: list = []
    campaigns: list = []
    boards: dict = {}
    history_results: dict = {}  # campaign_id -> engine payload
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

    async def tracker_application_history(self, campaign_id, limit=200):
        type(self).calls.append(("tracker_application_history", campaign_id, limit))
        key = ("tracker_application_history", campaign_id)
        if key in type(self).raises:
            raise type(self).raises[key]
        return type(self).history_results.get(
            campaign_id, {"campaign_id": campaign_id, "applications": []}
        )


@pytest.fixture(autouse=True)
def _reset_fake_history_engine():
    _FakeHistoryEngine.calls = []
    _FakeHistoryEngine.campaigns = []
    _FakeHistoryEngine.boards = {}
    _FakeHistoryEngine.history_results = {}
    _FakeHistoryEngine.raises = {}
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


def _history_row(app_id, *, status="AWAITING_RESPONSE", work_mode="remote",
                  screenshot_count=3, outcomes=None):
    return {
        "application_id": app_id,
        "status": status,
        "role_name": "Backend Engineer",
        "job_title": "Backend Engineer",
        "work_mode": work_mode,
        "root_url": "https://example.com/careers",
        "resume_variant_id": "rv-1",
        "screenshot_count": screenshot_count,
        "outcomes": outcomes or [],
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
    monkeypatch.setattr(tracker_routes, "ApplicantEngineClient", _FakeHistoryEngine)
    return TestClient(_make_tracker_app())


# --- happy path ---------------------------------------------------------------


def test_history_forwards_the_rows_own_campaign_id(tracker_client):
    _FakeHistoryEngine.campaigns = [{"id": "c1", "name": "Backend"}]
    _FakeHistoryEngine.boards = {"c1": {"applications": [_tracker_row("a-1")]}}
    _FakeHistoryEngine.history_results = {
        "c1": {
            "campaign_id": "c1",
            "applications": [
                _history_row(
                    "a-1",
                    status="AWAITING_RESPONSE",
                    work_mode="remote",
                    screenshot_count=4,
                    outcomes=[{"type": "submitted", "source": "engine"}],
                )
            ],
        }
    }

    r = tracker_client.get("/api/applicant/tracker/applications/a-1/history")

    assert r.status_code == 200
    body = r.json()
    assert body["found"] is True
    assert body["application_id"] == "a-1"
    assert body["status"] == "AWAITING_RESPONSE"
    assert body["work_mode"] == "remote"
    assert body["screenshot_count"] == 4
    assert body["outcomes"] == [{"type": "submitted", "source": "engine"}]
    assert ("tracker_application_history", "c1", 200) in _FakeHistoryEngine.calls


def test_history_narrows_to_the_one_application_out_of_the_campaigns_full_list(tracker_client):
    # The engine read returns EVERY application in the campaign; the route must
    # narrow down to the one the caller asked for, not just forward the whole
    # campaign payload.
    _FakeHistoryEngine.campaigns = [{"id": "c1", "name": "Backend"}]
    _FakeHistoryEngine.boards = {
        "c1": {"applications": [_tracker_row("a-1"), _tracker_row("a-2")]}
    }
    _FakeHistoryEngine.history_results = {
        "c1": {
            "campaign_id": "c1",
            "applications": [
                _history_row("a-1", screenshot_count=1),
                _history_row("a-2", screenshot_count=9),
            ],
        }
    }

    r = tracker_client.get("/api/applicant/tracker/applications/a-2/history")

    assert r.status_code == 200
    body = r.json()
    assert body["application_id"] == "a-2"
    assert body["screenshot_count"] == 9


def test_history_missing_from_engine_payload_is_404(tracker_client):
    _FakeHistoryEngine.campaigns = [{"id": "c1", "name": "Backend"}]
    _FakeHistoryEngine.boards = {"c1": {"applications": [_tracker_row("a-1")]}}
    _FakeHistoryEngine.history_results = {"c1": {"campaign_id": "c1", "applications": []}}

    r = tracker_client.get("/api/applicant/tracker/applications/a-1/history")

    assert r.status_code == 404


# --- owner-isolation guard (mandatory) -----------------------------------------


def test_history_rejects_an_application_not_in_owners_own_board(tracker_client):
    # Mirrors record_outcome/scan_email/interview_prep's owner-isolation guard:
    # "a-1" belongs to c1, which this request's own fan-out returns; a
    # caller-supplied id for an application that never showed up there must
    # 404, and the engine read must never even be attempted.
    _FakeHistoryEngine.campaigns = [{"id": "c1", "name": "Backend"}]
    _FakeHistoryEngine.boards = {"c1": {"applications": [_tracker_row("a-1")]}}

    r = tracker_client.get("/api/applicant/tracker/applications/not-mine/history")

    assert r.status_code == 404
    assert not any(
        isinstance(c, tuple) and c[0] == "tracker_application_history"
        for c in _FakeHistoryEngine.calls
    )


def test_history_owner_isolation_two_owners_never_cross_contaminate(tracker_client):
    # -- "owner A" ---------------------------------------------------------
    _FakeHistoryEngine.campaigns = [{"id": "owner-a-campaign", "name": "Alice's Search"}]
    _FakeHistoryEngine.boards = {
        "owner-a-campaign": {"applications": [_tracker_row("owner-a-app")]}
    }
    _FakeHistoryEngine.history_results = {
        "owner-a-campaign": {
            "campaign_id": "owner-a-campaign",
            "applications": [_history_row("owner-a-app", work_mode="hybrid")],
        }
    }
    r_a = tracker_client.get("/api/applicant/tracker/applications/owner-a-app/history")
    assert r_a.status_code == 200
    assert r_a.json()["work_mode"] == "hybrid"

    # -- "owner B" (a completely disjoint campaign/application universe) ---
    _FakeHistoryEngine.campaigns = [{"id": "owner-b-campaign", "name": "Bob's Search"}]
    _FakeHistoryEngine.boards = {
        "owner-b-campaign": {"applications": [_tracker_row("owner-b-app")]}
    }

    # Owner B can never fetch owner A's history detail by guessing the id.
    # (Owner A's OWN earlier request above legitimately made ONE
    # tracker_application_history call already -- what matters is that owner
    # B's attempt never makes a SECOND one for owner A's campaign; the
    # fan-out reads (list_campaigns/tracker_board) are fine.)
    calls_before = [
        c for c in _FakeHistoryEngine.calls
        if isinstance(c, tuple) and c[0] == "tracker_application_history"
    ]
    r_leak = tracker_client.get("/api/applicant/tracker/applications/owner-a-app/history")
    assert r_leak.status_code == 404
    calls_after = [
        c for c in _FakeHistoryEngine.calls
        if isinstance(c, tuple) and c[0] == "tracker_application_history"
    ]
    assert calls_after == calls_before  # no new call, and never against A's campaign

    # Owner B CAN read their own application's history.
    _FakeHistoryEngine.history_results = {
        "owner-b-campaign": {
            "campaign_id": "owner-b-campaign",
            "applications": [_history_row("owner-b-app", work_mode="onsite")],
        }
    }
    r_own = tracker_client.get("/api/applicant/tracker/applications/owner-b-app/history")
    assert r_own.status_code == 200
    assert r_own.json()["work_mode"] == "onsite"
    assert "Alice" not in str(r_own.json())


# --- soft-degrade / auth --------------------------------------------------------


def test_history_engine_unavailable_is_soft(tracker_client):
    _FakeHistoryEngine.raises = {"list_campaigns": EngineError("down", status=None)}

    r = tracker_client.get("/api/applicant/tracker/applications/a-1/history")

    assert r.status_code == 200
    assert r.json()["found"] is False


def test_history_requires_auth():
    client = TestClient(_make_tracker_app(authed=False))
    r = client.get("/api/applicant/tracker/applications/a-1/history")
    assert r.status_code in (401, 403)


# --- engine-client + proxy shape -------------------------------------------------


def test_engine_client_exposes_tracker_application_history():
    """The workspace's ApplicantEngineClient carries the new
    tracker_application_history method -- not an ad hoc inline request --
    and hits the EXACT SAME engine path the admin proxy's
    admin_application_history already hits."""
    src = ENGINE_CLIENT_PY.read_text(encoding="utf-8")
    assert "async def tracker_application_history(self, campaign_id: str, limit: int = 200)" in src
    assert '"GET", f"/api/admin/history/{campaign_id}", params={"limit": limit}' in src
