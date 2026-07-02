"""Hermetic tests for the Tracker proxy (design-audit Top-25 #4).

Mounts only ``routes/applicant_tracker_routes.py`` on a bare FastAPI app with a
tiny middleware that authenticates the request (the real global auth gate lives
in ``app.py`` and is out of scope here). The engine is faked two ways:

* a scripted ``FakeEngine`` patched in for ``ApplicantEngineClient`` (covers the
  campaign fan-out, the aggregated board shape, the owner-scoped write guard, and
  the soft-degrade / gate paths), and
* a real :class:`ApplicantEngineClient` over an ``httpx.MockTransport`` proving the
  exact engine paths are hit.

Zero network either way. Mirrors ``test_applicant_results_routes.py`` /
``test_applicant_campaigns_routes.py``.
"""

from __future__ import annotations

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import routes.applicant_tracker_routes as mod
from routes.applicant_tracker_routes import setup_applicant_tracker_routes
from src.applicant_engine import ApplicantEngineClient, EngineError


# --- test app with a stand-in auth middleware -------------------------------


def _make_app(authed: bool = True) -> FastAPI:
    app = FastAPI()

    @app.middleware("http")
    async def _auth(request, call_next):
        request.state.current_user = "tester" if authed else None
        return await call_next(request)

    app.include_router(setup_applicant_tracker_routes())
    return app


# --- a scripted fake engine -------------------------------------------------


class FakeEngine:
    """Stands in for ApplicantEngineClient as an async context manager."""

    calls: list = []
    campaigns: list = []
    boards: dict = {}          # campaign_id -> {"applications": [...]}
    record_results: dict = {}  # application_id -> engine response dict
    raises: dict = {}          # key -> EngineError

    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return None

    async def list_campaigns(self):
        FakeEngine.calls.append("list_campaigns")
        if "list_campaigns" in FakeEngine.raises:
            raise FakeEngine.raises["list_campaigns"]
        return FakeEngine.campaigns

    async def tracker_board(self, campaign_id):
        FakeEngine.calls.append(("tracker_board", campaign_id))
        if ("tracker_board", campaign_id) in FakeEngine.raises:
            raise FakeEngine.raises[("tracker_board", campaign_id)]
        return FakeEngine.boards.get(campaign_id, {"applications": []})

    async def tracker_record_outcome(self, application_id, outcome_type):
        FakeEngine.calls.append(("tracker_record_outcome", application_id, outcome_type))
        key = ("tracker_record_outcome", application_id, outcome_type)
        if key in FakeEngine.raises:
            raise FakeEngine.raises[key]
        return FakeEngine.record_results.get(
            application_id,
            {
                "application_id": application_id,
                "outcome_id": "oe-1",
                "type": outcome_type,
                "source": "manual",
            },
        )


@pytest.fixture(autouse=True)
def _reset_fake():
    FakeEngine.calls = []
    FakeEngine.campaigns = []
    FakeEngine.boards = {}
    FakeEngine.record_results = {}
    FakeEngine.raises = {}
    yield


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(mod, "ApplicantEngineClient", FakeEngine)
    return TestClient(_make_app())


def _row(aid: str, status: str = "AWAITING_RESPONSE", signals=None) -> dict:
    return {
        "application_id": aid,
        "status": status,
        "role_name": "Engineer",
        "job_title": "Backend Engineer",
        "signals": signals or [],
        "submitted_at": "2026-06-20T00:00:00+00:00",
        "created_at": "2026-06-15T00:00:00+00:00",
    }


# --- auth -------------------------------------------------------------------


def test_unauthenticated_get_is_rejected(monkeypatch):
    monkeypatch.setattr(mod, "ApplicantEngineClient", FakeEngine)
    c = TestClient(_make_app(authed=False))
    r = c.get("/api/applicant/tracker")
    assert r.status_code == 401


def test_unauthenticated_post_is_rejected(monkeypatch):
    monkeypatch.setattr(mod, "ApplicantEngineClient", FakeEngine)
    c = TestClient(_make_app(authed=False))
    r = c.post(
        "/api/applicant/tracker/applications/a-1/outcome",
        json={"outcome_type": "rejected"},
    )
    assert r.status_code == 401


# --- GET: aggregation across campaigns --------------------------------------


