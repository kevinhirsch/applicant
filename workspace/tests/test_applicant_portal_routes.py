"""Hermetic tests for the Pending-Actions Portal proxy (CRIT-portal).

Mounts only ``routes/applicant_portal_routes.py`` on a bare FastAPI app with a
tiny middleware that authenticates the request (the real global auth gate lives
in ``app.py`` and is out of scope here). The engine is faked two ways:

* a scripted ``FakeEngine`` patched in for ``ApplicantEngineClient`` (covers the
  aggregation, soft-degrade, and resolve/acquire happy + error paths), and
* a real :class:`ApplicantEngineClient` over an ``httpx.MockTransport`` proving
  the exact engine paths are hit and that a typed ``EngineError`` (e.g. a 409
  confirm gate) is forwarded with its status.

Zero network either way.
"""

from __future__ import annotations

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import routes.applicant_portal_routes as mod
from routes.applicant_portal_routes import setup_applicant_portal_routes
from src.applicant_engine import ApplicantEngineClient, EngineError


# --- test app with a stand-in auth middleware -------------------------------


def _make_app(authed: bool = True) -> FastAPI:
    app = FastAPI()

    @app.middleware("http")
    async def _auth(request, call_next):
        request.state.current_user = "tester" if authed else None
        return await call_next(request)

    app.include_router(setup_applicant_portal_routes())
    return app


# --- a scripted fake engine -------------------------------------------------


class FakeEngine:
    """Stands in for ApplicantEngineClient as an async context manager."""

    calls: list = []
    campaigns: list = []
    pending: dict = {}            # campaign_id -> engine pending payload
    onboarding: dict = {}         # campaign_id -> engine onboarding state
    raises: dict = {}             # key -> EngineError
    acquire_response: dict = {"saved": True}

    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return None

    async def list_campaigns(self):
        FakeEngine.calls.append("list_campaigns")
        if "list_campaigns" in FakeEngine.raises:
            raise FakeEngine.raises["list_campaigns"]
        return FakeEngine.campaigns

    async def list_pending_actions(self, cid):
        FakeEngine.calls.append(("list_pending_actions", cid))
        if ("list_pending_actions", cid) in FakeEngine.raises:
            raise FakeEngine.raises[("list_pending_actions", cid)]
        return FakeEngine.pending.get(cid, {"campaign_id": cid, "count": 0, "items": []})

    async def resolve_pending_action(self, aid, body=None):
        FakeEngine.calls.append(("resolve_pending_action", aid, body))
        if ("resolve_pending_action", aid) in FakeEngine.raises:
            raise FakeEngine.raises[("resolve_pending_action", aid)]
        return None

    async def acquire_missing_attribute(self, payload):
        FakeEngine.calls.append(("acquire_missing_attribute", payload))
        if "acquire_missing_attribute" in FakeEngine.raises:
            raise FakeEngine.raises["acquire_missing_attribute"]
        return FakeEngine.acquire_response

    async def onboarding_state(self, cid):
        FakeEngine.calls.append(("onboarding_state", cid))
        if ("onboarding_state", cid) in FakeEngine.raises:
            raise FakeEngine.raises[("onboarding_state", cid)]
        return FakeEngine.onboarding.get(cid, {"complete": True, "missing_sections": []})

    async def list_notifications(self):
        FakeEngine.calls.append("list_notifications")
        if "list_notifications" in FakeEngine.raises:
            raise FakeEngine.raises["list_notifications"]
        return FakeEngine.notifications

    async def dismiss_notification(self, nid):
        FakeEngine.calls.append(("dismiss_notification", nid))
        if ("dismiss_notification", nid) in FakeEngine.raises:
            raise FakeEngine.raises[("dismiss_notification", nid)]
        return None

    async def resolve_pending_actions_bulk(self, cid, action_ids):
        FakeEngine.calls.append(("resolve_pending_actions_bulk", cid, list(action_ids)))
        if "resolve_pending_actions_bulk" in FakeEngine.raises:
            raise FakeEngine.raises["resolve_pending_actions_bulk"]
        return {"resolved": list(action_ids), "skipped": [], "resolved_count": len(action_ids)}

    async def snooze_pending_action(self, aid, body=None):
        FakeEngine.calls.append(("snooze_pending_action", aid, body))
        if ("snooze_pending_action", aid) in FakeEngine.raises:
            raise FakeEngine.raises[("snooze_pending_action", aid)]
        return {"action_id": aid, "snoozed_until": "2026-07-01T09:00:00+00:00"}

    setup: dict = {}

    async def setup_status(self):
        FakeEngine.calls.append("setup_status")
        if "setup_status" in FakeEngine.raises:
            raise FakeEngine.raises["setup_status"]
        return FakeEngine.setup


