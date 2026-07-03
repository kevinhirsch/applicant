"""Regression test: the variant-library proxy forwards the ancestry ``lineage``
field untouched (dark-engine audit item 50).

The engine's ``GET /api/documents/variants/{campaign_id}`` now attaches a
``lineage`` list (root-first ancestor chain, via ``MaterialService.lineage``) to
each variant row. ``routes/applicant_documents_routes.py``'s ``variant_library``
proxy is a thin, owner-scoped pass-through (``JSONResponse(content=data)``) — this
confirms it does not strip or reshape the new field, mirroring the existing
pass-through coverage for the rest of the variant-library payload.

Hermetic: zero network, the engine client is a fake async-context-manager (same
pattern as ``test_applicant_documents_routes.py``).
"""

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

import routes.applicant_documents_routes as docs_routes
from routes.applicant_documents_routes import setup_applicant_documents_routes


class _FakeEngine:
    """Stand-in for ApplicantEngineClient — records the call, returns canned JSON."""

    last_call = None

    def __init__(self, *, result=None):
        self._result = result

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def list_variants(self, campaign_id):
        type(self).last_call = ("list_variants", (campaign_id,))
        return self._result


def _make_client():
    app = FastAPI()

    @app.middleware("http")
    async def _set_user(request: Request, call_next):
        request.state.current_user = "tester"
        return await call_next(request)

    app.include_router(setup_applicant_documents_routes())
    return TestClient(app, raise_server_exceptions=True)


def _patch_engine(monkeypatch, *, result=None):
    _FakeEngine.last_call = None
    monkeypatch.setattr(
        docs_routes, "ApplicantEngineClient", lambda *a, **k: _FakeEngine(result=result)
    )


def test_variant_lineage_field_passes_through_untouched(monkeypatch):
    payload = {
        "campaign_id": "camp-lineage-1",
        "variants": [
            {
                "variant_id": "grandchild",
                "is_root": False,
                "lineage": [
                    {"variant_id": "root", "is_root": True, "targeted_jd_signature": None, "approved": True},
                    {"variant_id": "child", "is_root": False, "targeted_jd_signature": "acme-swe", "approved": True},
                    {"variant_id": "grandchild", "is_root": False, "targeted_jd_signature": "beta-swe", "approved": False},
                ],
            }
        ],
    }
    _patch_engine(monkeypatch, result=payload)
    resp = _make_client().get("/api/applicant/documents/variants/camp-lineage-1")
    assert resp.status_code == 200
    body = resp.json()
    assert body == payload
    assert body["variants"][0]["lineage"][0]["variant_id"] == "root"
    assert body["variants"][0]["lineage"][-1]["variant_id"] == "grandchild"
    assert _FakeEngine.last_call == ("list_variants", ("camp-lineage-1",))


def test_variant_lineage_endpoint_requires_auth(monkeypatch):
    payload = {"campaign_id": "camp-lineage-2", "variants": []}
    _patch_engine(monkeypatch, result=payload)
    app = FastAPI()
    app.include_router(setup_applicant_documents_routes())
    resp = TestClient(app, raise_server_exceptions=True).get(
        "/api/applicant/documents/variants/camp-lineage-2"
    )
    assert resp.status_code in (401, 403)
