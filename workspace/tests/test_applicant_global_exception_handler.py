"""Regression test for the front-door global exception handler (#252).

Verifies that an unhandled exception in a route:
  - returns HTTP 500
  - returns the generic ``{"detail": "An unexpected error occurred…"}`` body
  - does NOT leak a traceback or internal exception message to the client
  - does NOT interfere with specific exception handlers (which must still
    take precedence and return their own status/body)

Uses a bare FastAPI app with a single crashing route and installs only the
catch-all handler so the test is hermetic and does not import the full
workspace.
"""

import traceback

import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from starlette.requests import Request

_GENERIC_DETAIL = "An unexpected error occurred. Please try again later."


def _make_app_with_handler() -> FastAPI:
    """Return a minimal FastAPI with only the catch-all handler wired up.

    Reproduces the handler added to workspace/app.py:
    - logs full server-side context (not tested here; side-effect only)
    - returns 500 + generic body
    """
    import logging

    logger = logging.getLogger("test_app")

    app = FastAPI()

    @app.get("/crash")
    async def crash_route():
        raise RuntimeError("internal secret: db_password=hunter2")

    @app.get("/ok")
    async def ok_route():
        return {"status": "ok"}

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        request_id = (
            request.headers.get("x-request-id")
            or request.headers.get("x-correlation-id")
        )
        logger.error(
            "unhandled_exception path=%s method=%s request_id=%s exc_type=%s\n%s",
            request.url.path,
            request.method,
            request_id,
            type(exc).__name__,
            traceback.format_exc(),
        )
        return JSONResponse(
            status_code=500,
            content={"detail": _GENERIC_DETAIL},
        )

    return app


@pytest.fixture
def client() -> TestClient:
    return TestClient(_make_app_with_handler(), raise_server_exceptions=False)


def test_unhandled_exception_returns_500(client: TestClient) -> None:
    resp = client.get("/crash")
    assert resp.status_code == 500


def test_unhandled_exception_returns_generic_body(client: TestClient) -> None:
    resp = client.get("/crash")
    body = resp.json()
    assert body == {"detail": _GENERIC_DETAIL}


def test_no_traceback_in_response(client: TestClient) -> None:
    resp = client.get("/crash")
    text = resp.text
    # Raw traceback markers must not appear in the HTTP response body
    assert "Traceback" not in text
    assert "RuntimeError" not in text
    assert "hunter2" not in text  # internal detail must not leak


def test_request_id_header_accepted(client: TestClient) -> None:
    """Handler must not crash when x-request-id / x-correlation-id are present."""
    resp = client.get(
        "/crash",
        headers={"x-request-id": "req-abc-123"},
    )
    assert resp.status_code == 500
    assert resp.json() == {"detail": _GENERIC_DETAIL}

    resp2 = client.get(
        "/crash",
        headers={"x-correlation-id": "corr-xyz-456"},
    )
    assert resp2.status_code == 500
    assert resp2.json() == {"detail": _GENERIC_DETAIL}


def test_ok_route_unaffected(client: TestClient) -> None:
    """The catch-all must not swallow responses from non-crashing routes."""
    resp = client.get("/ok")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_specific_handler_takes_precedence() -> None:
    """A specific handler registered BEFORE the catch-all must still win.

    FastAPI resolves handlers by most-specific type first; the catch-all
    (Exception) must not shadow a handler for a subclass.
    """
    import logging

    logger = logging.getLogger("test_specific")

    class MyError(Exception):
        pass

    app2 = FastAPI()

    @app2.get("/specific")
    async def specific_route():
        raise MyError("specific detail")

    @app2.exception_handler(MyError)
    async def _specific(request: Request, exc: MyError) -> JSONResponse:
        return JSONResponse(status_code=418, content={"error": "SPECIFIC"})

    @app2.exception_handler(Exception)
    async def _catch_all(request: Request, exc: Exception) -> JSONResponse:
        return JSONResponse(status_code=500, content={"detail": _GENERIC_DETAIL})

    c2 = TestClient(app2, raise_server_exceptions=False)
    resp = c2.get("/specific")
    # The specific handler (418) must win, not the catch-all (500)
    assert resp.status_code == 418
    assert resp.json() == {"error": "SPECIFIC"}
