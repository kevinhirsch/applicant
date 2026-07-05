"""Regression coverage for downloading the LaTeX conversion PREVIEW PDF
(dark-engine audit item 19): ``GET /api/applicant/setup/conversion/{campaign_id}
/preview/download``.

The engine has served the compiled preview PDF at
``GET /api/conversion/{campaign_id}/preview/download`` since issue #178
(``src/applicant/app/routers/conversion.py``), but the onboarding accept/reject
step never let the user actually open it -- the decision was made from the
page-count/fidelity summary alone. This file covers the three pieces that
close that gap, mirroring the conventions ``test_applicant_variant_pdf_
download.py`` set for item 16's identical shape:

  * ``workspace/src/applicant_engine.py`` -- new
    ``download_conversion_preview_pdf`` client method (raw ``httpx.Response``,
    ``expect_json=False``).
  * ``workspace/routes/applicant_model_connections_routes.py`` -- new
    ``GET .../conversion/{campaign_id}/preview/download`` proxy.
  * ``workspace/static/js/applicantOnboarding.js`` -- an "Open preview PDF"
    control on the conversion preview card.
"""

from __future__ import annotations

import pathlib
import re

import httpx
import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

import routes.applicant_model_connections_routes as setup_routes
from routes.applicant_model_connections_routes import setup_applicant_model_connections_routes
from src.applicant_engine import ApplicantEngineClient, EngineError

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
WORKSPACE_DIR = REPO_ROOT / "workspace"
ONBOARDING_JS = WORKSPACE_DIR / "static" / "js" / "applicantOnboarding.js"

_FAKE_PDF_BYTES = b"%PDF-1.7 fake conversion preview bytes for tests"


def _read(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8")


# ── engine client: download_conversion_preview_pdf ─────────────────────────


@pytest.mark.asyncio
async def test_client_download_conversion_preview_pdf_hits_exact_engine_path():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["method"] = request.method
        return httpx.Response(
            200, content=_FAKE_PDF_BYTES, headers={"content-type": "application/pdf"}
        )

    client = ApplicantEngineClient(
        base_url="http://api:8000", transport=httpx.MockTransport(handler)
    )
    resp = await client.download_conversion_preview_pdf("camp-1")
    assert seen["path"] == "/api/conversion/camp-1/preview/download"
    assert seen["method"] == "GET"
    assert resp.content == _FAKE_PDF_BYTES


@pytest.mark.asyncio
async def test_client_download_conversion_preview_pdf_raises_typed_error_on_404():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"detail": "Conversion preview PDF not available."})

    client = ApplicantEngineClient(
        base_url="http://api:8000", transport=httpx.MockTransport(handler)
    )
    with pytest.raises(EngineError) as exc_info:
        await client.download_conversion_preview_pdf("camp-missing")
    assert exc_info.value.status == 404


# ── workspace proxy route ───────────────────────────────────────────────────


class _FakeEngine:
    last_call = None

    def __init__(self, *, response: httpx.Response | None = None, error: EngineError | None = None):
        self._response = response
        self._error = error

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def download_conversion_preview_pdf(self, campaign_id):
        type(self).last_call = ("download_conversion_preview_pdf", (campaign_id,))
        if self._error is not None:
            raise self._error
        return self._response


def _patch_engine(monkeypatch, *, response=None, error: EngineError | None = None):
    _FakeEngine.last_call = None
    monkeypatch.setattr(
        setup_routes,
        "ApplicantEngineClient",
        lambda *a, **k: _FakeEngine(response=response, error=error),
    )


def _make_client(*, authed: bool = True):
    app = FastAPI()
    if authed:
        @app.middleware("http")
        async def _set_user(request: Request, call_next):
            request.state.current_user = "tester"
            return await call_next(request)
    app.include_router(setup_applicant_model_connections_routes())
    return TestClient(app, raise_server_exceptions=True)


def test_download_preview_returns_pdf_bytes_with_attachment_headers(monkeypatch):
    fake_resp = httpx.Response(
        200, content=_FAKE_PDF_BYTES, headers={"content-type": "application/pdf"}
    )
    _patch_engine(monkeypatch, response=fake_resp)
    resp = _make_client().get("/api/applicant/setup/conversion/camp-1/preview/download")

    assert resp.status_code == 200
    assert resp.content == _FAKE_PDF_BYTES
    assert resp.headers["content-type"].startswith("application/pdf")
    disposition = resp.headers["content-disposition"]
    assert "attachment" in disposition
    assert "camp-1" in disposition
    assert _FakeEngine.last_call == ("download_conversion_preview_pdf", ("camp-1",))


def test_download_preview_requires_authentication(monkeypatch):
    def _boom(*a, **k):  # pragma: no cover
        raise AssertionError("engine must not be called when unauthenticated")

    monkeypatch.setattr(setup_routes, "ApplicantEngineClient", _boom)

    class _Configured:
        is_configured = True

    app = FastAPI()
    app.state.auth_manager = _Configured()
    app.include_router(setup_applicant_model_connections_routes())
    client = TestClient(app)
    resp = client.get("/api/applicant/setup/conversion/camp-1/preview/download")
    assert resp.status_code == 401


def test_download_preview_returns_502_when_engine_unreachable(monkeypatch):
    _patch_engine(monkeypatch, error=EngineError("down", is_timeout=True))
    resp = _make_client().get("/api/applicant/setup/conversion/camp-1/preview/download")
    assert resp.status_code == 502


def test_download_preview_404_passes_through(monkeypatch):
    _patch_engine(
        monkeypatch,
        error=EngineError("not available", status=404, detail="Conversion preview PDF not available."),
    )
    resp = _make_client().get("/api/applicant/setup/conversion/camp-1/preview/download")
    assert resp.status_code == 404


# ── front-end: "Open preview PDF" control on the conversion step ───────────


def _build_preview_body() -> str:
    src = _read(ONBOARDING_JS)
    fn = re.search(r"async function _buildPreview\(\) \{.*?\n\}", src, re.S)
    assert fn, "expected the _buildPreview() renderer"
    return fn.group(0)


def test_conversion_preview_card_renders_a_download_control():
    body = _build_preview_body()
    assert "ao-prev-download" in body
    assert "Open preview PDF" in body


def test_conversion_preview_download_control_points_at_the_proxy():
    body = _build_preview_body()
    assert "/conversion/${encodeURIComponent(_campaignId)}/preview/download" in body
