"""Hermetic tests for the workspace Memory/Profile proxy.

`routes/applicant_memory_routes.py` forwards the Brain modal's "Profile" tab to
the application engine's attribute-cloud + conversion-learning + criteria
endpoints. These tests mount only that router on a bare FastAPI app and serve the
engine with an ``httpx.MockTransport`` (zero network), so we exercise:

* the workspace -> engine URL/method/body mapping for every endpoint;
* campaign resolution (explicit id wins; otherwise the engine's first campaign);
* graceful degradation when the engine is down (``/status`` reports not-ready);
* error translation — the engine's 409 (confirm) / 422 (sensitive) / timeout are
  surfaced as clean HTTP statuses for the UI.

Auth is satisfied by a tiny middleware that sets ``request.state.current_user``
so ``require_user`` / ``require_privilege`` pass without a real AuthManager
(privileges fail-open for a resolved user, matching the rest of the Brain modal).
"""

import httpx
import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

import routes.applicant_memory_routes as memmod
from routes.applicant_memory_routes import setup_applicant_memory_routes
from src.applicant_engine import ApplicantEngineClient


def _make_client(handler, *, user="tester"):
    """Mount the router with the engine served by ``handler`` (a MockTransport fn).

    Monkeypatches the module's ``ApplicantEngineClient`` to a subclass that always
    injects the mock transport, so the route handlers' internal ``ApplicantEngineClient()``
    construction stays hermetic.
    """
    transport = httpx.MockTransport(handler)

    class _MockedClient(ApplicantEngineClient):
        def __init__(self, *a, **k):
            k["transport"] = transport
            k.setdefault("base_url", "http://api:8000")
            super().__init__(*a, **k)

    memmod.ApplicantEngineClient = _MockedClient

    app = FastAPI()

    @app.middleware("http")
    async def _inject_user(request: Request, call_next):
        request.state.current_user = user
        return await call_next(request)

    app.include_router(setup_applicant_memory_routes())
    return TestClient(app)


@pytest.fixture(autouse=True)
def _restore_client():
    original = memmod.ApplicantEngineClient
    yield
    memmod.ApplicantEngineClient = original


# A default campaign listing so resolution finds "camp-1" unless overridden.
def _route(request: httpx.Request, routes: dict):
    key = (request.method, request.url.path)
    if key in routes:
        return routes[key](request)
    # default campaign list for resolution
    if request.url.path == "/api/campaigns" and request.method == "GET":
        return httpx.Response(200, json=[{"id": "camp-1", "name": "Default"}])
    if request.url.path == "/healthz":
        return httpx.Response(200, json={"ok": True})
    return httpx.Response(404, json={"detail": f"unrouted {key}"})


# ---------------------------------------------------------------------------
# status / activation
# ---------------------------------------------------------------------------


def test_status_ready_reports_campaign_and_counts():
    def handler(request):
        return _route(request, {
            ("GET", "/api/attributes/camp-1"): lambda r: httpx.Response(
                200, json={"campaign_id": "camp-1", "items": [{"id": "a1"}, {"id": "a2"}]}
            ),
            ("GET", "/api/conversion/camp-1/engine"): lambda r: httpx.Response(
                200, json={"campaign_id": "camp-1", "engine": "latex"}
            ),
        })

    client = _make_client(handler)
    resp = client.get("/api/applicant/memory/status")
    assert resp.status_code == 200
    body = resp.json()
    assert body["ready"] is True
    assert body["engine_available"] is True
    assert body["campaign_id"] == "camp-1"
    assert body["attribute_count"] == 2
    assert body["learned_engine"] == "latex"


def test_status_not_ready_when_engine_down():
    def handler(request):
        # /healthz fails -> engine_available() False
        return httpx.Response(503, json={"detail": "down"})

    client = _make_client(handler)
    resp = client.get("/api/applicant/memory/status")
    assert resp.status_code == 200
    body = resp.json()
    assert body["ready"] is False
    assert body["engine_available"] is False
    assert body["campaign_id"] is None


