"""Regression coverage for showing REAL screenshot images in the Debug modal,
not just text labels (dark-engine audit item 28).

``GET /api/admin/screenshots/{application_id}`` (``src/applicant/app/routers/
admin.py``) already listed per-page captures, already proxied through
(``routes/applicant_admin_routes.py``) and rendered in ``applicantDebug.js`` --
but only as a filename LABEL (``page_ref``/``page_url``), never the actual
pixels. ``page_ref`` is a ``file://`` ref into the sandbox's local capture
directory, so an ``<img src>`` needed a binary-serving seam that didn't exist
anywhere in the chain. This file covers the three pieces that close that gap:

  * ``src/applicant/app/routers/admin.py`` -- new ``GET /api/admin/screenshots/
    {application_id}/{screenshot_id}/image`` route (covered end-to-end for real
    storage/bytes behavior in ``tests/unit/test_admin_screenshot_image_route.py``;
    this file only proves the workspace side of the chain).
  * ``workspace/src/applicant_engine.py`` -- new ``admin_screenshot_image``
    client method (raw ``httpx.Response`` via ``expect_json=False``, mirroring
    the existing ``audit_log_campaign_export`` binary-passthrough convention).
  * ``workspace/routes/applicant_admin_routes.py`` -- new
    ``GET /api/applicant/admin/screenshots/{application_id}/{screenshot_id}/image``
    proxy, gated by the same ``_require_admin`` every other Debug-surface route uses.
  * ``workspace/static/js/applicantDebug.js`` -- the screenshot list now renders
    ``<img>`` thumbnails pointing at that proxy (click-to-enlarge), instead of
    the old label-only ``<span>``.

Every assertion here was hand-verified to go RED when the corresponding piece
of the wiring is reverted (dropping the client method / the proxy route / the
JS thumbnail rendering), then GREEN again after restoring -- per this series'
standing definition of done.
"""

from __future__ import annotations

import pathlib
import re

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import routes.applicant_admin_routes as mod
from routes.applicant_admin_routes import setup_applicant_admin_routes
from src.applicant_engine import ApplicantEngineClient, EngineError

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
WORKSPACE_DIR = REPO_ROOT / "workspace"
DEBUG_JS = WORKSPACE_DIR / "static" / "js" / "applicantDebug.js"

_FAKE_PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"fake-but-nonempty-capture-bytes" * 4