@pytest.fixture(autouse=True)
def _reset_fake():
    FakeEngine.calls = []
    FakeEngine.campaigns = []
    FakeEngine.pending = {}
    # Default to a fully-complete intake so the aggregation/resolve tests don't
    # see the synthetic "finish your profile" gap row injected.
    FakeEngine.onboarding = {}
    # Default: apply-readiness gate OPEN (search running) so the aggregation /
    # resolve tests don't see the synthetic "finish setup" gap row injected.
    FakeEngine.setup = {
        "apply_ready": True,
        "apply_missing": [],
        "automated_work_allowed": True,
    }
    FakeEngine.raises = {}
    FakeEngine.acquire_response = {"saved": True}
    FakeEngine.notifications = {"count": 0, "items": []}
    yield


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(mod, "ApplicantEngineClient", FakeEngine)
    return TestClient(_make_app())


# --- auth -------------------------------------------------------------------


def test_unauthenticated_is_rejected(monkeypatch):
    monkeypatch.setattr(mod, "ApplicantEngineClient", FakeEngine)
    c = TestClient(_make_app(authed=False))
    # No current_user and the TestClient host ("testclient") is not loopback, so
    # require_user rejects — a middleware misconfig can't open the portal up.
    r = c.get("/api/applicant/portal/pending")
    assert r.status_code == 401


# --- aggregation ------------------------------------------------------------


def test_pending_aggregates_across_campaigns(client):
    FakeEngine.campaigns = [
        {"id": "c1", "name": "Backend"},
        {"id": "c2", "name": "Platform"},
    ]
    FakeEngine.pending = {
        "c1": {"items": [
            {"id": "a1", "kind": "material_review", "title": "Cover letter", "application_id": "app1"},
        ]},
        "c2": {"items": [
            {"id": "a2", "kind": "missing_attr", "title": "Need a detail", "payload": {"attribute_name": "phone"}},
            {"id": "a3", "kind": "agent_question", "title": "Which city?"},
        ]},
    }
    r = client.get("/api/applicant/portal/pending")
    assert r.status_code == 200
    body = r.json()
    assert body["engine_available"] is True
    assert body["count"] == 3
    ids = {it["id"] for it in body["items"]}
    assert ids == {"a1", "a2", "a3"}
    # Campaign context is attached per item.
    by_id = {it["id"]: it for it in body["items"]}
    assert by_id["a1"]["campaign_id"] == "c1"
    assert by_id["a1"]["campaign_name"] == "Backend"
    assert by_id["a2"]["campaign_name"] == "Platform"


def test_pending_soft_degrades_when_engine_down(client):
    FakeEngine.raises["list_campaigns"] = EngineError("down", is_timeout=True)
    r = client.get("/api/applicant/portal/pending")
    assert r.status_code == 200
    assert r.json() == {"engine_available": False, "count": 0, "items": []}


# --- HONESTY: a 409 setup gate is NOT offline -------------------------------
#
# A pre-campaign / automated-work setup gate (409, also 401/403/422) on the
# campaigns read must surface as GATED (gated:true + the engine's message,
# engine_available:true) so the Portal shows the honest setup prompt instead of
# "not connected yet". A transport failure (status None) stays offline.

_PORTAL_GATE_MSG = (
    "Automated work is blocked until onboarding is complete and the LLM + "
    "notification channels are configured."
)