def test_status_not_ready_when_no_campaign():
    def handler(request):
        if request.url.path == "/healthz":
            return httpx.Response(200, json={"ok": True})
        if request.url.path == "/api/campaigns":
            return httpx.Response(200, json=[])  # no campaigns yet
        return httpx.Response(404, json={"detail": "x"})

    client = _make_client(handler)
    resp = client.get("/api/applicant/memory/status")
    assert resp.status_code == 200
    body = resp.json()
    assert body["ready"] is False
    assert body["engine_available"] is True
    assert body["campaign_id"] is None


# ---------------------------------------------------------------------------
# attribute cloud
# ---------------------------------------------------------------------------


def test_list_attributes_resolves_first_campaign():
    seen = {}

    def handler(request):
        if request.url.path == "/api/attributes/camp-1" and request.method == "GET":
            seen["path"] = request.url.path
            return httpx.Response(200, json={"campaign_id": "camp-1", "items": [{"id": "a1"}]})
        return _route(request, {})

    client = _make_client(handler)
    resp = client.get("/api/applicant/memory/attributes")
    assert resp.status_code == 200
    assert seen["path"] == "/api/attributes/camp-1"
    assert resp.json()["items"] == [{"id": "a1"}]


def test_list_attributes_honours_explicit_campaign():
    seen = {}

    def handler(request):
        if request.url.path == "/api/attributes/camp-X" and request.method == "GET":
            seen["hit"] = True
            return httpx.Response(200, json={"campaign_id": "camp-X", "items": []})
        return httpx.Response(500, json={"detail": "should not resolve via list"})

    client = _make_client(handler)
    resp = client.get("/api/applicant/memory/attributes", params={"campaign_id": "camp-X"})
    assert resp.status_code == 200
    assert seen.get("hit") is True


def test_add_attribute_maps_body_to_engine():
    captured = {}

    def handler(request):
        if request.url.path == "/api/attributes" and request.method == "POST":
            captured["body"] = request.content.decode()
            return httpx.Response(201, json={"id": "a9", "name": "Phone", "value": "+1"})
        return _route(request, {})

    client = _make_client(handler)
    resp = client.post(
        "/api/applicant/memory/attributes",
        json={"name": "Phone", "value": "+1", "is_sensitive": False},
    )
    assert resp.status_code == 200
    assert resp.json()["id"] == "a9"
    assert '"campaign_id"' in captured["body"] and "camp-1" in captured["body"]
    assert '"Phone"' in captured["body"]


def test_add_attribute_forwards_confirm_409():
    def handler(request):
        if request.url.path == "/api/attributes" and request.method == "POST":
            return httpx.Response(409, json={"detail": "confirmation required"})
        return _route(request, {})

    client = _make_client(handler)
    resp = client.post(
        "/api/applicant/memory/attributes", json={"name": "Name", "value": "Kev"}
    )
    assert resp.status_code == 409
    assert "confirmation" in resp.json()["detail"]


def test_add_attribute_forwards_sensitive_422():
    def handler(request):
        if request.url.path == "/api/attributes" and request.method == "POST":
            return httpx.Response(422, json={"detail": "sensitive field"})
        return _route(request, {})

    client = _make_client(handler)
    resp = client.post(
        "/api/applicant/memory/attributes",
        json={"name": "Gender", "value": "x", "is_sensitive": True},
    )
    assert resp.status_code == 422


def test_ai_add_attribute():
    def handler(request):
        if request.url.path == "/api/attributes/ai-add" and request.method == "POST":
            return httpx.Response(201, json={"id": "ai1", "name": "Skill", "value": "Go"})
        return _route(request, {})

    client = _make_client(handler)
    resp = client.post(
        "/api/applicant/memory/attributes/ai-add",
        json={"name": "Skill", "value": "Go", "confirm": True},
    )
    assert resp.status_code == 200
    assert resp.json()["id"] == "ai1"


def test_bind_attribute_maps_fields():
    captured = {}

    def handler(request):
        if request.url.path == "/api/attributes/bindings" and request.method == "POST":
            captured["body"] = request.content.decode()
            return httpx.Response(201, json={"id": "b1", "site_key": "greenhouse"})
        return _route(request, {})

    client = _make_client(handler)
    resp = client.post(
        "/api/applicant/memory/attributes/bind",
        json={"site_key": "greenhouse", "field_selector": "#phone", "attribute_id": "a1"},
    )
    assert resp.status_code == 200
    assert "greenhouse" in captured["body"] and "#phone" in captured["body"]