def _read(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8")


# ── engine client: admin_screenshot_image ───────────────────────────────────


@pytest.mark.asyncio
async def test_client_admin_screenshot_image_hits_exact_engine_path_and_returns_raw_response():
    """The client method must GET the exact engine route added in
    ``src/applicant/app/routers/admin.py`` and hand back the raw
    ``httpx.Response`` (bytes + headers) rather than trying to JSON-decode a
    binary image body."""
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["method"] = request.method
        return httpx.Response(200, content=_FAKE_PNG_BYTES, headers={"content-type": "image/png"})

    client = ApplicantEngineClient(base_url="http://api:8000", transport=httpx.MockTransport(handler))
    resp = await client.admin_screenshot_image("app-1", "shot-1")
    assert seen["path"] == "/api/admin/screenshots/app-1/shot-1/image"
    assert seen["method"] == "GET"
    assert resp.content == _FAKE_PNG_BYTES
    assert resp.headers["content-type"] == "image/png"


@pytest.mark.asyncio
async def test_client_admin_screenshot_image_raises_typed_error_on_404():
    """A missing/no-longer-available capture surfaces as the typed
    ``EngineError``, not a raw httpx exception, matching every other client
    method's error-normalization contract."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"detail": "Screenshot not found"})

    client = ApplicantEngineClient(base_url="http://api:8000", transport=httpx.MockTransport(handler))
    with pytest.raises(EngineError) as exc_info:
        await client.admin_screenshot_image("app-1", "shot-missing")
    assert exc_info.value.status == 404


# ── workspace proxy route ───────────────────────────────────────────────────


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


def _mock_transport_app(handler, *, user="alice") -> tuple[FastAPI, type]:
    """A real ``ApplicantEngineClient`` riding an ``httpx.MockTransport`` --
    mirrors ``test_applicant_variant_pdf_download.py``'s convention so the
    proxy's exact request/response passthrough is exercised for real."""

    class TransportEngine(ApplicantEngineClient):
        def __init__(self, *a, **k):
            super().__init__(base_url="http://api:8000", transport=httpx.MockTransport(handler))

    return _make_app(user=user), TransportEngine


def test_screenshot_image_proxy_streams_bytes_and_content_type(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/admin/screenshots/app-1/shot-1/image"
        return httpx.Response(200, content=_FAKE_PNG_BYTES, headers={"content-type": "image/png"})

    app, engine_cls = _mock_transport_app(handler)
    monkeypatch.setattr(mod, "ApplicantEngineClient", engine_cls)
    client = TestClient(app)

    resp = client.get("/api/applicant/admin/screenshots/app-1/shot-1/image")

    assert resp.status_code == 200
    assert resp.content == _FAKE_PNG_BYTES  # the REAL bytes, not a placeholder
    assert resp.headers["content-type"] == "image/png"


def test_screenshot_image_proxy_forwards_404_from_engine(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"detail": "Screenshot not found"})

    app, engine_cls = _mock_transport_app(handler)
    monkeypatch.setattr(mod, "ApplicantEngineClient", engine_cls)
    client = TestClient(app)

    resp = client.get("/api/applicant/admin/screenshots/app-1/shot-missing/image")
    assert resp.status_code == 404


def test_screenshot_image_proxy_returns_503_when_engine_unreachable(monkeypatch):
    def timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    app, engine_cls = _mock_transport_app(timeout)
    monkeypatch.setattr(mod, "ApplicantEngineClient", engine_cls)
    client = TestClient(app)

    resp = client.get("/api/applicant/admin/screenshots/app-1/shot-1/image")
    assert resp.status_code == 503


def test_screenshot_image_proxy_requires_admin(monkeypatch):
    def _boom(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        raise AssertionError("engine must not be called for a non-admin caller")

    app, engine_cls = _mock_transport_app(_boom, user="bob")
    app.state.auth_manager = _AuthMgr(configured=True, admins={"alice"})
    monkeypatch.setattr(mod, "ApplicantEngineClient", engine_cls)
    client = TestClient(app)

    resp = client.get("/api/applicant/admin/screenshots/app-1/shot-1/image")
    assert resp.status_code == 403


# ── front-end: real <img> thumbnails, not just a label ─────────────────────


def _show_app_detail_body() -> str:
    src = _read(DEBUG_JS)
    # `triggerBtn` is an optional second param added by the a11y pass (05/01)
    # so the drill-in's Close button can hand focus back to the row that
    # opened it — the signature match tolerates it either way.
    fn = re.search(r"async function _showAppDetail\(appId(?:, triggerBtn)?\) \{.*?\n\}\n", src, re.S)
    assert fn, "expected the _showAppDetail(appId) renderer"
    return fn.group(0)


def test_screenshot_list_renders_real_img_thumbnails_not_just_labels():
    body = _show_app_detail_body()
    assert "<img" in body
    assert "applicant-debug-shot-thumb" in body


def test_screenshot_thumbnail_src_points_at_the_new_image_proxy():
    src = _read(DEBUG_JS)
    fn = re.search(r"function _screenshotImgUrl\(appId, screenshotId\) \{.*?\n\}\n", src, re.S)
    assert fn, "expected a _screenshotImgUrl(appId, screenshotId) helper"
    body = fn.group(0)
    assert "/screenshots/" in body
    assert "/image" in body


def test_screenshot_thumbnails_are_click_to_enlarge():
    body = _show_app_detail_body()
    assert "applicant-debug-shot-thumb" in body
    assert "_openScreenshotLightbox" in body
    src = _read(DEBUG_JS)
    assert "function _openScreenshotLightbox(" in src


def test_screenshot_lightbox_reuses_existing_attach_lightbox_styling():
    """CLAUDE.md principle #1 (lift and shift): reuse the chat attachment
    lightbox's existing ``.attach-lightbox`` CSS class instead of hand-rolling
    a new overlay style."""
    src = _read(DEBUG_JS)
    # `triggerEl` is an optional third param (a11y pass 05/01, focus restore
    # on close) — tolerate it either way, same convention as
    # `_show_app_detail_body` above.
    fn = re.search(r"function _openScreenshotLightbox\(url, label(?:, triggerEl)?\) \{.*?\n\}\n", src, re.S)
    assert fn, "expected an _openScreenshotLightbox(url, label) function"
    assert "attach-lightbox" in fn.group(0)


def test_missing_screenshot_id_falls_back_to_label_not_a_broken_image():
    body = _show_app_detail_body()
    assert "s.page_ref || s.page || s.label || 'page'" in body