def test_pending_409_gate_is_not_offline(client):
    FakeEngine.raises["list_campaigns"] = EngineError("gated", status=409, detail=_PORTAL_GATE_MSG)
    r = client.get("/api/applicant/portal/pending")
    assert r.status_code == 200
    body = r.json()
    assert body["gated"] is True
    assert body["engine_available"] is True
    assert body["message"] == _PORTAL_GATE_MSG
    assert body["items"] == []


def test_pending_transport_error_is_offline(client):
    FakeEngine.raises["list_campaigns"] = EngineError("conn refused", status=None)
    r = client.get("/api/applicant/portal/pending")
    assert r.status_code == 200
    body = r.json()
    assert body["engine_available"] is False
    assert body.get("gated") is not True


def test_notifications_409_gate_is_not_offline(client):
    FakeEngine.raises["list_notifications"] = EngineError("gated", status=409, detail=_PORTAL_GATE_MSG)
    r = client.get("/api/applicant/portal/notifications")
    assert r.status_code == 200
    body = r.json()
    assert body["gated"] is True
    assert body["engine_available"] is True
    assert body["message"] == _PORTAL_GATE_MSG


def test_notifications_transport_error_is_offline(client):
    FakeEngine.raises["list_notifications"] = EngineError("down", status=None)
    r = client.get("/api/applicant/portal/notifications")
    assert r.status_code == 200
    assert r.json()["engine_available"] is False


def test_pending_skips_a_single_failing_campaign(client):
    FakeEngine.campaigns = [{"id": "c1", "name": "A"}, {"id": "c2", "name": "B"}]
    FakeEngine.pending = {"c1": {"items": [{"id": "a1", "kind": "error", "title": "snag"}]}}
    FakeEngine.raises[("list_pending_actions", "c2")] = EngineError("flaky")
    r = client.get("/api/applicant/portal/pending")
    assert r.status_code == 200
    body = r.json()
    assert body["count"] == 1
    assert body["items"][0]["id"] == "a1"


def test_pending_empty_when_no_campaigns(client):
    FakeEngine.campaigns = []
    r = client.get("/api/applicant/portal/pending")
    assert r.status_code == 200
    body = r.json()
    assert body["engine_available"] is True
    assert body["count"] == 0
    assert body["items"] == []
    assert _gap_item(body) is None


# --- onboarding gap row -----------------------------------------------------


def _gap_item(body):
    for it in body["items"]:
        if it.get("kind") == "onboarding_incomplete":
            return it
    return None


def test_pending_includes_gap_when_gate_closed(client):
    # Product-honesty: while the apply-readiness gate is CLOSED the Portal surfaces
    # one synthetic row naming the SAME essentials the wizard-finish + chat report
    # (the server-truth apply_missing) — not a third, disagreeing list.
    FakeEngine.campaigns = [{"id": "c1", "name": "Backend"}]
    FakeEngine.setup = {
        "apply_ready": False,
        "automated_work_allowed": False,
        "apply_missing": ["salary floor", "a résumé"],
    }
    r = client.get("/api/applicant/portal/pending")
    assert r.status_code == 200
    body = r.json()
    gap = _gap_item(body)
    assert gap is not None
    assert gap["id"] == "onboarding-incomplete"
    assert gap["affordance"] == "complete"
    assert gap["campaign_id"] == "c1"
    assert gap["missing"] == ["salary floor", "a résumé"]
    # It sits at the top of the feed, and the honest gate is surfaced on the payload.
    assert body["items"][0]["id"] == "onboarding-incomplete"
    assert body["count"] == 1
    assert body["apply_ready"] is False
    assert body["automated_work_allowed"] is False
    assert body["apply_missing"] == ["salary floor", "a résumé"]