def test_aggregates_rows_across_all_owned_campaigns(client):
    FakeEngine.campaigns = [
        {"id": "c1", "name": "Backend"},
        {"id": "c2", "name": "Frontend"},
    ]
    FakeEngine.boards = {
        "c1": {"applications": [_row("a-1")]},
        "c2": {"applications": [_row("a-2")]},
    }

    r = client.get("/api/applicant/tracker")

    assert r.status_code == 200
    body = r.json()
    assert body["engine_available"] is True
    assert body["has_data"] is True
    ids = {row["application_id"] for row in body["applications"]}
    assert ids == {"a-1", "a-2"}
    # Each row is tagged with the campaign it came from.
    by_id = {row["application_id"]: row for row in body["applications"]}
    assert by_id["a-1"]["campaign_id"] == "c1"
    assert by_id["a-1"]["campaign_name"] == "Backend"
    assert by_id["a-2"]["campaign_id"] == "c2"
    assert by_id["a-2"]["campaign_name"] == "Frontend"


def test_no_campaigns_yet_is_well_formed_empty(client):
    FakeEngine.campaigns = []

    r = client.get("/api/applicant/tracker")

    assert r.status_code == 200
    assert r.json() == {"engine_available": True, "has_data": False, "applications": []}


def test_one_campaigns_board_failing_does_not_blank_the_rest(client):
    FakeEngine.campaigns = [{"id": "c1", "name": "Backend"}, {"id": "c2", "name": "Frontend"}]
    FakeEngine.boards = {"c2": {"applications": [_row("a-2")]}}
    FakeEngine.raises = {("tracker_board", "c1"): EngineError("boom", status=500)}

    r = client.get("/api/applicant/tracker")

    assert r.status_code == 200
    body = r.json()
    assert [row["application_id"] for row in body["applications"]] == ["a-2"]


def test_soft_degrades_when_engine_down_on_campaigns(client):
    FakeEngine.raises = {"list_campaigns": EngineError("down", status=None)}

    r = client.get("/api/applicant/tracker")

    assert r.status_code == 200
    body = r.json()
    assert body["engine_available"] is False
    assert body["applications"] == []


def test_campaigns_409_gate_is_not_offline(client):
    FakeEngine.raises = {
        "list_campaigns": EngineError("blocked", status=409, detail="Finish setup first.")
    }

    r = client.get("/api/applicant/tracker")

    assert r.status_code == 200
    body = r.json()
    assert body["gated"] is True
    assert body["engine_available"] is True
    assert body["message"] == "Finish setup first."
    assert body["applications"] == []


# --- POST: owner-scoped manual outcome --------------------------------------


def test_record_outcome_succeeds_for_owned_application(client):
    FakeEngine.campaigns = [{"id": "c1", "name": "Backend"}]
    FakeEngine.boards = {"c1": {"applications": [_row("a-1")]}}

    r = client.post(
        "/api/applicant/tracker/applications/a-1/outcome",
        json={"outcome_type": "interview_invited"},
    )

    assert r.status_code == 201
    body = r.json()
    assert body["application_id"] == "a-1"
    assert body["type"] == "interview_invited"
    assert body["source"] == "manual"
    assert ("tracker_record_outcome", "a-1", "interview_invited") in FakeEngine.calls


def test_record_outcome_rejects_application_not_in_owners_own_board(client):
    # "a-1" belongs to campaign c1, which THIS request's own list_campaigns()
    # fan-out returns. A caller-supplied id for an application that never showed
    # up in that fan-out (someone else's application, or a typo) must 404 —
    # and, critically, the engine write must never even be attempted.
    FakeEngine.campaigns = [{"id": "c1", "name": "Backend"}]
    FakeEngine.boards = {"c1": {"applications": [_row("a-1")]}}

    r = client.post(
        "/api/applicant/tracker/applications/not-mine/outcome",
        json={"outcome_type": "rejected"},
    )

    assert r.status_code == 404
    assert not any(c[0] == "tracker_record_outcome" for c in FakeEngine.calls if isinstance(c, tuple))


def test_record_outcome_engine_unavailable_is_503(client):
    FakeEngine.raises = {"list_campaigns": EngineError("down", status=None)}

    r = client.post(
        "/api/applicant/tracker/applications/a-1/outcome",
        json={"outcome_type": "rejected"},
    )

    assert r.status_code == 503


def test_record_outcome_forwards_engine_422_for_bad_outcome_type(client):
    FakeEngine.campaigns = [{"id": "c1", "name": "Backend"}]
    FakeEngine.boards = {"c1": {"applications": [_row("a-1")]}}
    FakeEngine.raises = {
        ("tracker_record_outcome", "a-1", "bogus"): EngineError(
            "bad type", status=422, detail="Unrecognized outcome type"
        )
    }

    r = client.post(
        "/api/applicant/tracker/applications/a-1/outcome",
        json={"outcome_type": "bogus"},
    )

    assert r.status_code == 422


