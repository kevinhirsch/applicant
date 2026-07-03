"""Regression coverage for wiring "Promote to base résumé" through to the
white-labeled front door (dark-engine audit item 33).

``MaterialService.promote_to_base_resume`` (``src/applicant/application/
services/material_service.py``, #293) clears a résumé variant's ``parent_id``
and marks it approved, so future tailoring forks from the user's best-performing
variant instead of the original base résumé. It had zero callers and no engine
router exposed it -- a user with a clearly winning tailored résumé (per the
A/B scoreboard's interview-rate on variant cards) had no way to make it the new
baseline. This file covers the four pieces that close that gap:

  * engine ``POST /api/documents/variants/{variant_id}/promote``
    (``src/applicant/app/routers/documents.py`` -- covered separately by
    ``tests/unit/test_promote_variant_route.py`` on the engine side).
  * ``workspace/src/applicant_engine.py`` -- new ``promote_variant`` client
    method.
  * ``workspace/routes/applicant_documents_routes.py`` -- new
    ``POST /api/applicant/documents/variants/{variant_id}/promote`` proxy.
    Owner-scoped: since the engine route takes only a bare ``variant_id`` (no
    campaign to check directly), the proxy fans out over the caller's OWN
    ``list_campaigns()`` -> ``list_variants()`` results and only forwards the
    promote when the variant turns up under one of them -- mirrors
    ``download_variant``/``_owner_campaign_ids``'s isolation boundary
    elsewhere in this file. THE MANDATORY OWNER-ISOLATION TEST below proves a
    variant that doesn't belong to any of the caller's own campaigns 404s and
    the engine's promote endpoint is never even hit.
  * ``workspace/static/js/documentLibrary.js`` -- a "Promote to base résumé"
    control on résumé-variant cards, alongside the existing "Approve resume"
    control, gated behind a plain-language confirm dialog.

Every assertion here was hand-verified to go RED when the corresponding piece
of the wiring is reverted (dropping the client method / the proxy route / the
owner-scoping guard / the JS control / the confirm), then GREEN again after
restoring -- per this series' standing definition of done.
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


def _read(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8")


# ── engine client: promote_variant ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_client_promote_variant_hits_exact_engine_path():
    """The client method must POST the exact engine route from
    ``src/applicant/app/routers/documents.py``."""
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["method"] = request.method
        return httpx.Response(
            201,
            json={
                "id": "var-123",
                "type": "resume_variant",
                "approved": True,
                "campaign_id": "camp-1",
                "parent_id": None,
            },
        )

    client = ApplicantEngineClient(
        base_url="http://api:8000", transport=httpx.MockTransport(handler)
    )
    data = await client.promote_variant("var-123")
    assert seen["path"] == "/api/documents/variants/var-123/promote"
    assert seen["method"] == "POST"
    assert data["approved"] is True
    assert data["parent_id"] is None


@pytest.mark.asyncio
async def test_client_promote_variant_raises_typed_error_on_404():
    """An unknown variant id surfaces as the typed ``EngineError``, matching
    every other client method's error-normalization contract."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"detail": "no such variant var-missing"})

    client = ApplicantEngineClient(
        base_url="http://api:8000", transport=httpx.MockTransport(handler)
    )
    with pytest.raises(EngineError) as exc_info:
        await client.promote_variant("var-missing")
    assert exc_info.value.status == 404


# ── workspace proxy route ───────────────────────────────────────────────────


