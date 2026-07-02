"""Regression coverage for wiring the tailored-résumé PDF download through to
the white-labeled front door (dark-engine audit item 16).

The engine has served the compiled PDF at
``GET /api/documents/variants/{variant_id}/download`` since issue #178
(``src/applicant/app/routers/documents.py``), but until this change there was
no client method, no workspace proxy, and no front-end control -- a user could
approve a tailored résumé they could never actually save or open. This file
covers the three pieces that close that gap:

  * ``workspace/src/applicant_engine.py`` -- new ``download_variant_pdf``
    client method (returns the raw ``httpx.Response`` via ``expect_json=False``,
    mirroring the existing ``audit_log_campaign_export`` binary-passthrough
    convention).
  * ``workspace/routes/applicant_documents_routes.py`` -- new
    ``GET /api/applicant/documents/variants/{variant_id}/download`` proxy.
    Owner-scoped: since the engine route takes only a bare ``variant_id`` (no
    campaign to check directly, unlike the screening-answer library), the
    proxy fans out over the caller's OWN ``list_campaigns()`` ->
    ``list_variants()`` results and only forwards the download when the
    variant turns up under one of them. THE MANDATORY OWNER-ISOLATION TEST
    below proves a variant that doesn't belong to any of the caller's own
    campaigns 404s and the engine's download endpoint is never even hit.
  * ``workspace/static/js/documentLibrary.js`` -- a "Download PDF" control on
    résumé-variant cards in the document library, alongside the existing
    "Approve resume" control.

Every assertion here was hand-verified to go RED when the corresponding piece
of the wiring is reverted (dropping the client method / the proxy route / the
owner-scoping guard / the JS control), then GREEN again after restoring --
per this series' standing definition of done.
"""

from __future__ import annotations

import pathlib
import re

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import routes.applicant_documents_routes as docs_routes
from routes.applicant_documents_routes import setup_applicant_documents_routes
from src.applicant_engine import ApplicantEngineClient, EngineError

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
WORKSPACE_DIR = REPO_ROOT / "workspace"
DOC_LIBRARY_JS = WORKSPACE_DIR / "static" / "js" / "documentLibrary.js"

_FAKE_PDF_BYTES = b"%PDF-1.7 fake rendered resume bytes for tests"


