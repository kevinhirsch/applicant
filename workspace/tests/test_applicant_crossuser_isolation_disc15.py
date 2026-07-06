"""Regression coverage for DISC-15: cross-account isolation on the
pending/campaigns/tracker/activity proxies.

The Applicant engine is SINGLE-TENANT per deployment -- it has no owner
concept at all, so ``list_campaigns()``/tracker board/activity status/pending
actions all return the SAME data to every workspace account that calls them.
Before this fix, ``applicant_campaigns_routes.py``, ``applicant_tracker_routes.py``,
and ``applicant_activity_routes.py`` gated their read/list endpoints only with
``require_user`` (any authenticated user), and ``applicant_portal_routes.py``'s
``GET /pending`` did the same -- so a SECOND, unrelated workspace account could
read the real owner's pending actions, campaign config, tracker board, and
agent-activity feed.

Fixed by factoring PR #626's ``_require_notification_owner`` gate out into
``src.auth_helpers.require_engine_owner`` and applying it to the read/list
endpoints on all four proxies: in single-user / unconfigured mode there is no
admin distinction (the lone owner still passes, matching the rest of the
workspace); once the workspace is configured for MULTIPLE accounts, only an
admin may reach these surfaces.

Follows the exact two-account convention of
``test_applicant_inbox_owner_scope_lens10.py``: a tiny ``_AuthMgr`` stub on
``app.state.auth_manager`` plus a middleware that authenticates as whichever
user the test names. The engine is faked with a scripted double; zero
network.

Hand-verified RED-on-revert / GREEN-on-restore: temporarily reverting the
gate on each endpoint below (back to ``require_user`` / the local
``_require_user`` wrapper) makes every ``test_*_non_owner_denied`` test in
this file fail (a non-admin second account gets 200 instead of 401/403);
restoring the fix turns them green again.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import routes.applicant_activity_routes as activity_mod
import routes.applicant_campaigns_routes as campaigns_mod
import routes.applicant_portal_routes as portal_mod
import routes.applicant_tracker_routes as tracker_mod
from routes.applicant_activity_routes import setup_applicant_activity_routes
from routes.applicant_campaigns_routes import setup_applicant_campaigns_routes
from routes.applicant_portal_routes import setup_applicant_portal_routes
from routes.applicant_tracker_routes import setup_applicant_tracker_routes


class _AuthMgr:
    """Minimal stand-in for the real ``AuthManager`` (mirrors the #626 inbox
    tests' ``_AuthMgr`` exactly)."""

    def __init__(self, *, configured: bool, admins: set[str] | None = None):
        self.is_configured = configured
        self._admins = set(admins or ())

    def is_admin(self, user: str) -> bool:
        return user in self._admins


def _mount(router_factory, *, user, configured: bool, admins=("owner",)) -> FastAPI:
    app = FastAPI()
    app.state.auth_manager = _AuthMgr(configured=configured, admins=admins)

    @app.middleware("http")
    async def _auth(request, call_next):
        request.state.current_user = user
        return await call_next(request)

    app.include_router(router_factory())
    return app


# --- a single shared scripted fake engine covering all four surfaces --------


class FakeEngine:
    """Stands in for ApplicantEngineClient as an async context manager, with
    just enough scripted data for one read call per surface."""

    calls: list = []
    campaigns: list = [{"id": "c1", "name": "Backend roles"}]
    pending: dict = {"c1": {"campaign_id": "c1", "count": 0, "items": []}}
    onboarding: dict = {}
    tracker_boards: dict = {"c1": {"applications": []}}
    activity_status: dict = {"c1": {"active": True, "applied_today": 0}}
    sources: dict = {"c1": {"items": []}}

    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return None

    # -- shared --
    async def list_campaigns(self):
        FakeEngine.calls.append("list_campaigns")
        return FakeEngine.campaigns

    # -- portal / pending --
    async def list_pending_actions(self, cid):
        FakeEngine.calls.append(("list_pending_actions", cid))
        return FakeEngine.pending.get(cid, {"campaign_id": cid, "count": 0, "items": []})

    async def onboarding_state(self, cid):
        FakeEngine.calls.append(("onboarding_state", cid))
        return FakeEngine.onboarding.get(cid, {"complete": True, "missing_sections": []})

    # -- campaigns --
    async def list_discovery_sources(self, cid):
        FakeEngine.calls.append(("list_discovery_sources", cid))
        return FakeEngine.sources.get(cid, {"items": []})

    # -- tracker --
    async def tracker_board(self, cid):
        FakeEngine.calls.append(("tracker_board", cid))
        return FakeEngine.tracker_boards.get(cid, {"applications": []})

    # -- activity --
    async def agent_run_status(self, cid):
        FakeEngine.calls.append(("agent_run_status", cid))
        return FakeEngine.activity_status.get(cid, {})


@pytest.fixture(autouse=True)
def _reset():
    FakeEngine.calls = []
    yield


@pytest.fixture(autouse=True)
def _patch_engines(monkeypatch):
    monkeypatch.setattr(portal_mod, "ApplicantEngineClient", FakeEngine)
    monkeypatch.setattr(campaigns_mod, "ApplicantEngineClient", FakeEngine)
    monkeypatch.setattr(tracker_mod, "ApplicantEngineClient", FakeEngine)
    monkeypatch.setattr(activity_mod, "ApplicantEngineClient", FakeEngine)


# --- surface 1: pending (Portal) --------------------------------------------


def test_pending_lone_owner_single_user_mode_passes():
    app = _mount(setup_applicant_portal_routes, user="solo", configured=False, admins=())
    c = TestClient(app)
    r = c.get("/api/applicant/portal/pending")
    assert r.status_code == 200
    assert r.json()["engine_available"] is True


def test_pending_owner_in_configured_mode_passes():
    app = _mount(setup_applicant_portal_routes, user="owner", configured=True, admins=("owner",))
    c = TestClient(app)
    r = c.get("/api/applicant/portal/pending")
    assert r.status_code == 200


def test_pending_second_account_denied():
    app = _mount(setup_applicant_portal_routes, user="teammate", configured=True, admins=("owner",))
    c = TestClient(app)
    r = c.get("/api/applicant/portal/pending")
    assert r.status_code == 403
    assert "list_campaigns" not in FakeEngine.calls


# --- surface 2: campaigns ----------------------------------------------------


def test_campaigns_lone_owner_single_user_mode_passes():
    app = _mount(setup_applicant_campaigns_routes, user="solo", configured=False, admins=())
    c = TestClient(app)
    r = c.get("/api/applicant/campaigns")
    assert r.status_code == 200
    assert r.json()["engine_available"] is True
    assert r.json()["campaigns"][0]["id"] == "c1"


def test_campaigns_owner_in_configured_mode_passes():
    app = _mount(setup_applicant_campaigns_routes, user="owner", configured=True, admins=("owner",))
    c = TestClient(app)
    r = c.get("/api/applicant/campaigns")
    assert r.status_code == 200


def test_campaigns_second_account_denied():
    app = _mount(setup_applicant_campaigns_routes, user="teammate", configured=True, admins=("owner",))
    c = TestClient(app)
    r = c.get("/api/applicant/campaigns")
    assert r.status_code == 403
    assert "list_campaigns" not in FakeEngine.calls


# --- surface 3: tracker -------------------------------------------------------


def test_tracker_lone_owner_single_user_mode_passes():
    app = _mount(setup_applicant_tracker_routes, user="solo", configured=False, admins=())
    c = TestClient(app)
    r = c.get("/api/applicant/tracker")
    assert r.status_code == 200
    assert r.json()["engine_available"] is True


def test_tracker_owner_in_configured_mode_passes():
    app = _mount(setup_applicant_tracker_routes, user="owner", configured=True, admins=("owner",))
    c = TestClient(app)
    r = c.get("/api/applicant/tracker")
    assert r.status_code == 200


def test_tracker_second_account_denied():
    app = _mount(setup_applicant_tracker_routes, user="teammate", configured=True, admins=("owner",))
    c = TestClient(app)
    r = c.get("/api/applicant/tracker")
    assert r.status_code == 403
    assert "list_campaigns" not in FakeEngine.calls


# --- surface 4: activity ------------------------------------------------------


def test_activity_lone_owner_single_user_mode_passes():
    app = _mount(setup_applicant_activity_routes, user="solo", configured=False, admins=())
    c = TestClient(app)
    r = c.get("/api/applicant/activity/status")
    assert r.status_code == 200
    assert r.json()["engine_available"] is True


def test_activity_owner_in_configured_mode_passes():
    app = _mount(setup_applicant_activity_routes, user="owner", configured=True, admins=("owner",))
    c = TestClient(app)
    r = c.get("/api/applicant/activity/status")
    assert r.status_code == 200


def test_activity_second_account_denied():
    app = _mount(setup_applicant_activity_routes, user="teammate", configured=True, admins=("owner",))
    c = TestClient(app)
    r = c.get("/api/applicant/activity/status")
    assert r.status_code == 403
    assert "list_campaigns" not in FakeEngine.calls


# --- unauthenticated is still rejected (gate must not fail open) -----------


def test_pending_unauthenticated_rejected():
    app = _mount(setup_applicant_portal_routes, user=None, configured=True, admins=("owner",))
    c = TestClient(app)
    r = c.get("/api/applicant/portal/pending")
    assert r.status_code == 401


def test_campaigns_unauthenticated_rejected():
    app = _mount(setup_applicant_campaigns_routes, user=None, configured=True, admins=("owner",))
    c = TestClient(app)
    r = c.get("/api/applicant/campaigns")
    assert r.status_code == 401


def test_tracker_unauthenticated_rejected():
    app = _mount(setup_applicant_tracker_routes, user=None, configured=True, admins=("owner",))
    c = TestClient(app)
    r = c.get("/api/applicant/tracker")
    assert r.status_code == 401


def test_activity_unauthenticated_rejected():
    app = _mount(setup_applicant_activity_routes, user=None, configured=True, admins=("owner",))
    c = TestClient(app)
    r = c.get("/api/applicant/activity/status")
    assert r.status_code == 401