def _mock_transport_app(handler, *, authed=True, user="tester"):
    """A bare app with only the documents router mounted, wired to a REAL
    ``ApplicantEngineClient`` riding an ``httpx.MockTransport`` -- so multi-call
    proxy logic (list_campaigns -> list_variants -> promote) is exercised
    against real request objects, not a hand-rolled fake. Mirrors
    ``test_applicant_variant_pdf_download.py``'s convention."""

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
    résumé variant, and the promote itself succeeds."""
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
        if request.url.path == f"/api/documents/variants/{owned_variant_id}/promote":
            return httpx.Response(
                201,
                json={
                    "id": owned_variant_id,
                    "type": "resume_variant",
                    "approved": True,
                    "campaign_id": owned_campaign_id,
                    "parent_id": None,
                },
            )
        return httpx.Response(404, json={"detail": "unexpected path in test"})

    return handler, seen_paths


def test_promote_variant_forwards_to_engine_for_owned_variant(monkeypatch):
    handler, seen_paths = _owned_variant_handler()
    app, engine_cls = _mock_transport_app(handler)
    monkeypatch.setattr(docs_routes, "ApplicantEngineClient", engine_cls)
    client = TestClient(app)

    resp = client.post("/api/applicant/documents/variants/var-1/promote")

    assert resp.status_code == 200
    body = resp.json()
    assert body["approved"] is True
    assert body["parent_id"] is None
    # The full owner-scoping fan-out happened: campaigns, then that campaign's
    # variants, then the promote itself.
    assert "/api/campaigns" in seen_paths
    assert "/api/documents/variants/camp-1" in seen_paths
    assert "/api/documents/variants/var-1/promote" in seen_paths


def test_promote_variant_requires_authentication(monkeypatch):
    def _boom(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        raise AssertionError("engine must not be called when unauthenticated")

    app, engine_cls = _mock_transport_app(_boom, authed=False)
    monkeypatch.setattr(docs_routes, "ApplicantEngineClient", engine_cls)

    class _Configured:
        is_configured = True

    app.state.auth_manager = _Configured()
    client = TestClient(app)
    resp = client.post("/api/applicant/documents/variants/var-1/promote")
    assert resp.status_code == 401


def test_promote_variant_owner_isolation_blocks_foreign_variant(monkeypatch):
    """MANDATORY: a caller must NOT be able to promote a résumé variant that
    belongs to another owner's campaign. The attacker here owns "camp-1" (with
    variant "var-1") but requests "var-999", which belongs to nobody the
    caller can see. The proxy must 404 -- AND never even call the engine's
    promote endpoint for that foreign id (proving the leak is closed at the
    proxy, not just after a mutation already happened)."""
    handler, seen_paths = _owned_variant_handler(owned_campaign_id="camp-1", owned_variant_id="var-1")
    app, engine_cls = _mock_transport_app(handler)
    monkeypatch.setattr(docs_routes, "ApplicantEngineClient", engine_cls)
    client = TestClient(app)

    resp = client.post("/api/applicant/documents/variants/var-999/promote")

    assert resp.status_code == 404
    assert not any(p.endswith("/var-999/promote") for p in seen_paths), (
        "the engine's promote endpoint must never be hit for a variant that "
        "isn't confirmed to belong to the caller"
    )


def test_promote_variant_returns_503_when_engine_unreachable(monkeypatch):
    def _timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    app, engine_cls = _mock_transport_app(_timeout)
    monkeypatch.setattr(docs_routes, "ApplicantEngineClient", engine_cls)
    client = TestClient(app)

    resp = client.post("/api/applicant/documents/variants/var-1/promote")
    assert resp.status_code == 503


# ── front-end: "Promote to base résumé" control on résumé-variant cards ────


def _applicant_card_body() -> str:
    src = _read(DOC_LIBRARY_JS)
    fn = re.search(
        r"function _applicantCard\(item, appId, results\) \{.*?\n    \}\n", src, re.S
    )
    assert fn, "expected the _applicantCard(item, appId, results) renderer"
    return fn.group(0)


def test_variant_card_renders_a_promote_control():
    body = _applicant_card_body()
    assert "Promote to base résumé" in body


def test_variant_card_promote_control_points_at_the_owner_scoped_proxy():
    body = _applicant_card_body()
    # Same base the approve/download buttons already use -- the owner-scoped
    # `/api/applicant/documents` proxy, never a direct engine URL.
    assert "${_APPLICANT_BASE}/variants/${encodeURIComponent(item.id)}/promote" in body


def test_variant_card_promote_control_is_scoped_to_the_variant_branch():
    """The promote control must live inside the ``isVariant`` branch (the same
    branch the "Approve resume" button lives in) -- a non-variant document
    (cover letter / screening answer) has no lineage to promote and must not
    offer this control."""
    body = _applicant_card_body()
    variant_branch = re.search(r"if \(isVariant\) \{.*?\n      \} else \{", body, re.S)
    assert variant_branch, "expected an isVariant branch in _applicantCard"
    assert "Promote to base résumé" in variant_branch.group(0)
    non_variant_branch = body[variant_branch.end():]
    non_variant_branch = non_variant_branch.split("card.appendChild(actions);")[0]
    assert "Promote to base résumé" not in non_variant_branch


def test_variant_card_promote_control_reuses_the_shared_action_button_classes():
    """CLAUDE.md: reuse the workspace design system -- the same
    ``doclib-card-text-btn doclib-card-action-btn`` classes every other card
    action button already uses, not a hand-rolled style."""
    body = _applicant_card_body()
    promote_snippet = body[body.index("promoteBtn = document.createElement"):]
    class_line = re.search(r"promoteBtn\.className = '([^']+)'", promote_snippet)
    assert class_line
    assert class_line.group(1) == "doclib-card-text-btn doclib-card-action-btn"


def test_variant_card_promote_control_confirms_before_acting():
    """Promoting changes what future tailoring forks from -- a plain-language
    confirm must gate the request, and the fetch must not fire when the user
    declines it."""
    body = _applicant_card_body()
    promote_snippet = body[body.index("promoteBtn = document.createElement"):]
    confirm_match = re.search(r"confirm\('([^']+)'\)", promote_snippet)
    assert confirm_match, "expected a plain-language confirm() before promoting"
    message = confirm_match.group(1).lower()
    # Plain language, not jargon: says what changes for the USER (future
    # tailoring/resumes build from this one), not engine internals.
    assert "base" in message
    assert "future" in message
    # The confirm must guard the fetch: an early return on decline appears
    # before the network call in source order.
    confirm_pos = promote_snippet.index("confirm(")
    if_not_ok_pos = promote_snippet.index("if (!ok) return;")
    fetch_pos = promote_snippet.index("fetch(")
    assert confirm_pos < if_not_ok_pos < fetch_pos