def test_gap_prepended_above_other_actions(client):
    FakeEngine.campaigns = [{"id": "c1", "name": "Backend"}]
    FakeEngine.pending = {
        "c1": {"items": [{"id": "a1", "kind": "agent_question", "title": "Which city?"}]}
    }
    FakeEngine.setup = {
        "apply_ready": False,
        "automated_work_allowed": False,
        "apply_missing": ["locations"],
    }
    r = client.get("/api/applicant/portal/pending")
    body = r.json()
    assert body["count"] == 2
    assert body["items"][0]["id"] == "onboarding-incomplete"
    assert body["items"][1]["id"] == "a1"
    assert _gap_item(body)["missing"] == ["locations"]


def test_pending_omits_gap_when_gate_open(client):
    # Gate open (search genuinely running) → no gap row, honest "active" signal.
    FakeEngine.campaigns = [{"id": "c1", "name": "Backend"}]
    FakeEngine.setup = {"apply_ready": True, "automated_work_allowed": True, "apply_missing": []}
    r = client.get("/api/applicant/portal/pending")
    body = r.json()
    assert _gap_item(body) is None
    assert body["count"] == 0
    assert body["automated_work_allowed"] is True


def test_pending_omits_gap_when_apply_missing_empty(client):
    # apply_ready False but nothing actually missing → no gap row (clears itself).
    FakeEngine.campaigns = [{"id": "c1", "name": "Backend"}]
    FakeEngine.setup = {"apply_ready": False, "automated_work_allowed": False, "apply_missing": []}
    r = client.get("/api/applicant/portal/pending")
    assert _gap_item(r.json()) is None


def test_gap_attaches_to_first_campaign(client):
    # The apply-readiness gate is a single global signal; the row attaches to the
    # owner's first campaign so its "Finish setup" jump lands somewhere real.
    FakeEngine.campaigns = [{"id": "c1", "name": "First"}, {"id": "c2", "name": "Second"}]
    FakeEngine.setup = {
        "apply_ready": False,
        "automated_work_allowed": False,
        "apply_missing": ["key skills"],
    }
    r = client.get("/api/applicant/portal/pending")
    gap = _gap_item(r.json())
    assert gap is not None
    assert gap["campaign_id"] == "c1"
    assert gap["campaign_name"] == "First"
    assert gap["missing"] == ["key skills"]


def test_gap_omitted_when_status_lookup_errors(client):
    # A setup-status error must not sink the feed — the gap row is simply omitted
    # (readiness unknown), the gate fields drop off, and normal items still land.
    FakeEngine.campaigns = [{"id": "c1", "name": "Backend"}]
    FakeEngine.pending = {"c1": {"items": [{"id": "a1", "kind": "agent_question"}]}}
    FakeEngine.raises["setup_status"] = EngineError("boom", status=500)
    r = client.get("/api/applicant/portal/pending")
    body = r.json()
    assert r.status_code == 200
    assert _gap_item(body) is None
    assert body["count"] == 1
    assert body["items"][0]["id"] == "a1"
    assert "apply_missing" not in body


def test_pending_no_gap_when_engine_down(client):
    # A fully-down engine returns the soft-degrade payload with no gap row.
    FakeEngine.raises["list_campaigns"] = EngineError("down", is_timeout=True)
    r = client.get("/api/applicant/portal/pending")
    assert r.json() == {"engine_available": False, "count": 0, "items": []}


# --- resolve ----------------------------------------------------------------


def _resolve_calls():
    return [c for c in FakeEngine.calls if isinstance(c, tuple) and c[0] == "resolve_pending_action"]


def test_resolve_action_ok(client):
    r = client.post("/api/applicant/portal/actions/a1/resolve")
    assert r.status_code == 200
    assert r.json() == {"resolved": True, "already_resolved": False, "action_id": "a1"}
    # Plain resolve (no JSON body) → forwarded with no body.
    assert any(c[1] == "a1" and c[2] is None for c in _resolve_calls())