# --- owner isolation: one owner's request never surfaces or mutates another's --
#
# The engine is single-tenant per deployment (no ``owner_id`` anywhere in its
# storage — see ``src/applicant/adapters/storage/models.py``), so this proxy's
# ONLY scoping mechanism is: never trust a caller-supplied application id, and
# derive "what the owner may read/write" purely from THIS request's own
# ``list_campaigns()`` -> ``tracker_board()`` fan-out (mirrors
# ``applicant_results_routes.test_owner_isolation_two_owners_never_cross_contaminate``).
# This test proves two requests standing in for two different owners never
# cross-contaminate: owner A's applications must never leak into owner B's board,
# and owner B can never record an outcome against owner A's application id.


def test_owner_isolation_two_owners_never_cross_contaminate(client):
    # -- "owner A" ---------------------------------------------------------
    FakeEngine.campaigns = [{"id": "owner-a-campaign", "name": "Alice's Search"}]
    FakeEngine.boards = {"owner-a-campaign": {"applications": [_row("owner-a-app")]}}
    r_a = client.get("/api/applicant/tracker")
    assert r_a.status_code == 200
    body_a = r_a.json()
    assert [row["application_id"] for row in body_a["applications"]] == ["owner-a-app"]

    # -- "owner B" (a completely disjoint campaign/application universe) ---
    FakeEngine.campaigns = [{"id": "owner-b-campaign", "name": "Bob's Search"}]
    FakeEngine.boards = {"owner-b-campaign": {"applications": [_row("owner-b-app")]}}
    r_b = client.get("/api/applicant/tracker")
    assert r_b.status_code == 200
    body_b = r_b.json()

    # Owner B's board must be entirely B's own data — none of A's.
    ids_b = [row["application_id"] for row in body_b["applications"]]
    assert ids_b == ["owner-b-app"]
    assert "owner-a-app" not in str(body_b)
    assert "Alice's Search" not in str(body_b)

    # Owner B cannot record an outcome against owner A's application id — it
    # never appeared in B's own campaign fan-out, so it 404s and the engine
    # write is never attempted for it.
    r_leak = client.post(
        "/api/applicant/tracker/applications/owner-a-app/outcome",
        json={"outcome_type": "rejected"},
    )
    assert r_leak.status_code == 404
    assert (
        "tracker_record_outcome",
        "owner-a-app",
        "rejected",
    ) not in FakeEngine.calls

    # Owner B CAN record an outcome against their own application.
    r_own = client.post(
        "/api/applicant/tracker/applications/owner-b-app/outcome",
        json={"outcome_type": "offer"},
    )
    assert r_own.status_code == 201
    assert ("tracker_record_outcome", "owner-b-app", "offer") in FakeEngine.calls


# --- exact engine paths via a real client over MockTransport ----------------


def _mock_transport_app(handler):
    class TransportEngine(ApplicantEngineClient):
        def __init__(self, *a, **k):
            super().__init__(base_url="http://api:8000", transport=httpx.MockTransport(handler))

    app = FastAPI()

    @app.middleware("http")
    async def _auth(request, call_next):
        request.state.current_user = "tester"
        return await call_next(request)

    app.include_router(setup_applicant_tracker_routes())
    return app, TransportEngine


def test_tracker_hits_exact_engine_paths(monkeypatch):
    paths = []

    def handler(request: httpx.Request) -> httpx.Response:
        paths.append((request.method, request.url.path))
        if request.url.path == "/api/campaigns":
            return httpx.Response(200, json=[{"id": "c9", "name": "Search"}])
        if request.url.path == "/api/post-submission/c9":
            return httpx.Response(200, json={"campaign_id": "c9", "applications": [_row("a-9")]})
        if request.url.path == "/api/post-submission/applications/a-9/outcome":
            return httpx.Response(
                201,
                json={"application_id": "a-9", "outcome_id": "oe-9", "type": "offer", "source": "manual"},
            )
        return httpx.Response(404, json={"detail": "unexpected"})

    app, engine_cls = _mock_transport_app(handler)
    monkeypatch.setattr(mod, "ApplicantEngineClient", engine_cls)
    c = TestClient(app)

    r = c.get("/api/applicant/tracker")
    assert r.status_code == 200
    assert ("GET", "/api/campaigns") in paths
    assert ("GET", "/api/post-submission/c9") in paths
    body = r.json()
    assert body["applications"][0]["application_id"] == "a-9"

    r2 = c.post(
        "/api/applicant/tracker/applications/a-9/outcome",
        json={"outcome_type": "offer"},
    )
    assert r2.status_code == 201
    assert ("POST", "/api/post-submission/applications/a-9/outcome") in paths
    assert r2.json()["type"] == "offer"
