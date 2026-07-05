"""Regression coverage for dark-engine audit lens 10 #28 (workspace side).

The Pending-Actions Portal's notification-center proxy (``GET
/api/applicant/portal/notifications`` / ``POST
/api/applicant/portal/notifications/{id}/seen``) used to require only *a*
logged-in workspace user (``_require_user``). The engine's in-app inbox has no
owner concept at all -- it is single-tenant per deployment, every entry
(title/body includes role/company) belongs to the ONE person the deployment
was set up for -- so in a multi-user front-door, any OTHER configured
workspace account could read and dismiss the real owner's job-search
notifications.

Fixed by gating both endpoints with ``_require_notification_owner``, which
mirrors ``applicant_admin_routes.py``'s already-established
``_require_admin``: in single-user / unconfigured mode there is no admin
distinction (the lone account passes, matching the rest of the workspace);
once the workspace is configured for multiple accounts, only an admin may
reach the notification center.

Mounts only ``routes/applicant_portal_routes.py`` on a bare FastAPI app with a
tiny middleware that authenticates the request and an ``auth_manager`` stub on
app state (the real global auth gate lives in ``app.py``, out of scope here),
following the exact convention of ``test_applicant_admin_routes.py``. The
engine is faked with a scripted double; zero network.

Hand-verified RED-on-revert / GREEN-on-restore: temporarily restoring the
pre-fix gate (``_require_user`` instead of ``_require_notification_owner`` on
the two endpoints below) makes ``test_non_owner_cannot_read_inbox`` and
``test_non_owner_cannot_dismiss_inbox_entry`` fail (a non-admin second account
gets 200/204 instead of 403); restoring the fix turns them green again.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import routes.applicant_portal_routes as mod
from routes.applicant_portal_routes import setup_applicant_portal_routes


class _AuthMgr:
    def __init__(self, *, configured: bool, admins: set[str] | None = None):
        self.is_configured = configured
        self._admins = set(admins or ())

    def is_admin(self, user: str) -> bool:
        return user in self._admins


def _make_app(*, user="owner", configured=True, admins=("owner",)) -> FastAPI:
    app = FastAPI()
    app.state.auth_manager = _AuthMgr(configured=configured, admins=admins)

    @app.middleware("http")
    async def _auth(request, call_next):
        request.state.current_user = user
        return await call_next(request)

    app.include_router(setup_applicant_portal_routes())
    return app


class FakeEngine:
    """Stands in for ApplicantEngineClient as an async context manager."""

    calls: list = []
    notifications: dict = {"count": 0, "items": []}

    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return None

    async def list_notifications(self):
        FakeEngine.calls.append("list_notifications")
        return FakeEngine.notifications

    async def dismiss_notification(self, nid):
        FakeEngine.calls.append(("dismiss_notification", nid))
        return None


@pytest.fixture(autouse=True)
def _reset():
    FakeEngine.calls = []
    FakeEngine.notifications = {
        "count": 1,
        "items": [
            {
                "id": "n1",
                "title": "Digest ready",
                "body": "2 roles at Acme await review",
                "kind": "digest",
            }
        ],
    }
    yield


@pytest.fixture
def owner_client(monkeypatch):
    monkeypatch.setattr(mod, "ApplicantEngineClient", FakeEngine)
    return TestClient(_make_app(user="owner", configured=True, admins=("owner",)))


# --- the vulnerability: a non-owner workspace account must be denied --------


def test_non_owner_cannot_read_inbox(monkeypatch):
    monkeypatch.setattr(mod, "ApplicantEngineClient", FakeEngine)
    c = TestClient(_make_app(user="teammate", configured=True, admins=("owner",)))
    r = c.get("/api/applicant/portal/notifications")
    assert r.status_code == 403
    assert "list_notifications" not in FakeEngine.calls


def test_non_owner_cannot_dismiss_inbox_entry(monkeypatch):
    monkeypatch.setattr(mod, "ApplicantEngineClient", FakeEngine)
    c = TestClient(_make_app(user="teammate", configured=True, admins=("owner",)))
    r = c.post("/api/applicant/portal/notifications/n1/seen")
    assert r.status_code == 403
    assert ("dismiss_notification", "n1") not in FakeEngine.calls


# --- the legitimate owner is completely unaffected --------------------------


def test_owner_can_read_inbox(owner_client):
    r = owner_client.get("/api/applicant/portal/notifications")
    assert r.status_code == 200
    body = r.json()
    assert body["engine_available"] is True
    assert body["count"] == 1
    assert body["items"][0]["title"] == "Digest ready"


def test_owner_can_dismiss_inbox_entry(owner_client):
    r = owner_client.post("/api/applicant/portal/notifications/n1/seen")
    assert r.status_code == 200
    assert ("dismiss_notification", "n1") in FakeEngine.calls


# --- single-user / unconfigured mode: the lone account still works ---------


def test_single_user_mode_allows_lone_owner(monkeypatch):
    monkeypatch.setattr(mod, "ApplicantEngineClient", FakeEngine)
    c = TestClient(_make_app(user="solo", configured=False, admins=()))
    r = c.get("/api/applicant/portal/notifications")
    assert r.status_code == 200


# --- unauthenticated is still rejected (gate must not fail open) -----------


def test_unauthenticated_is_rejected(monkeypatch):
    monkeypatch.setattr(mod, "ApplicantEngineClient", FakeEngine)
    c = TestClient(_make_app(user=None, configured=True, admins=("owner",)))
    r = c.get("/api/applicant/portal/notifications")
    assert r.status_code == 401


def test_unauthenticated_cannot_dismiss(monkeypatch):
    monkeypatch.setattr(mod, "ApplicantEngineClient", FakeEngine)
    c = TestClient(_make_app(user=None, configured=True, admins=("owner",)))
    r = c.post("/api/applicant/portal/notifications/n1/seen")
    assert r.status_code == 401