def test_resolve_action_surfaces_already_resolved(client, monkeypatch):
    # DISC-6: the engine now returns a distinguishable body (rather than an
    # empty 204) when the action was already resolved -- the proxy must
    # forward that as an explicit ``already_resolved`` flag instead of
    # collapsing it back into the same "resolved": True shape as a fresh
    # resolve, which is exactly the silent no-op the ledger item calls out.
    async def _already_resolved(self, aid, body=None):
        FakeEngine.calls.append(("resolve_pending_action", aid, body))
        return {"action_id": aid, "status": "already_resolved"}

    monkeypatch.setattr(FakeEngine, "resolve_pending_action", _already_resolved)
    r = client.post("/api/applicant/portal/actions/a1/resolve")
    assert r.status_code == 200
    assert r.json() == {"resolved": False, "already_resolved": True, "action_id": "a1"}


def test_resolve_action_forwards_apply_body(client):
    # FR-FB-3: confirming a held integral change forwards {"apply": true} to the engine.
    r = client.post("/api/applicant/portal/actions/a1/resolve", json={"apply": True})
    assert r.status_code == 200
    assert any(c[1] == "a1" and c[2] == {"apply": True} for c in _resolve_calls())


def test_resolve_action_forwards_error(client):
    FakeEngine.raises[("resolve_pending_action", "missing")] = EngineError(
        "nope", status=404, detail="unknown"
    )
    r = client.post("/api/applicant/portal/actions/missing/resolve")
    assert r.status_code == 404
    assert r.json()["detail"] == "unknown"


def test_resolve_action_maps_unreachable_to_503(client):
    FakeEngine.raises[("resolve_pending_action", "a1")] = EngineError("conn refused")
    r = client.post("/api/applicant/portal/actions/a1/resolve")
    assert r.status_code == 503


# --- missing attribute ------------------------------------------------------


