"""Coverage: product-gaps backlog #23 (résumé <-> JD match-score explainer),
``docs/design/audits/PRODUCT_EXHAUSTIVE_AUDIT.md``, front-door half.

The engine half (``core.rules.jd_match.compute_jd_match`` +
``GET /api/documents/jd-match/{application_id}``) is covered by
``tests/unit/test_cov_backlog_jdmatch.py``. This file covers the front-door:

* ``routes/applicant_documents_routes.py``'s new ``GET
  /api/applicant/documents/jd-match/{application_id}`` proxy — a small,
  self-contained inline ``httpx`` call (NOT a new ``ApplicantEngineClient``
  method; that client is concurrently owned by another lane) mirroring
  ``ApplicantEngineClient._request``'s own timeout/error-normalization shape.
* ``static/js/documentLibrary.js``'s ``_loadJdMatch`` — the compact "Match
  score: N/100 — you cover X, Y; consider adding: Z" line rendered under the
  redline/materials header, reusing the existing gate-badge pill styling.

Route tests are hermetic (``httpx.MockTransport``, zero real network) following
the exact pattern ``test_applicant_backlog_perfcompression.py`` established for
proving a real route + injected transport. JS tests read the actual static
file content via regex — no browser, no DOM — following
``test_applicant_round2_wave2_redlinecta.py``'s convention.
"""

from __future__ import annotations

import pathlib
import re

import httpx
import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

import routes.applicant_documents_routes as docs_routes
from routes.applicant_documents_routes import setup_applicant_documents_routes
from src.applicant_engine import EngineError

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
JS_DIR = REPO_ROOT / "workspace" / "static" / "js"
DOCLIB_JS = JS_DIR / "documentLibrary.js"


def _read(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8")


# ── route: hermetic MockTransport wiring ─────────────────────────────────────


def _make_client(*, authed: bool = True) -> TestClient:
    app = FastAPI()
    if authed:
        @app.middleware("http")
        async def _set_user(request: Request, call_next):
            request.state.current_user = "tester"
            return await call_next(request)
    app.include_router(setup_applicant_documents_routes())
    return TestClient(app, raise_server_exceptions=True)


def _patch_transport(monkeypatch, handler):
    """Make every ``httpx.AsyncClient(...)`` constructed inside
    ``docs_routes`` (i.e. by ``_fetch_jd_match``) ride a ``MockTransport``
    instead of touching the network, while preserving every other kwarg
    (timeout, etc.) the route passes -- mirrors the real
    ``httpx.AsyncClient(base_url=..., transport=httpx.MockTransport(handler))``
    pattern the rest of this test suite already uses.
    """
    real_async_client = httpx.AsyncClient

    def _factory(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return real_async_client(*args, **kwargs)

    monkeypatch.setattr(docs_routes.httpx, "AsyncClient", _factory)


@pytest.mark.asyncio
async def test_fetch_jd_match_hits_the_right_engine_path_and_returns_json():
    calls: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, request.url.path))
        return httpx.Response(
            200,
            json={"application_id": "app-9", "score": 62, "matched": ["Python"], "missing": ["AWS"]},
        )

    orig = httpx.AsyncClient

    def _factory(*a, **k):
        k["transport"] = httpx.MockTransport(handler)
        return orig(*a, **k)

    import unittest.mock

    with unittest.mock.patch.object(docs_routes.httpx, "AsyncClient", _factory):
        data = await docs_routes._fetch_jd_match("app-9")

    assert calls == [("GET", "/api/documents/jd-match/app-9")]
    assert data == {"application_id": "app-9", "score": 62, "matched": ["Python"], "missing": ["AWS"]}