def test_acquire_missing():
    def handler(request):
        if request.url.path == "/api/attributes/acquire-missing" and request.method == "POST":
            return httpx.Response(201, json={"id": "m1", "name": "Visa", "value": "Yes", "resumed": True})
        return _route(request, {})

    client = _make_client(handler)
    resp = client.post(
        "/api/applicant/memory/attributes/acquire-missing",
        json={"name": "Visa", "value": "Yes"},
    )
    assert resp.status_code == 200
    assert resp.json()["resumed"] is True


# ---------------------------------------------------------------------------
# conversion learning
# ---------------------------------------------------------------------------


def test_learning_state():
    def handler(request):
        if request.url.path == "/api/conversion/camp-1/engine" and request.method == "GET":
            return httpx.Response(200, json={"campaign_id": "camp-1", "engine": "docx"})
        return _route(request, {})

    client = _make_client(handler)
    resp = client.get("/api/applicant/memory/learning")
    assert resp.status_code == 200
    assert resp.json()["engine"] == "docx"


def test_learning_preview_sends_source():
    captured = {}

    def handler(request):
        if request.url.path == "/api/conversion/camp-1/preview" and request.method == "POST":
            captured["body"] = request.content.decode()
            return httpx.Response(200, json={"campaign_id": "camp-1", "page_count": 2, "fidelity_ok": True})
        return _route(request, {})

    client = _make_client(handler)
    resp = client.post("/api/applicant/memory/learning/preview", json={"source": "\\documentclass{}"})
    assert resp.status_code == 200
    assert resp.json()["page_count"] == 2
    assert '"source"' in captured["body"]


def test_learning_accept_and_reject():
    hits = []

    def handler(request):
        if request.method == "POST" and request.url.path.startswith("/api/conversion/camp-1/"):
            hits.append(request.url.path)
            return httpx.Response(200, json={"campaign_id": "camp-1", "engine": "latex"})
        return _route(request, {})

    client = _make_client(handler)
    assert client.post("/api/applicant/memory/learning/accept").status_code == 200
    assert client.post("/api/applicant/memory/learning/reject").status_code == 200
    assert "/api/conversion/camp-1/accept" in hits
    assert "/api/conversion/camp-1/reject" in hits


# ---------------------------------------------------------------------------
# criteria (adjacent)
# ---------------------------------------------------------------------------


def test_get_criteria():
    def handler(request):
        if request.url.path == "/api/criteria/camp-1" and request.method == "GET":
            return httpx.Response(200, json={"campaign_id": "camp-1", "titles": ["SWE"]})
        return _route(request, {})

    client = _make_client(handler)
    resp = client.get("/api/applicant/memory/criteria")
    assert resp.status_code == 200
    assert resp.json()["titles"] == ["SWE"]


def test_edit_criteria_sends_changes_and_excludes_campaign_id():
    captured = {}

    def handler(request):
        if request.url.path == "/api/criteria/camp-1" and request.method == "PUT":
            captured["body"] = request.content.decode()
            return httpx.Response(200, json={"campaign_id": "camp-1", "titles": ["SRE"]})
        return _route(request, {})

    client = _make_client(handler)
    resp = client.put("/api/applicant/memory/criteria", json={"titles": ["SRE"], "confirm": True})
    assert resp.status_code == 200
    assert '"titles"' in captured["body"]
    # campaign_id is path-encoded on the engine, not part of the PUT body
    assert "campaign_id" not in captured["body"]


# ---------------------------------------------------------------------------
# error translation
# ---------------------------------------------------------------------------


def test_engine_timeout_becomes_503():
    def handler(request):
        if request.url.path == "/api/attributes/camp-1":
            raise httpx.ReadTimeout("slow", request=request)
        return _route(request, {})

    client = _make_client(handler)
    resp = client.get("/api/applicant/memory/attributes")
    assert resp.status_code == 503


def test_missing_campaign_is_409_on_write():
    def handler(request):
        if request.url.path == "/healthz":
            return httpx.Response(200, json={"ok": True})
        if request.url.path == "/api/campaigns":
            return httpx.Response(200, json=[])
        return httpx.Response(500, json={"detail": "x"})

    client = _make_client(handler)
    resp = client.post("/api/applicant/memory/attributes", json={"name": "A", "value": "B"})
    assert resp.status_code == 409