def test_missing_attribute_acquires_and_resolves(client):
    FakeEngine.campaigns = [{"id": "c1", "name": "A"}]
    r = client.post(
        "/api/applicant/portal/missing-attribute",
        json={"name": "phone", "value": "555-1212", "campaign_id": "c1", "action_id": "a2"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["resolved"] is True
    assert body["campaign_id"] == "c1"
    # The acquire payload carried the resolved campaign + value.
    acquire = [c for c in FakeEngine.calls if isinstance(c, tuple) and c[0] == "acquire_missing_attribute"]
    assert acquire and acquire[0][1]["name"] == "phone"
    assert acquire[0][1]["value"] == "555-1212"
    assert any(c[1] == "a2" for c in _resolve_calls())


def test_missing_attribute_resolves_campaign_when_omitted(client):
    FakeEngine.campaigns = [{"id": "auto1", "name": "First"}]
    r = client.post(
        "/api/applicant/portal/missing-attribute",
        json={"name": "phone", "value": "x"},
    )
    assert r.status_code == 200
    assert r.json()["campaign_id"] == "auto1"


def test_missing_attribute_requires_name_and_value(client):
    assert client.post(
        "/api/applicant/portal/missing-attribute", json={"name": " ", "value": "x"}
    ).status_code == 400
    assert client.post(
        "/api/applicant/portal/missing-attribute", json={"name": "phone", "value": " "}
    ).status_code == 400


def test_missing_attribute_forwards_confirm_gate(client):
    FakeEngine.campaigns = [{"id": "c1", "name": "A"}]
    FakeEngine.raises["acquire_missing_attribute"] = EngineError(
        "confirm", status=409, detail="needs confirm"
    )
    r = client.post(
        "/api/applicant/portal/missing-attribute",
        json={"name": "phone", "value": "x", "campaign_id": "c1"},
    )
    assert r.status_code == 409
    assert r.json()["detail"] == "needs confirm"


def test_missing_attribute_409_when_no_campaign(client):
    FakeEngine.campaigns = []
    r = client.post(
        "/api/applicant/portal/missing-attribute", json={"name": "phone", "value": "x"}
    )
    assert r.status_code == 409


def test_missing_attribute_survives_resolve_failure(client):
    # The detail saved; only the row-clear failed → still 200, resolved=False.
    FakeEngine.campaigns = [{"id": "c1", "name": "A"}]
    FakeEngine.raises[("resolve_pending_action", "a2")] = EngineError("flaky", status=500)
    r = client.post(
        "/api/applicant/portal/missing-attribute",
        json={"name": "phone", "value": "x", "campaign_id": "c1", "action_id": "a2"},
    )
    assert r.status_code == 200
    assert r.json()["resolved"] is False


# --- notification center ----------------------------------------------------


def test_notifications_list_proxies(client):
    FakeEngine.notifications = {
        "count": 2,
        "items": [
            {"id": "inapp-2", "title": "Digest ready", "kind": "digest"},
            {"id": "inapp-1", "title": "Heads up", "kind": "error"},
        ],
    }
    r = client.get("/api/applicant/portal/notifications")
    assert r.status_code == 200
    body = r.json()
    assert body["engine_available"] is True
    assert body["count"] == 2
    assert {i["id"] for i in body["items"]} == {"inapp-1", "inapp-2"}
    assert "list_notifications" in FakeEngine.calls


def test_notifications_soft_degrade_when_engine_down(client):
    FakeEngine.raises["list_notifications"] = EngineError("down")
    r = client.get("/api/applicant/portal/notifications")
    assert r.status_code == 200
    assert r.json() == {"engine_available": False, "count": 0, "items": []}


def test_notification_dismiss_ok(client):
    r = client.post("/api/applicant/portal/notifications/inapp-1/seen")
    assert r.status_code == 200
    assert r.json() == {"dismissed": True, "id": "inapp-1"}
    assert ("dismiss_notification", "inapp-1") in FakeEngine.calls


def test_notification_dismiss_404_is_idempotent_success(client):
    # An already-cleared notification (engine 404) is treated as dismissed so the
    # UI can drop the row without erroring.
    FakeEngine.raises[("dismiss_notification", "gone")] = EngineError(
        "missing", status=404, detail="no"
    )
    r = client.post("/api/applicant/portal/notifications/gone/seen")
    assert r.status_code == 200
    assert r.json() == {"dismissed": True, "id": "gone"}


def test_notification_dismiss_scrubs_5xx_to_502(client):
    # Engine 5xx is scrubbed to 502 Bad Gateway; detail must not leak to the browser.
    FakeEngine.raises[("dismiss_notification", "x")] = EngineError("boom", status=500, detail="bad")
    r = client.post("/api/applicant/portal/notifications/x/seen")
    assert r.status_code == 502
    body = r.json()
    assert "detail" not in body or body.get("detail") != "bad"


# --- bulk resolve ("approve all N") -----------------------------------------


def test_bulk_resolve_proxies(client):
    r = client.post(
        "/api/applicant/portal/actions/resolve-bulk",
        json={"campaign_id": "c1", "action_ids": ["a1", "a2"]},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["resolved_count"] == 2
    assert set(body["resolved"]) == {"a1", "a2"}
    assert ("resolve_pending_actions_bulk", "c1", ["a1", "a2"]) in FakeEngine.calls


def test_bulk_resolve_requires_campaign(client):
    r = client.post(
        "/api/applicant/portal/actions/resolve-bulk",
        json={"campaign_id": " ", "action_ids": ["a1"]},
    )
    assert r.status_code == 400


def test_bulk_resolve_empty_is_noop(client):
    r = client.post(
        "/api/applicant/portal/actions/resolve-bulk",
        json={"campaign_id": "c1", "action_ids": []},
    )
    assert r.status_code == 200
    assert r.json()["resolved_count"] == 0
    # No engine round-trip for an empty batch.
    assert not any(
        isinstance(c, tuple) and c[0] == "resolve_pending_actions_bulk" for c in FakeEngine.calls
    )


def test_bulk_resolve_forwards_engine_error(client):
    FakeEngine.raises["resolve_pending_actions_bulk"] = EngineError("nope", status=409, detail="gate")
    r = client.post(
        "/api/applicant/portal/actions/resolve-bulk",
        json={"campaign_id": "c1", "action_ids": ["a1"]},
    )
    assert r.status_code == 409
    assert r.json()["detail"] == "gate"


# --- snooze ("remind me later") ---------------------------------------------


def test_snooze_proxies_default(client):
    r = client.post("/api/applicant/portal/actions/a1/snooze", json={})
    assert r.status_code == 200
    assert r.json()["snoozed_until"]
    assert ("snooze_pending_action", "a1", None) in FakeEngine.calls


def test_snooze_forwards_until_and_hours(client):
    r = client.post(
        "/api/applicant/portal/actions/a1/snooze", json={"until": "2026-07-01T09:00:00Z"}
    )
    assert r.status_code == 200
    sent = [c for c in FakeEngine.calls if isinstance(c, tuple) and c[0] == "snooze_pending_action"]
    assert sent and sent[0][2] == {"until": "2026-07-01T09:00:00Z"}


def test_snooze_forwards_404(client):
    FakeEngine.raises[("snooze_pending_action", "gone")] = EngineError(
        "missing", status=404, detail="gone"
    )
    r = client.post("/api/applicant/portal/actions/gone/snooze", json={})
    assert r.status_code == 404


# --- exact engine paths via a real client over MockTransport ----------------


def _mock_transport_app(handler):
    class TransportEngine(ApplicantEngineClient):
        def __init__(self, *a, **k):
            super().__init__(base_url="http://api:8000", transport=httpx.MockTransport(handler))

    app = FastAPI()

    @app.middleware("http")
    async def _auth(request, call_next):
        request.state.current_user = "tester"
        return await call_next(request)

    app.include_router(setup_applicant_portal_routes())
    return app, TransportEngine


def test_resolve_hits_exact_engine_path(monkeypatch):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["method"] = request.method
        return httpx.Response(204)

    app, engine_cls = _mock_transport_app(handler)
    monkeypatch.setattr(mod, "ApplicantEngineClient", engine_cls)
    c = TestClient(app)

    r = c.post("/api/applicant/portal/actions/a9/resolve")
    assert r.status_code == 200
    assert seen["path"] == "/api/pending-actions/a9/resolve"
    assert seen["method"] == "POST"


def test_bulk_and_snooze_hit_exact_engine_paths(monkeypatch):
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.method, request.url.path))
        if request.url.path.endswith("/resolve-bulk"):
            return httpx.Response(200, json={"resolved": ["a1"], "skipped": [], "resolved_count": 1})
        if request.url.path.endswith("/snooze"):
            return httpx.Response(200, json={"action_id": "a1", "snoozed_until": "2026-07-01T09:00:00+00:00"})
        return httpx.Response(404, json={"detail": "unexpected"})

    app, engine_cls = _mock_transport_app(handler)
    monkeypatch.setattr(mod, "ApplicantEngineClient", engine_cls)
    c = TestClient(app)

    rb = c.post(
        "/api/applicant/portal/actions/resolve-bulk",
        json={"campaign_id": "c1", "action_ids": ["a1"]},
    )
    assert rb.status_code == 200
    rs = c.post("/api/applicant/portal/actions/a1/snooze", json={})
    assert rs.status_code == 200
    assert ("POST", "/api/pending-actions/c1/resolve-bulk") in seen
    assert ("POST", "/api/pending-actions/a1/snooze") in seen


def test_missing_attribute_hits_exact_engine_path(monkeypatch):
    paths = []

    def handler(request: httpx.Request) -> httpx.Response:
        paths.append((request.method, request.url.path))
        if request.url.path == "/api/attributes/acquire-missing":
            return httpx.Response(200, json={"saved": True})
        if request.url.path == "/api/pending-actions/a2/resolve":
            return httpx.Response(204)
        return httpx.Response(404, json={"detail": "unexpected"})

    app, engine_cls = _mock_transport_app(handler)
    monkeypatch.setattr(mod, "ApplicantEngineClient", engine_cls)
    c = TestClient(app)

    r = c.post(
        "/api/applicant/portal/missing-attribute",
        json={"name": "phone", "value": "x", "campaign_id": "c1", "action_id": "a2"},
    )
    assert r.status_code == 200
    assert ("POST", "/api/attributes/acquire-missing") in paths
    assert ("POST", "/api/pending-actions/a2/resolve") in paths