def test_jd_match_route_passes_engine_json_through(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/documents/jd-match/app-1"
        return httpx.Response(
            200,
            json={
                "application_id": "app-1",
                "score": 78,
                "matched": ["React", "Python", "AWS"],
                "missing": ["Kubernetes", "GraphQL"],
            },
        )

    _patch_transport(monkeypatch, handler)
    resp = _make_client().get("/api/applicant/documents/jd-match/app-1")
    assert resp.status_code == 200
    body = resp.json()
    assert body["score"] == 78
    assert body["matched"] == ["React", "Python", "AWS"]
    assert body["missing"] == ["Kubernetes", "GraphQL"]


def test_jd_match_route_requires_authentication(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover - must not run
        raise AssertionError("engine must not be called when unauthenticated")

    _patch_transport(monkeypatch, handler)
    resp = _make_client(authed=False).get("/api/applicant/documents/jd-match/app-1")
    assert resp.status_code in (401, 403)


def test_jd_match_route_translates_engine_404(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"detail": "No such application."})

    _patch_transport(monkeypatch, handler)
    resp = _make_client().get("/api/applicant/documents/jd-match/does-not-exist")
    assert resp.status_code == 404
    body = resp.json()
    assert body["error"] == "engine_error"
    assert body["engine_status"] == 404


def test_jd_match_route_translates_timeout_to_502(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("boom", request=request)

    _patch_transport(monkeypatch, handler)
    resp = _make_client().get("/api/applicant/documents/jd-match/app-1")
    assert resp.status_code == 502
    body = resp.json()
    assert body["engine_status"] is None
    assert "timed out" in body["message"].lower()


def test_jd_match_route_translates_connection_error_to_502(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    _patch_transport(monkeypatch, handler)
    resp = _make_client().get("/api/applicant/documents/jd-match/app-1")
    assert resp.status_code == 502


def test_fetch_jd_match_never_added_to_applicant_engine_client():
    """Hard requirement (concurrent-lock avoidance): the new engine call must
    live entirely inside this route module, never as a method on the shared
    ``ApplicantEngineClient`` (``src/applicant_engine.py`` is concurrently
    owned by another lane in this batch)."""
    from src.applicant_engine import ApplicantEngineClient

    assert not hasattr(ApplicantEngineClient, "jd_match")
    assert not hasattr(ApplicantEngineClient, "get_jd_match")


# ── documentLibrary.js: static-source assertions (no browser) ───────────────


def _materials_fn_source() -> str:
    src = _read(DOCLIB_JS)
    m = re.search(
        r"async function _loadApplicantMaterials\(appId, results\) \{(.*?)\n    \}\n",
        src,
        re.S,
    )
    assert m, "expected to find _loadApplicantMaterials()"
    return m.group(1)


def _jd_match_fn_source() -> str:
    src = _read(DOCLIB_JS)
    m = re.search(
        r"async function _loadJdMatch\(appId, container\) \{(.*?)\n    \}\n",
        src,
        re.S,
    )
    assert m, "expected to find _loadJdMatch()"
    return m.group(1)


def test_jd_match_helper_fetches_the_dedicated_proxy_endpoint():
    fn = _jd_match_fn_source()
    assert "${_APPLICANT_BASE}/jd-match/" in fn
    assert "encodeURIComponent(appId)" in fn


def test_jd_match_helper_never_blocks_or_toasts_on_failure():
    """Advisory-only: a failed/slow lookup must degrade silently (no
    uiModule.showError call), never block rendering of the materials list."""
    fn = _jd_match_fn_source()
    assert "showError" not in fn
    assert "if (!res.ok) return;" in fn


def test_jd_match_helper_renders_score_matched_and_missing():
    fn = _jd_match_fn_source()
    assert "Match score:" in fn
    assert "you cover" in fn
    assert "consider adding:" in fn
    # Capped to a readable handful, mirroring the engine's own ~12-item cap.
    assert "matched.slice(0, 6)" in fn
    assert "missing.slice(0, 6)" in fn


def test_jd_match_score_chip_reuses_the_existing_gate_badge_pill_styling():
    """No new visual system: the score chip must reuse the SAME pill shape
    (border-radius:10px + border:1px solid var(--border)) the "All approved" /
    "Needs review" gate badge above it already uses in this same function."""
    materials_fn = _materials_fn_source()
    gate_badge_style = "border-radius:10px;border:1px solid var(--border)"
    assert gate_badge_style in materials_fn

    jdmatch_fn = _jd_match_fn_source()
    assert gate_badge_style in jdmatch_fn


def test_jd_match_is_wired_into_the_materials_view_in_a_fixed_slot():
    """The line must live in a DOM slot created synchronously (right after the
    header) so the async fetch fills in *in place* rather than appending after
    the material cards once it eventually resolves — otherwise the score line
    would jump to the bottom of a populated materials list."""
    fn = _materials_fn_source()
    assert "results.appendChild(head);" in fn
    slot_idx = fn.index("jdMatchSlot")
    head_idx = fn.index("results.appendChild(head);")
    list_idx = fn.index("results.appendChild(list);") if "results.appendChild(list);" in fn else len(fn)
    assert head_idx < slot_idx < list_idx, (
        "expected the jd-match slot to be created between the header and the "
        "material-card list so it renders in the right visual position"
    )
    assert "_loadJdMatch(appId, jdMatchSlot)" in fn


def test_jd_match_only_fetched_when_there_are_materials():
    """No point (and no application-scoped signal) fetching a match score for
    an application with zero generated materials yet."""
    fn = _materials_fn_source()
    assert "if (items.length) _loadJdMatch(appId, jdMatchSlot);" in fn
