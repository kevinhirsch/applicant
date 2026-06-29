"""#252 — Global unhandled-exception handler.

Verifies that:

1. An unhandled ``Exception`` from a route returns HTTP 500 with a GENERIC body
   (no traceback, no internal detail).
2. The response body is ``{"detail": "An unexpected error occurred..."}`` —
   never the raw exception message.
3. The handler does NOT suppress ``DomainError`` — those still return the
   correct 4xx via the existing domain-error handler.
4. The handler works even for ``Exception`` subclasses that are not ``DomainError``.
"""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.testclient import TestClient

from applicant.app.main import create_app
from applicant.core.errors import NotFound

# ---------------------------------------------------------------------------
# Helpers — inject test routes that raise specific exceptions
# ---------------------------------------------------------------------------


def _make_app_with_boom_route(exc_factory):
    """Create a test app with a /boom route that raises exc_factory()."""
    app = create_app()

    router = APIRouter()

    @router.get("/boom")
    def _boom():
        raise exc_factory()

    app.include_router(router)
    return app


# ---------------------------------------------------------------------------
# 1. Unhandled exception → 500 with generic body
# ---------------------------------------------------------------------------


class TestUnhandledExceptionReturns500:
    def test_returns_500_status(self):
        app = _make_app_with_boom_route(lambda: RuntimeError("internal failure"))
        with TestClient(app, raise_server_exceptions=False) as c:
            res = c.get("/boom")
        assert res.status_code == 500

    def test_response_body_is_generic(self):
        app = _make_app_with_boom_route(lambda: RuntimeError("internal failure"))
        with TestClient(app, raise_server_exceptions=False) as c:
            res = c.get("/boom")
        body = res.json()
        assert "detail" in body
        # Must NOT contain the raw exception message.
        assert "internal failure" not in body["detail"]

    def test_response_does_not_contain_traceback(self):
        app = _make_app_with_boom_route(lambda: RuntimeError("internal failure"))
        with TestClient(app, raise_server_exceptions=False) as c:
            res = c.get("/boom")
        text = res.text
        assert "Traceback" not in text
        assert "RuntimeError" not in text

    def test_generic_message_present(self):
        app = _make_app_with_boom_route(lambda: RuntimeError("internal failure"))
        with TestClient(app, raise_server_exceptions=False) as c:
            res = c.get("/boom")
        body = res.json()
        assert "unexpected error" in body["detail"].lower()

    def test_value_error_also_returns_500(self):
        app = _make_app_with_boom_route(lambda: ValueError("bad value"))
        with TestClient(app, raise_server_exceptions=False) as c:
            res = c.get("/boom")
        assert res.status_code == 500
        body = res.json()
        assert "bad value" not in body.get("detail", "")

    def test_key_error_also_returns_500(self):
        app = _make_app_with_boom_route(lambda: KeyError("missing"))
        with TestClient(app, raise_server_exceptions=False) as c:
            res = c.get("/boom")
        assert res.status_code == 500


# ---------------------------------------------------------------------------
# 2. DomainError still maps to 4xx (handler does not override domain handler)
# ---------------------------------------------------------------------------


class TestDomainErrorNotSuppressed:
    def test_domain_not_found_returns_404(self):
        app = _make_app_with_boom_route(lambda: NotFound("thing", "x"))
        with TestClient(app, raise_server_exceptions=False) as c:
            res = c.get("/boom")
        assert res.status_code == 404

    def test_domain_error_detail_is_message(self):
        app = _make_app_with_boom_route(lambda: NotFound("thing", "x"))
        with TestClient(app, raise_server_exceptions=False) as c:
            res = c.get("/boom")
        body = res.json()
        assert "detail" in body
        # DomainError detail IS the error message (4xx, safe to return)
        assert body["detail"]  # non-empty


# ---------------------------------------------------------------------------
# 3. /healthz is unaffected (still returns 200 on the hermetic path)
# ---------------------------------------------------------------------------


class TestHealthzUnaffected:
    def test_healthz_still_200(self):
        app = create_app()
        with TestClient(app) as c:
            res = c.get("/healthz")
        assert res.status_code == 200
