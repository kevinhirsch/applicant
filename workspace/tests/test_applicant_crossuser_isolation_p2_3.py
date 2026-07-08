"""P2-3 security pass — cross-account isolation on the RESULTS / RESEARCH /
GALLERY read surfaces (the residual DISC-15 hole class).

DISC-15/15b closed cross-account isolation on pending/campaigns/tracker/activity
by moving them from the plain ``require_user`` gate (any authenticated account)
to ``src.auth_helpers.require_engine_owner`` (only the lone deployment owner,
or an admin once multiple accounts exist). The security-pass sweep found three
more engine-backed READ proxies that surface the ONE deployment owner's data but
were still on ``require_user``:

* **Results** — the owner's learning/outcomes funnel + per-source conversion;
* **Research** — the owner's cached company-research reports + budget;
* **Gallery** — the owner's generated documents/collections.

On a single-tenant engine ``list_campaigns()`` returns the SAME rows to every
workspace account, so ``require_user`` let a second, unrelated account read all
three. Fixed by switching each to ``require_engine_owner``.

Mirrors DISC-15b's two-account harness exactly: a bare app with a stub
``auth_manager`` + a middleware that authenticates as whichever user the test
names, and a scripted fake engine. Hand-verified RED-on-revert: putting any of
the three gates back to ``require_user`` turns the corresponding
``*_second_account_denied`` test red (200 instead of 403, and the engine read
IS reached). Zero network.
"""

from __future__ import annotations

import pytest
import routes.applicant_gallery_routes as gallery_mod
import routes.applicant_research_routes as research_mod
import routes.applicant_results_routes as results_mod
from fastapi import FastAPI
from fastapi.testclient import TestClient
from routes.applicant_gallery_routes import setup_applicant_gallery_routes
from routes.applicant_research_routes import setup_applicant_research_routes
from routes.applicant_results_routes import setup_applicant_results_routes


class _AuthMgr:
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


class FakeEngine:
    """Scripted ApplicantEngineClient double covering all three read surfaces."""

    calls: list = []
    campaigns: list = [{"id": "c1", "name": "Backend roles"}]

    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return None

    async def list_campaigns(self):
        FakeEngine.calls.append("list_campaigns")
        return FakeEngine.campaigns

    async def admin_learning(self, campaign_id):
        FakeEngine.calls.append(("admin_learning", campaign_id))
        return {"summary": {"matched": 3}, "sources": [], "converting_roles": []}

    async def gallery(self, campaign_id):
        FakeEngine.calls.append(("gallery", campaign_id))
        return {"collections": []}

    async def research_cached(self, campaign_id, query):
        FakeEngine.calls.append(("research_cached", campaign_id, query))
        return {"report": "secret company research"}

    async def research_run(self, campaign_id, payload):
        FakeEngine.calls.append(("research_run", campaign_id, dict(payload)))
        return {"report": "fresh company research"}

    async def research_budget(self, campaign_id):
        FakeEngine.calls.append(("research_budget", campaign_id))
        return {"remaining": 5}


@pytest.fixture(autouse=True)
def _reset():
    FakeEngine.calls = []
    yield


@pytest.fixture(autouse=True)
def _patch_engines(monkeypatch):
    for mod in (results_mod, research_mod, gallery_mod):
        monkeypatch.setattr(mod, "ApplicantEngineClient", FakeEngine)


# --- results ("") -----------------------------------------------------------


def test_results_lone_owner_single_user_mode_passes():
    app = _mount(setup_applicant_results_routes, user="solo", configured=False, admins=())
    r = TestClient(app).get("/api/applicant/results")
    assert r.status_code == 200
    assert ("admin_learning", "c1") in FakeEngine.calls


def test_results_owner_in_configured_mode_passes():
    app = _mount(setup_applicant_results_routes, user="owner", configured=True, admins=("owner",))
    r = TestClient(app).get("/api/applicant/results")
    assert r.status_code == 200


def test_results_second_account_denied_and_engine_untouched():
    app = _mount(setup_applicant_results_routes, user="teammate", configured=True, admins=("owner",))
    r = TestClient(app).get("/api/applicant/results")
    assert r.status_code == 403
    assert FakeEngine.calls == [], "the ungated engine read must never be reached"


def test_results_unauthenticated_rejected():
    app = _mount(setup_applicant_results_routes, user=None, configured=True, admins=("owner",))
    assert TestClient(app).get("/api/applicant/results").status_code == 401


# --- research ("/{cid}/cached") ---------------------------------------------


def test_research_lone_owner_single_user_mode_passes():
    app = _mount(setup_applicant_research_routes, user="solo", configured=False, admins=())
    r = TestClient(app).get("/api/applicant/research/c1/cached", params={"query": "Acme"})
    assert r.status_code == 200
    assert ("research_cached", "c1", "Acme") in FakeEngine.calls


def test_research_second_account_denied_and_engine_untouched():
    app = _mount(setup_applicant_research_routes, user="teammate", configured=True, admins=("owner",))
    r = TestClient(app).get("/api/applicant/research/c1/cached", params={"query": "Acme"})
    assert r.status_code == 403
    assert FakeEngine.calls == [], "another account must not read the owner's research"


def test_research_run_second_account_denied_and_engine_untouched():
    """The budget-CHARGING run is the costliest research endpoint — a second
    account must not be able to spend the owner's research budget."""
    app = _mount(setup_applicant_research_routes, user="teammate", configured=True, admins=("owner",))
    r = TestClient(app).post("/api/applicant/research/c1/run", json={"query": "Acme"})
    assert r.status_code == 403
    assert FakeEngine.calls == []


def test_research_budget_second_account_denied():
    app = _mount(setup_applicant_research_routes, user="teammate", configured=True, admins=("owner",))
    r = TestClient(app).get("/api/applicant/research/c1/budget")
    assert r.status_code == 403
    assert FakeEngine.calls == []


def test_research_unauthenticated_rejected():
    app = _mount(setup_applicant_research_routes, user=None, configured=True, admins=("owner",))
    r = TestClient(app).get("/api/applicant/research/c1/cached", params={"query": "Acme"})
    assert r.status_code == 401


# --- gallery ("") -----------------------------------------------------------


def test_gallery_lone_owner_single_user_mode_passes():
    app = _mount(setup_applicant_gallery_routes, user="solo", configured=False, admins=())
    r = TestClient(app).get("/api/applicant/gallery")
    assert r.status_code == 200
    assert ("gallery", "c1") in FakeEngine.calls


def test_gallery_second_account_denied_and_engine_untouched():
    app = _mount(setup_applicant_gallery_routes, user="teammate", configured=True, admins=("owner",))
    r = TestClient(app).get("/api/applicant/gallery")
    assert r.status_code == 403
    assert FakeEngine.calls == [], "another account must not read the owner's gallery"


def test_gallery_campaigns_list_second_account_denied():
    app = _mount(setup_applicant_gallery_routes, user="teammate", configured=True, admins=("owner",))
    r = TestClient(app).get("/api/applicant/gallery/campaigns")
    assert r.status_code == 403
    assert FakeEngine.calls == []


def test_gallery_for_campaign_second_account_denied():
    app = _mount(setup_applicant_gallery_routes, user="teammate", configured=True, admins=("owner",))
    r = TestClient(app).get("/api/applicant/gallery/c1")
    assert r.status_code == 403
    assert FakeEngine.calls == []


def test_gallery_unauthenticated_rejected():
    app = _mount(setup_applicant_gallery_routes, user=None, configured=True, admins=("owner",))
    assert TestClient(app).get("/api/applicant/gallery").status_code == 401
