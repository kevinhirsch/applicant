"""Hermetic tests for the post-submission "attention" feed proxy (dark-engine
audit B2 items 8/9/60).

Mounts only ``routes/applicant_followups_routes.py`` on a bare FastAPI app with
a tiny stand-in auth middleware (the real global auth gate lives in ``app.py``
and is out of scope here). The engine is faked with a scripted ``FakeEngine``
patched in for ``ApplicantEngineClient`` -- zero network. Mirrors
``test_applicant_tracker_routes.py``'s harness exactly.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import routes.applicant_followups_routes as mod
from routes.applicant_followups_routes import setup_applicant_followups_routes
from src.applicant_engine import EngineError


def _make_app(authed: bool = True) -> FastAPI:
    app = FastAPI()

    @app.middleware("http")
    async def _auth(request, call_next):
        request.state.current_user = "tester" if authed else None
        return await call_next(request)

    app.include_router(setup_applicant_followups_routes())
    return app


class FakeEngine:
    """Stands in for ApplicantEngineClient as an async context manager."""

    calls: list = []
    campaigns: list = []
    attention: dict = {}  # campaign_id -> engine response dict
    raises: dict = {}     # key -> EngineError
    approve_result: dict = {}  # application_id -> engine response dict

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

    async def post_submission_attention(self, campaign_id):
        FakeEngine.calls.append(("post_submission_attention", campaign_id))
        key = ("post_submission_attention", campaign_id)
        if key in FakeEngine.raises:
            raise FakeEngine.raises[key]
        return FakeEngine.attention.get(
            campaign_id, {"campaign_id": campaign_id, "ghosted": [], "followups_due": []}
        )

    async def follow_up_approve(self, application_id, *, subject=None, body=None, delay_hours=None):
        FakeEngine.calls.append(("follow_up_approve", application_id, subject, body, delay_hours))
        key = ("follow_up_approve", application_id)
        if key in FakeEngine.raises:
            raise FakeEngine.raises[key]
        return FakeEngine.approve_result.get(
            application_id,
            {
                "application_id": application_id,
                "follow_up_id": "fup-1",
                "status": "SCHEDULED",
                "scheduled_at": "2026-06-22T00:00:00+00:00",
                "subject": subject or "Checking in",
                "body": body or "Hi, ...",
            },
        )


@pytest.fixture(autouse=True)
def _reset_fake():
    FakeEngine.calls = []
    FakeEngine.campaigns = []
    FakeEngine.attention = {}
    FakeEngine.raises = {}
    FakeEngine.approve_result = {}
    yield


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(mod, "ApplicantEngineClient", FakeEngine)
    return TestClient(_make_app())


# --- auth --------------------------------------------------------------------


def test_unauthenticated_get_is_rejected(monkeypatch):
    monkeypatch.setattr(mod, "ApplicantEngineClient", FakeEngine)
    c = TestClient(_make_app(authed=False))
    r = c.get("/api/applicant/followups/c1")
    assert r.status_code == 401


# --- owner-scope: campaign id must belong to the caller -----------------------


def test_campaign_not_owned_is_404(client):
    FakeEngine.campaigns = [{"id": "c1", "name": "Backend"}]

    r = client.get("/api/applicant/followups/someone-elses-campaign")

    assert r.status_code == 404
    # The attention read is never even attempted for an unowned campaign id.
    assert ("post_submission_attention", "someone-elses-campaign") not in FakeEngine.calls


def test_owned_campaign_round_trips_ghosted_and_followups_due(client):
    FakeEngine.campaigns = [{"id": "c1", "name": "Backend"}]
    FakeEngine.attention = {
        "c1": {
            "campaign_id": "c1",
            "ghosted": [
                {
                    "id": "pa-1",
                    "application_id": "a-1",
                    "title": "Likely gone silent: Acme",
                    "payload": {"sla_days": 21, "submission_age_days": 30},
                    "created_at": "2026-06-20T00:00:00+00:00",
                }
            ],
            "followups_due": [
                {
                    "id": "pa-2",
                    "application_id": "a-2",
                    "title": "Follow-up ready to review: Widgets Inc",
                    "payload": {"subject": "Checking in", "body": "Hi, ..."},
                    "created_at": "2026-06-21T00:00:00+00:00",
                }
            ],
        }
    }

    r = client.get("/api/applicant/followups/c1")

    assert r.status_code == 200
    body = r.json()
    assert body["engine_available"] is True
    assert body["campaign_id"] == "c1"
    assert len(body["ghosted"]) == 1
    assert body["ghosted"][0]["application_id"] == "a-1"
    assert len(body["followups_due"]) == 1
    assert body["followups_due"][0]["application_id"] == "a-2"
    assert ("post_submission_attention", "c1") in FakeEngine.calls


def test_no_campaigns_is_well_formed_empty(client):
    FakeEngine.campaigns = []

    r = client.get("/api/applicant/followups/c1")

    assert r.status_code == 404  # not owned (no campaigns at all)


# --- soft-degrade -------------------------------------------------------------


def test_engine_unreachable_on_campaign_list_degrades_soft(client):
    FakeEngine.raises["list_campaigns"] = EngineError("boom", status=None)

    r = client.get("/api/applicant/followups/c1")

    assert r.status_code == 200
    body = r.json()
    assert body["engine_available"] is False
    assert body["ghosted"] == []
    assert body["followups_due"] == []


def test_engine_gate_on_attention_read_degrades_soft(client):
    FakeEngine.campaigns = [{"id": "c1", "name": "Backend"}]
    FakeEngine.raises[("post_submission_attention", "c1")] = EngineError(
        "not set up", status=409, detail="Finish setup first."
    )

    r = client.get("/api/applicant/followups/c1")

    assert r.status_code == 200
    body = r.json()
    assert body.get("gated") is True
    assert body["ghosted"] == []
    assert body["followups_due"] == []


# --- approve a drafted follow-up (dark-engine audit B2 item 7) ----------------


def _own(campaign_id: str, application_id: str, *, subject="Checking in", body="Hi, ..."):
    """Wire up FakeEngine so ``application_id`` shows up in the owner's own
    ``followups_due`` fan-out for ``campaign_id`` (the scope guard the approve
    route checks before forwarding the write)."""
    FakeEngine.campaigns = [{"id": campaign_id, "name": "Backend"}]
    FakeEngine.attention = {
        campaign_id: {
            "campaign_id": campaign_id,
            "ghosted": [],
            "followups_due": [
                {
                    "id": "pa-1",
                    "application_id": application_id,
                    "title": "Follow-up ready to review",
                    "payload": {"subject": subject, "body": body},
                    "created_at": "2026-06-21T00:00:00+00:00",
                }
            ],
        }
    }


def test_unauthenticated_approve_is_rejected(monkeypatch):
    monkeypatch.setattr(mod, "ApplicantEngineClient", FakeEngine)
    c = TestClient(_make_app(authed=False))
    r = c.post("/api/applicant/followups/applications/a-1/approve")
    assert r.status_code == 401


def test_approve_forwards_to_the_engine_for_an_owned_application(client):
    _own("c1", "a-1")

    r = client.post("/api/applicant/followups/applications/a-1/approve")

    assert r.status_code == 201
    body = r.json()
    assert body["application_id"] == "a-1"
    assert body["status"] == "SCHEDULED"
    assert body["subject"] == "Checking in"
    call = next(c for c in FakeEngine.calls if c[0] == "follow_up_approve")
    assert call == ("follow_up_approve", "a-1", None, None, None)


def test_approve_forwards_owner_edited_subject_and_body(client):
    _own("c1", "a-1")

    r = client.post(
        "/api/applicant/followups/applications/a-1/approve",
        json={"subject": "Edited subject", "body": "Edited body", "delay_hours": 2.0},
    )

    assert r.status_code == 201
    body = r.json()
    assert body["subject"] == "Edited subject"
    assert body["body"] == "Edited body"
    call = next(c for c in FakeEngine.calls if c[0] == "follow_up_approve")
    assert call == ("follow_up_approve", "a-1", "Edited subject", "Edited body", 2.0)


def test_approve_an_application_never_surfaced_as_a_draft_is_404(client):
    # An owned campaign exists, but this application never showed up in its
    # followups_due fan-out.
    FakeEngine.campaigns = [{"id": "c1", "name": "Backend"}]
    FakeEngine.attention = {"c1": {"campaign_id": "c1", "ghosted": [], "followups_due": []}}

    r = client.post("/api/applicant/followups/applications/a-not-a-draft/approve")

    assert r.status_code == 404
    assert not any(c[0] == "follow_up_approve" for c in FakeEngine.calls)


def test_approve_when_engine_unreachable_is_503(client):
    FakeEngine.raises["list_campaigns"] = EngineError("boom", status=None)

    r = client.post("/api/applicant/followups/applications/a-1/approve")

    assert r.status_code == 503
    assert not any(c[0] == "follow_up_approve" for c in FakeEngine.calls)


def test_approve_forwards_a_404_from_the_engine_when_already_approved(client):
    """Even after this route's own scope check passes, the engine may still
    404 (e.g. a race: a second tap after the first already resolved the
    draft) -- that must be forwarded faithfully, not swallowed."""
    _own("c1", "a-1")
    FakeEngine.raises[("follow_up_approve", "a-1")] = EngineError(
        "No open follow-up draft for this application.", status=404
    )

    r = client.post("/api/applicant/followups/applications/a-1/approve")

    assert r.status_code == 404


# --- cross-account isolation (DISC-15/DISC-15b): engine-owner gate ------------
#
# The engine is single-tenant, so the id-ownership fan-outs above only guard
# against foreign ids -- ``list_campaigns()`` returns the SAME rows to every
# authenticated workspace account. Both endpoints must therefore gate with
# ``require_engine_owner`` (a second, non-admin account is denied on the read
# AND the write), mirroring ``test_applicant_crossuser_write_isolation_disc15b``'s
# two-account convention exactly.


class _AuthMgr:
    """Minimal stand-in for the real ``AuthManager`` (mirrors DISC-15b's
    ``_AuthMgr`` exactly)."""

    def __init__(self, *, configured: bool, admins: "set[str] | None" = None):
        self.is_configured = configured
        self._admins = set(admins or ())

    def is_admin(self, user: str) -> bool:
        return user in self._admins


def _mount_with_accounts(*, user, configured: bool, admins=("owner",)) -> TestClient:
    app = FastAPI()
    app.state.auth_manager = _AuthMgr(configured=configured, admins=admins)

    @app.middleware("http")
    async def _auth(request, call_next):
        request.state.current_user = user
        return await call_next(request)

    app.include_router(setup_applicant_followups_routes())
    return TestClient(app)


def test_attention_read_second_account_denied(monkeypatch):
    """A SECOND, non-admin workspace account must be denied the read -- the
    engine fan-out is never even attempted (it has no owner concept to
    protect the real owner's drafted follow-ups with)."""
    monkeypatch.setattr(mod, "ApplicantEngineClient", FakeEngine)
    _own("c1", "a-1")
    c = _mount_with_accounts(user="teammate", configured=True, admins=("owner",))

    r = c.get("/api/applicant/followups/c1")

    assert r.status_code == 403
    assert "list_campaigns" not in FakeEngine.calls


def test_attention_read_owner_in_configured_mode_passes(monkeypatch):
    monkeypatch.setattr(mod, "ApplicantEngineClient", FakeEngine)
    _own("c1", "a-1")
    c = _mount_with_accounts(user="owner", configured=True, admins=("owner",))

    r = c.get("/api/applicant/followups/c1")

    assert r.status_code == 200
    assert len(r.json()["followups_due"]) == 1


def test_approve_second_account_denied(monkeypatch):
    """A SECOND, non-admin workspace account must be denied the WRITE -- and
    the engine mutation must never be reached. Before this fix, plain
    ``require_user`` let any authenticated account approve/schedule the real
    owner's drafted follow-up (outbound email in the owner's name)."""
    monkeypatch.setattr(mod, "ApplicantEngineClient", FakeEngine)
    _own("c1", "a-1")
    c = _mount_with_accounts(user="teammate", configured=True, admins=("owner",))

    r = c.post("/api/applicant/followups/applications/a-1/approve")

    assert r.status_code == 403
    assert not any(
        call[0] == "follow_up_approve" for call in FakeEngine.calls if isinstance(call, tuple)
    )
    assert "list_campaigns" not in FakeEngine.calls


def test_approve_lone_owner_single_user_mode_passes(monkeypatch):
    """Single-user / unconfigured mode: the lone owner must still be able to
    approve their own drafted follow-up -- this gate must not lock them out."""
    monkeypatch.setattr(mod, "ApplicantEngineClient", FakeEngine)
    _own("c1", "a-1")
    c = _mount_with_accounts(user="solo", configured=False, admins=())

    r = c.post("/api/applicant/followups/applications/a-1/approve")

    assert r.status_code == 201
    assert any(
        call[0] == "follow_up_approve" for call in FakeEngine.calls if isinstance(call, tuple)
    )
