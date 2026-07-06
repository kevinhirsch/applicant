"""Regression coverage for DISC-15b: cross-account isolation on the
campaigns/tracker WRITE (mutating) endpoints.

DISC-15 closed the read-side of this hole: the engine is single-tenant (no
owner concept at all), so ``applicant_campaigns_routes.py`` /
``applicant_tracker_routes.py`` previously gated their read/list endpoints
with only ``require_user`` (any authenticated account), letting a second,
unrelated workspace account read the real owner's data. That fix factored a
shared ``src.auth_helpers.require_engine_owner`` gate and applied it to the
reads.

The WRITE endpoints had a residual hole: each mutator FIRST resolves the
caller's own campaign/application ids from the engine (e.g.
``_owner_campaign_ids`` / ``_owner_application_ids``) and rejects any id not
in that set. On a single-tenant engine that fan-out has no owner concept to
filter on either -- ``list_campaigns()`` returns the SAME campaigns/rows to
every workspace account, so the "id must belong to the caller" check was
trivially satisfied for ANY authenticated account. A second, unrelated
workspace account could still PATCH/clone/delete a campaign, toggle a
discovery source, or record an outcome/archive/mark-submitted/etc. against
the real owner's applications.

Fixed by switching every write endpoint in both files from the plain
auth-only gate (``require_user`` / the local ``_require_user`` wrapper) to
the SAME ``require_engine_owner`` gate the reads already use: in single-user
/ unconfigured mode there is no admin distinction (the lone owner still
passes, matching the rest of the workspace); once the workspace is
configured for MULTIPLE accounts, only an admin may reach these writes.

Follows the exact two-account convention of
``test_applicant_crossuser_isolation_disc15.py``: a tiny ``_AuthMgr`` stub on
``app.state.auth_manager`` plus a middleware that authenticates as whichever
user the test names. The engine is faked with a scripted double; zero
network.

Hand-verified RED-on-revert / GREEN-on-restore: temporarily reverting the
gate on ``update_campaign`` (back to ``require_user``) and ``record_outcome``
(back to ``_require_user``) makes ``test_campaigns_update_second_account_denied``
and ``test_tracker_outcome_second_account_denied`` below fail (a non-admin
second account gets 200 instead of 403, and the engine mutation IS called);
restoring the fix turns them green again and the mutation call disappears
from the fake engine's call log.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import routes.applicant_campaigns_routes as campaigns_mod
import routes.applicant_tracker_routes as tracker_mod
from routes.applicant_campaigns_routes import setup_applicant_campaigns_routes
from routes.applicant_tracker_routes import setup_applicant_tracker_routes


class _AuthMgr:
    """Minimal stand-in for the real ``AuthManager`` (mirrors DISC-15's
    ``_AuthMgr`` exactly)."""

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


# --- a single shared scripted fake engine covering both write surfaces ------


class FakeEngine:
    """Stands in for ApplicantEngineClient as an async context manager, with
    just enough scripted data to exercise one write call per surface."""

    calls: list = []
    campaigns: list = [{"id": "c1", "name": "Backend roles"}]
    tracker_boards: dict = {
        "c1": {"applications": [{"application_id": "app-1", "campaign_id": "c1"}]}
    }
    updated_campaign: dict = {"id": "c1", "name": "Renamed"}
    recorded_outcome: dict = {"application_id": "app-1", "outcome_type": "interview"}

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

    # -- campaigns write --
    async def update_campaign(self, campaign_id, body):
        FakeEngine.calls.append(("update_campaign", campaign_id, dict(body)))
        return FakeEngine.updated_campaign

    # -- tracker read (feeds the write's own id fan-out) --
    async def tracker_board(self, cid):
        FakeEngine.calls.append(("tracker_board", cid))
        return FakeEngine.tracker_boards.get(cid, {"applications": []})

    # -- tracker write --
    async def tracker_record_outcome(self, application_id, outcome_type, reason=None):
        FakeEngine.calls.append(
            ("tracker_record_outcome", application_id, outcome_type, reason)
        )
        return FakeEngine.recorded_outcome


@pytest.fixture(autouse=True)
def _reset():
    FakeEngine.calls = []
    yield


@pytest.fixture(autouse=True)
def _patch_engines(monkeypatch):
    monkeypatch.setattr(campaigns_mod, "ApplicantEngineClient", FakeEngine)
    monkeypatch.setattr(tracker_mod, "ApplicantEngineClient", FakeEngine)


# --- surface 1: campaigns PATCH (update_campaign) ---------------------------


def test_campaigns_update_lone_owner_single_user_mode_passes():
    """Single-user / unconfigured mode: the lone owner must still be able to
    rename/re-tune their own campaign -- this fix must not lock them out."""
    app = _mount(setup_applicant_campaigns_routes, user="solo", configured=False, admins=())
    c = TestClient(app)
    r = c.patch("/api/applicant/campaigns/c1", json={"name": "New name"})
    assert r.status_code == 200
    assert ("update_campaign", "c1", {"name": "New name"}) in FakeEngine.calls


def test_campaigns_update_owner_in_configured_mode_passes():
    """Configured (multi-account) mode: the real admin/owner still passes."""
    app = _mount(setup_applicant_campaigns_routes, user="owner", configured=True, admins=("owner",))
    c = TestClient(app)
    r = c.patch("/api/applicant/campaigns/c1", json={"name": "New name"})
    assert r.status_code == 200


def test_campaigns_update_second_account_denied():
    """A SECOND, non-admin workspace account must be denied -- and the
    engine mutation must never be reached (the id-ownership fan-out alone
    was not enough, since list_campaigns() returns the same rows to every
    account on a single-tenant engine)."""
    app = _mount(setup_applicant_campaigns_routes, user="teammate", configured=True, admins=("owner",))
    c = TestClient(app)
    r = c.patch("/api/applicant/campaigns/c1", json={"name": "Hijacked"})
    assert r.status_code == 403
    assert "update_campaign" not in [call[0] if isinstance(call, tuple) else call for call in FakeEngine.calls]
    assert "list_campaigns" not in FakeEngine.calls


def test_campaigns_update_unauthenticated_rejected():
    app = _mount(setup_applicant_campaigns_routes, user=None, configured=True, admins=("owner",))
    c = TestClient(app)
    r = c.patch("/api/applicant/campaigns/c1", json={"name": "x"})
    assert r.status_code == 401


# --- surface 2: tracker POST (record_outcome) -------------------------------


def test_tracker_outcome_lone_owner_single_user_mode_passes():
    """Single-user / unconfigured mode: the lone owner must still be able to
    record an outcome against their own application."""
    app = _mount(setup_applicant_tracker_routes, user="solo", configured=False, admins=())
    c = TestClient(app)
    r = c.post(
        "/api/applicant/tracker/applications/app-1/outcome",
        json={"outcome_type": "interview"},
    )
    assert r.status_code == 201
    assert any(call[0] == "tracker_record_outcome" for call in FakeEngine.calls if isinstance(call, tuple))


def test_tracker_outcome_owner_in_configured_mode_passes():
    """Configured (multi-account) mode: the real admin/owner still passes."""
    app = _mount(setup_applicant_tracker_routes, user="owner", configured=True, admins=("owner",))
    c = TestClient(app)
    r = c.post(
        "/api/applicant/tracker/applications/app-1/outcome",
        json={"outcome_type": "interview"},
    )
    assert r.status_code == 201


def test_tracker_outcome_second_account_denied():
    """A SECOND, non-admin workspace account must be denied -- and the
    engine mutation must never be reached. Before this fix, a caller-supplied
    application_id that merely appeared in the (shared, single-tenant)
    tracker-board fan-out was enough for ANY authenticated account to record
    an outcome against the real owner's application."""
    app = _mount(setup_applicant_tracker_routes, user="teammate", configured=True, admins=("owner",))
    c = TestClient(app)
    r = c.post(
        "/api/applicant/tracker/applications/app-1/outcome",
        json={"outcome_type": "interview"},
    )
    assert r.status_code == 403
    assert not any(
        call[0] == "tracker_record_outcome" for call in FakeEngine.calls if isinstance(call, tuple)
    )
    assert "list_campaigns" not in FakeEngine.calls


def test_tracker_outcome_unauthenticated_rejected():
    app = _mount(setup_applicant_tracker_routes, user=None, configured=True, admins=("owner",))
    c = TestClient(app)
    r = c.post(
        "/api/applicant/tracker/applications/app-1/outcome",
        json={"outcome_type": "interview"},
    )
    assert r.status_code == 401
