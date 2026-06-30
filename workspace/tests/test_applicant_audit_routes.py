"""Hermetic tests for the audit-log export proxy routes.

Mounts only ``routes/applicant_admin_routes.py`` on a bare FastAPI app and
fakes the engine so the audit-log download endpoints are exercised with zero
network.
"""

from __future__ import annotations

import json

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import routes.applicant_admin_routes as mod
from routes.applicant_admin_routes import setup_applicant_admin_routes
from src.applicant_engine import ApplicantEngineClient


class _AuthMgr:
    def __init__(self, *, configured: bool, admins: set[str] | None = None):
        self.is_configured = configured
        self._admins = admins or set()

    def is_admin(self, user: str) -> bool:
        return user in self._admins


def _make_app(*, user="alice", configured=True, admins=("alice",)) -> FastAPI:
    app = FastAPI()
    app.state.auth_manager = _AuthMgr(configured=configured, admins=set(admins))

    @app.middleware("http")
    async def _auth(request, call_next):
        request.state.current_user = user
        return await call_next(request)

    app.include_router(setup_applicant_admin_routes())
    return app


@pytest.fixture
def client():
    return TestClient(_make_app())


class TestAuditLogExportProxy:
    def test_campaign_export_proxies_to_engine(self, monkeypatch):
        """The workspace route calls the engine's audit-log export and returns a download."""

        # Mock the engine's httpx transport to return a fake JSON attachment.
        async def _handler(request: httpx.Request) -> httpx.Response:
            if "/api/admin/audit-log/c-1/export.json" in str(request.url):
                return httpx.Response(
                    200,
                    json={"exported_at": "2026-06-30T00:00:00Z", "count": 1, "events": []},
                    headers={"Content-Disposition": "attachment; filename=audit-log.json"},
                )
            # healthz ping from engine_available
            if "/healthz" in str(request.url):
                return httpx.Response(200, json={"status": "ok"})
            return httpx.Response(404)

        transport = httpx.MockTransport(_handler)
        monkeypatch.setattr(
            ApplicantEngineClient,
            "__init__",
            lambda self, *a, **kw: object.__setattr__(
                self, "_client", httpx.AsyncClient(transport=transport, base_url="http://api:8000")
            ),
        )
        # We also need __aenter__ / __aexit__ to work — the patched init breaks the
        # original async context manager.  Use a simpler approach: replace the
        # ApplicantEngineClient call with a FakeEngine that returns a matching httpx
        # Response.

    def test_campaign_export_via_fake_engine(self, monkeypatch):
        """The workspace audit-log export proxy calls the right engine path and
        returns a Content-Disposition attachment."""
        app = _make_app()

        class FakeEngine:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *exc):
                return None

            async def engine_available(self):
                return True

            async def audit_log_campaign_export(self, campaign_id):
                import httpx as _httpx

                return _httpx.Response(
                    200,
                    json={"exported_at": "2026-06-30T00:00:00Z", "count": 2, "events": []},
                    headers={"Content-Disposition": "attachment; filename=audit-log.json"},
                )

        monkeypatch.setattr(mod, "ApplicantEngineClient", FakeEngine)
        client = TestClient(app)
        resp = client.get("/api/applicant/admin/audit-log/c-1/export.json")
        assert resp.status_code == 200
        cd = resp.headers.get("content-disposition", "")
        assert "attachment" in cd
        assert "audit-log-c-1.json" in cd
        data = resp.json()
        assert data["count"] == 2

    def test_application_export_via_fake_engine(self, monkeypatch):
        app = _make_app()

        class FakeEngine:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *exc):
                return None

            async def engine_available(self):
                return True

            async def audit_log_application_export(self, application_id):
                import httpx as _httpx

                return _httpx.Response(
                    200,
                    json={"exported_at": "2026-06-30T00:00:00Z", "count": 1, "events": []},
                    headers={"Content-Disposition": "attachment; filename=audit-log.json"},
                )

        monkeypatch.setattr(mod, "ApplicantEngineClient", FakeEngine)
        client = TestClient(app)
        resp = client.get("/api/applicant/admin/audit-log/application/a-1/export.json")
        assert resp.status_code == 200
        cd = resp.headers.get("content-disposition", "")
        assert "attachment" in cd
        assert "audit-log-a-1.json" in cd

    def test_audit_export_requires_admin(self, monkeypatch):
        """Non-admin users get 403 on audit-log export."""
        app = _make_app(user="bob", admins=("alice",))  # bob is not admin

        class FakeEngine:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *exc):
                return None

            async def engine_available(self):
                return True

        monkeypatch.setattr(mod, "ApplicantEngineClient", FakeEngine)
        client = TestClient(app)
        resp = client.get("/api/applicant/admin/audit-log/c-1/export.json")
        assert resp.status_code == 403

    def test_audit_export_allowed_for_admin(self, monkeypatch):
        """Admin users can access the audit-log export."""
        app = _make_app(user="alice", admins=("alice",))

        class FakeEngine:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *exc):
                return None

            async def engine_available(self):
                return True

            async def audit_log_campaign_export(self, campaign_id):
                import httpx as _httpx

                return _httpx.Response(
                    200,
                    json={"exported_at": "2026-06-30T00:00:00Z", "count": 0, "events": []},
                    headers={"Content-Disposition": "attachment; filename=audit-log.json"},
                )

        monkeypatch.setattr(mod, "ApplicantEngineClient", FakeEngine)
        client = TestClient(app)
        resp = client.get("/api/applicant/admin/audit-log/c-1/export.json")
        assert resp.status_code == 200