def _read(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8")


# ── engine client: download_variant_pdf ─────────────────────────────────────


@pytest.mark.asyncio
async def test_client_download_variant_pdf_hits_exact_engine_path_and_returns_raw_response():
    """The client method must GET the exact engine route from
    ``src/applicant/app/routers/documents.py`` and hand back the raw
    ``httpx.Response`` (bytes + headers) rather than trying to JSON-decode a
    binary PDF body."""
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
    resp = await client.download_variant_pdf("var-123")
    assert seen["path"] == "/api/documents/variants/var-123/download"
    assert seen["method"] == "GET"
    assert resp.content == _FAKE_PDF_BYTES
    assert resp.headers["content-type"] == "application/pdf"


@pytest.mark.asyncio
async def test_client_download_variant_pdf_raises_typed_error_on_404():
    """A missing artifact (stub mode / compile failure) surfaces as the typed
    ``EngineError``, not a raw httpx exception, matching every other client
    method's error-normalization contract."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"detail": "Rendered artifact not found."})

    client = ApplicantEngineClient(
        base_url="http://api:8000", transport=httpx.MockTransport(handler)
    )
    with pytest.raises(EngineError) as exc_info:
        await client.download_variant_pdf("var-missing")
    assert exc_info.value.status == 404


# ── workspace proxy route ───────────────────────────────────────────────────


def _mock_transport_app(handler, *, authed=True, user="tester"):
    """A bare app with only the documents router mounted, wired to a REAL
    ``ApplicantEngineClient`` riding an ``httpx.MockTransport`` -- so multi-call
    proxy logic (list_campaigns -> list_variants -> download) is exercised
    against real request objects, not a hand-rolled fake. Mirrors
    ``test_applicant_admin_routes.py``'s ``_mock_transport_app`` convention."""

    class TransportEngine(ApplicantEngineClient):
        def __init__(self, *a, **k):
            super().__init__(base_url="http://api:8000", transport=httpx.MockTransport(handler))

    app = FastAPI()
    if authed:
        from fastapi import Request

        @app.middleware("http")
        async def _set_user(request: Request, call_next):
            request.state.current_user = user
            return await call_next(request)

    app.include_router(setup_applicant_documents_routes())
    return app, TransportEngine


def _owned_variant_handler(*, owned_campaign_id="camp-1", owned_variant_id="var-1"):
    """A handler where the caller owns exactly one campaign with exactly one
    résumé variant, and the download itself succeeds."""
    seen_paths = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_paths.append(request.url.path)
        if request.url.path == "/api/campaigns":
            return httpx.Response(200, json=[{"id": owned_campaign_id, "name": "Search 1"}])
        if request.url.path == f"/api/documents/variants/{owned_campaign_id}":
            return httpx.Response(
                200,
                json={
                    "campaign_id": owned_campaign_id,
                    "variants": [{"variant_id": owned_variant_id, "is_root": True}],
                },
            )
        if request.url.path == f"/api/documents/variants/{owned_variant_id}/download":
            return httpx.Response(
                200, content=_FAKE_PDF_BYTES, headers={"content-type": "application/pdf"}
            )
        return httpx.Response(404, json={"detail": "unexpected path in test"})

    return handler, seen_paths


def test_download_variant_returns_pdf_bytes_with_attachment_headers(monkeypatch):
    handler, seen_paths = _owned_variant_handler()
    app, engine_cls = _mock_transport_app(handler)
    monkeypatch.setattr(docs_routes, "ApplicantEngineClient", engine_cls)
    client = TestClient(app)

    resp = client.get("/api/applicant/documents/variants/var-1/download")

    assert resp.status_code == 200
    assert resp.content == _FAKE_PDF_BYTES
    assert resp.headers["content-type"].startswith("application/pdf")
    disposition = resp.headers["content-disposition"]
    assert "attachment" in disposition
    assert "var-1" in disposition
    # The full owner-scoping fan-out happened: campaigns, then that campaign's
    # variants, then the download itself.
    assert "/api/campaigns" in seen_paths
    assert "/api/documents/variants/camp-1" in seen_paths
    assert "/api/documents/variants/var-1/download" in seen_paths


def test_download_variant_requires_authentication(monkeypatch):
    def _boom(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        raise AssertionError("engine must not be called when unauthenticated")

    app, engine_cls = _mock_transport_app(_boom, authed=False)
    monkeypatch.setattr(docs_routes, "ApplicantEngineClient", engine_cls)

    # No auth_manager on app.state at all -> require_user's "not configured"
    # path allows through in some proxies, so also assert the more realistic
    # "configured but no logged-in user" 401 gate matches the rest of the file.
    class _Configured:
        is_configured = True

    app.state.auth_manager = _Configured()
    client = TestClient(app)
    resp = client.get("/api/applicant/documents/variants/var-1/download")
    assert resp.status_code == 401


def test_download_variant_owner_isolation_blocks_foreign_variant(monkeypatch):
    """MANDATORY: a caller must NOT be able to download a résumé variant that
    belongs to another owner's campaign. The attacker here owns "camp-1" (with
    variant "var-1") but requests "var-999", which belongs to nobody the
    caller can see. The proxy must 404 -- AND never even call the engine's
    download endpoint for that foreign id (proving the leak is closed at the
    proxy, not just filtered after the bytes were already fetched)."""
    handler, seen_paths = _owned_variant_handler(owned_campaign_id="camp-1", owned_variant_id="var-1")
    app, engine_cls = _mock_transport_app(handler)
    monkeypatch.setattr(docs_routes, "ApplicantEngineClient", engine_cls)
    client = TestClient(app)

    resp = client.get("/api/applicant/documents/variants/var-999/download")

    assert resp.status_code == 404
    assert not any(p.endswith("/var-999/download") for p in seen_paths), (
        "the engine's download endpoint must never be hit for a variant that "
        "isn't confirmed to belong to the caller"
    )


def test_download_variant_returns_503_when_engine_unreachable(monkeypatch):
    def _timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    app, engine_cls = _mock_transport_app(_timeout)
    monkeypatch.setattr(docs_routes, "ApplicantEngineClient", engine_cls)
    client = TestClient(app)

    resp = client.get("/api/applicant/documents/variants/var-1/download")
    assert resp.status_code == 503


# ── front-end: "Download PDF" control on résumé-variant cards ──────────────


def _applicant_card_body() -> str:
    src = _read(DOC_LIBRARY_JS)
    fn = re.search(
        r"function _applicantCard\(item, appId, results\) \{.*?\n    \}\n", src, re.S
    )
    assert fn, "expected the _applicantCard(item, appId, results) renderer"
    return fn.group(0)


def test_variant_card_renders_a_download_pdf_control():
    body = _applicant_card_body()
    assert "Download PDF" in body


def test_variant_card_download_control_points_at_the_owner_scoped_proxy():
    body = _applicant_card_body()
    # Same base the approve button already uses -- the owner-scoped
    # `/api/applicant/documents` proxy, never a direct engine URL.
    assert "${_APPLICANT_BASE}/variants/${encodeURIComponent(item.id)}/download" in body


def test_variant_card_download_control_is_scoped_to_the_variant_branch():
    """The download control must live inside the ``isVariant`` branch (the
    same branch the "Approve resume" button lives in) -- a non-variant
    document (cover letter / screening answer) has no rendered PDF artifact
    and must not offer this control."""
    body = _applicant_card_body()
    variant_branch = re.search(r"if \(isVariant\) \{.*?\n      \} else \{", body, re.S)
    assert variant_branch, "expected an isVariant branch in _applicantCard"
    assert "Download PDF" in variant_branch.group(0)
    non_variant_branch = body[variant_branch.end():]
    non_variant_branch = non_variant_branch.split("card.appendChild(actions);")[0]
    assert "Download PDF" not in non_variant_branch


def test_variant_card_download_control_reuses_the_shared_action_button_classes():
    """CLAUDE.md: reuse the workspace design system -- the same
    ``doclib-card-text-btn doclib-card-action-btn`` classes every other card
    action button already uses, not a hand-rolled style."""
    body = _applicant_card_body()
    download_snippet = body[body.index("downloadBtn = document.createElement"):]
    class_line = re.search(r"downloadBtn\.className = '([^']+)'", download_snippet)
    assert class_line
    assert class_line.group(1) == "doclib-card-text-btn doclib-card-action-btn"
