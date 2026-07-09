"""Hermetic tests for the Applicant SETUP/ONBOARDING proxy (applicant_setup_routes).

Zero network: the engine client is replaced with a fake async-context-manager so
every route is exercised without an engine. Covers the happy path (engine JSON
passed through), the typed-error translation (timeout -> 502, HTTP status passed
through), request-body + multipart forwarding, the auth gate, and the owner-scoped
config-privilege gate.
"""

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

import routes.applicant_setup_routes as setup_routes
from routes.applicant_setup_routes import setup_applicant_setup_routes
from src.applicant_engine import EngineError


class _FakeEngine:
    """Stand-in for ApplicantEngineClient. Records (method, args), returns a
    canned result or raises a canned EngineError. Async context manager."""

    last_call = None

    def __init__(self, *, result=None, error: EngineError | None = None):
        self._result = result
        self._error = error

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def _dispatch(self, name, *args):
        type(self).last_call = (name, args)
        if self._error is not None:
            raise self._error
        return self._result

    # Methods the proxy calls, all routed through _dispatch.
    async def setup_status(self):
        return await self._dispatch("setup_status")

    async def setup_advance(self, step):
        return await self._dispatch("setup_advance", step)

    async def setup_configure_llm(self, body):
        return await self._dispatch("setup_configure_llm", body)

    async def setup_configure_llm_from_endpoint(self, body):
        return await self._dispatch("setup_configure_llm_from_endpoint", body)

    async def setup_get_tiers(self):
        return await self._dispatch("setup_get_tiers")

    async def setup_set_tiers(self, body):
        return await self._dispatch("setup_set_tiers", body)

    async def list_model_endpoints(self, refresh=False):
        return await self._dispatch("list_model_endpoints", refresh)

    async def add_model_endpoint(self, data):
        return await self._dispatch("add_model_endpoint", data)

    async def test_model_endpoint(self, data):
        return await self._dispatch("test_model_endpoint", data)

    async def model_endpoint_models(self, endpoint_id, refresh=False):
        return await self._dispatch("model_endpoint_models", endpoint_id, refresh)

    async def setup_get_channels(self):
        return await self._dispatch("setup_get_channels")

    async def setup_configure_channels(self, body):
        return await self._dispatch("setup_configure_channels", body)

    async def setup_test_channels(self, channel=""):
        return await self._dispatch("setup_test_channels", channel)

    async def setup_get_quiet_hours(self):
        return await self._dispatch("setup_get_quiet_hours")

    async def setup_configure_quiet_hours(self, body):
        return await self._dispatch("setup_configure_quiet_hours", body)

    async def setup_get_sandbox_connection(self):
        return await self._dispatch("setup_get_sandbox_connection")

    async def setup_configure_sandbox_connection(self, body):
        return await self._dispatch("setup_configure_sandbox_connection", body)

    async def list_fonts(self):
        return await self._dispatch("list_fonts")

    async def detect_fonts(self, files):
        return await self._dispatch("detect_fonts", files)

    async def install_font(self, files, data):
        return await self._dispatch("install_font", files, data)

    async def list_campaigns(self):
        return await self._dispatch("list_campaigns")

    async def create_campaign(self, name):
        return await self._dispatch("create_campaign", name)

    async def onboarding_state(self, campaign_id):
        return await self._dispatch("onboarding_state", campaign_id)

    async def onboarding_section(self, campaign_id, body):
        return await self._dispatch("onboarding_section", campaign_id, body)

    async def onboarding_base_resume(self, campaign_id, files):
        return await self._dispatch("onboarding_base_resume", campaign_id, files)

    async def onboarding_confirm_conflict(self, campaign_id, body):
        return await self._dispatch("onboarding_confirm_conflict", campaign_id, body)

    async def onboarding_complete(self, campaign_id):
        return await self._dispatch("onboarding_complete", campaign_id)

    async def conversion_engine(self, campaign_id):
        return await self._dispatch("conversion_engine", campaign_id)

    async def conversion_preview(self, campaign_id, source):
        return await self._dispatch("conversion_preview", campaign_id, source)

    async def conversion_accept(self, campaign_id):
        return await self._dispatch("conversion_accept", campaign_id)

    async def conversion_reject(self, campaign_id):
        return await self._dispatch("conversion_reject", campaign_id)


def _patch_engine(monkeypatch, *, result=None, error: EngineError | None = None):
    _FakeEngine.last_call = None
    monkeypatch.setattr(
        setup_routes,
        "ApplicantEngineClient",
        lambda *a, **k: _FakeEngine(result=result, error=error),
    )


def _make_client(*, authed: bool = True):
    app = FastAPI()
    if authed:
        @app.middleware("http")
        async def _set_user(request: Request, call_next):
            request.state.current_user = "tester"
            return await call_next(request)
    app.include_router(setup_applicant_setup_routes())
    return TestClient(app, raise_server_exceptions=True)


# ── happy path ────────────────────────────────────────────────────────────


def test_status_passes_engine_json_through(monkeypatch):
    payload = {"llm_configured": False, "channels_configured": False, "onboarding_complete": False}
    _patch_engine(monkeypatch, result=payload)
    resp = _make_client().get("/api/applicant/setup/status")
    assert resp.status_code == 200
    assert resp.json() == payload
    assert _FakeEngine.last_call == ("setup_status", ())


def test_advance_forwards_step(monkeypatch):
    _patch_engine(monkeypatch, result={"current_step": "channels"})
    resp = _make_client().post("/api/applicant/setup/advance/llm")
    assert resp.status_code == 200
    assert _FakeEngine.last_call == ("setup_advance", ("llm",))


def test_configure_llm_forwards_body(monkeypatch):
    _patch_engine(monkeypatch, result=None)
    body = {"provider": "openai", "base_url": "u", "api_key": "k", "model": "m", "context_window": 8192}
    resp = _make_client().post("/api/applicant/setup/llm", json=body)
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}
    name, args = _FakeEngine.last_call
    assert name == "setup_configure_llm"
    assert args[0]["model"] == "m"


def test_get_tiers_passes_through(monkeypatch):
    payload = {"tiers": [{"provider": "openrouter", "model": "deepseek/deepseek-v4-flash", "api_key_ref": "llm.tier1"}]}
    _patch_engine(monkeypatch, result=payload)
    resp = _make_client().get("/api/applicant/setup/llm/tiers")
    assert resp.status_code == 200
    body = resp.json()
    assert body["engine_available"] is True
    assert body["tiers"][0]["model"] == "deepseek/deepseek-v4-flash"
    assert "api_key" not in body["tiers"][0]  # secret omitted by the engine
    assert _FakeEngine.last_call == ("setup_get_tiers", ())


def test_get_tiers_soft_degrades(monkeypatch):
    _patch_engine(monkeypatch, error=EngineError("down"))
    resp = _make_client().get("/api/applicant/setup/llm/tiers")
    assert resp.status_code == 200
    assert resp.json() == {"tiers": [], "engine_available": False}


def test_set_tiers_forwards_ladder(monkeypatch):
    _patch_engine(monkeypatch, result=None)
    body = {"tiers": [
        {"provider": "openrouter", "base_url": "https://openrouter.ai/api/v1", "model": "deepseek/deepseek-v4-flash", "api_key": "sk", "context_window": 128000},
        {"provider": "openrouter", "base_url": "https://openrouter.ai/api/v1", "model": "deepseek/deepseek-v4-pro", "api_key_ref": "llm.tier2", "context_window": 128000},
    ]}
    resp = _make_client().put("/api/applicant/setup/llm/tiers", json=body)
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}
    name, args = _FakeEngine.last_call
    assert name == "setup_set_tiers"
    assert len(args[0]["tiers"]) == 2
    assert args[0]["tiers"][1]["api_key_ref"] == "llm.tier2"  # ref carried through


def test_set_tiers_rejects_empty(monkeypatch):
    _patch_engine(monkeypatch, result=None)
    resp = _make_client().put("/api/applicant/setup/llm/tiers", json={"tiers": []})
    assert resp.status_code == 400


def test_set_tiers_forwards_connection_id_by_reference(monkeypatch):
    """DISC-4: a tier bound to a saved connection forwards only the connection's
    id (a reference) — never a key — to the engine."""
    _patch_engine(monkeypatch, result=None)
    body = {"tiers": [
        {"provider": "openai", "base_url": "https://conn.test/v1", "model": "m1", "connection_id": "conn-123"},
    ]}
    resp = _make_client().put("/api/applicant/setup/llm/tiers", json=body)
    assert resp.status_code == 200
    name, args = _FakeEngine.last_call
    assert name == "setup_set_tiers"
    tier = args[0]["tiers"][0]
    assert tier["connection_id"] == "conn-123"  # reference carried through
    assert not tier.get("api_key")  # no plaintext key travels through the proxy


def test_llm_from_endpoint_forwards_body(monkeypatch):
    _patch_engine(monkeypatch, result=None)
    resp = _make_client().post(
        "/api/applicant/setup/llm/from-endpoint", json={"endpoint_id": "e1", "model": "m2"}
    )
    assert resp.status_code == 200
    name, args = _FakeEngine.last_call
    assert name == "setup_configure_llm_from_endpoint"
    assert args[0] == {"endpoint_id": "e1", "model": "m2"}


def test_add_model_endpoint_forwards_form(monkeypatch):
    _patch_engine(monkeypatch, result={"id": "e1", "models": ["a", "b"]})
    resp = _make_client().post(
        "/api/applicant/setup/model-endpoints",
        data={"base_url": "http://x", "api_key": "k", "name": "n", "model_type": "llm"},
    )
    assert resp.status_code == 200
    assert resp.json()["id"] == "e1"
    name, args = _FakeEngine.last_call
    assert name == "add_model_endpoint"
    assert args[0]["base_url"] == "http://x"


def test_test_model_endpoint_forwards_form(monkeypatch):
    _patch_engine(monkeypatch, result={"ok": True, "models": []})
    resp = _make_client().post(
        "/api/applicant/setup/model-endpoints/test", data={"base_url": "http://x", "api_key": ""}
    )
    assert resp.status_code == 200
    assert _FakeEngine.last_call[0] == "test_model_endpoint"


def test_model_endpoint_models(monkeypatch):
    _patch_engine(monkeypatch, result=["m1", "m2"])
    resp = _make_client().get("/api/applicant/setup/model-endpoints/e1/models")
    assert resp.status_code == 200
    assert _FakeEngine.last_call == ("model_endpoint_models", ("e1", False))


def test_channels_get_and_save(monkeypatch):
    _patch_engine(monkeypatch, result={"discord_configured": False})
    assert _make_client().get("/api/applicant/setup/channels").status_code == 200
    assert _FakeEngine.last_call == ("setup_get_channels", ())

    _patch_engine(monkeypatch, result=None)
    resp = _make_client().post(
        "/api/applicant/setup/channels",
        json={
            "discord_webhook_url": "https://d",
            "apprise_urls": "",
            "ntfy_url": "ntfy://ntfy.sh/topic",
        },
    )
    assert resp.status_code == 200
    name, args = _FakeEngine.last_call
    assert name == "setup_configure_channels"
    assert args[0]["discord_webhook_url"] == "https://d"
    # K5: ntfy push is configurable from the front-door and passes through the proxy.
    assert args[0]["ntfy_url"] == "ntfy://ntfy.sh/topic"


def test_channels_save_omitted_field_not_forwarded(monkeypatch):
    """Regression: configure_channels now does body.model_dump(exclude_unset=True)
    instead of body.model_dump(), so a field left out of the request entirely is
    NOT forwarded to the engine (its "leave the saved value alone" semantics) —
    previously every field defaulted to "" and was always sent, so the engine
    could not tell "omitted" from "explicitly cleared"."""
    _patch_engine(monkeypatch, result=None)
    resp = _make_client().post(
        "/api/applicant/setup/channels",
        json={"discord_webhook_url": "https://d"},
    )
    assert resp.status_code == 200
    name, args = _FakeEngine.last_call
    assert name == "setup_configure_channels"
    payload = args[0]
    assert payload == {"discord_webhook_url": "https://d"}
    assert "apprise_urls" not in payload
    assert "ntfy_url" not in payload
    assert "email_timeout_minutes" not in payload


def test_channels_save_explicit_empty_string_is_forwarded(monkeypatch):
    """Regression: an explicit "" (caller intent to clear a channel) is
    distinguished from omission and still forwarded to the engine, rather than
    being silently dropped or coerced into "leave unchanged"."""
    _patch_engine(monkeypatch, result=None)
    resp = _make_client().post(
        "/api/applicant/setup/channels",
        json={"discord_webhook_url": "", "apprise_urls": "https://a"},
    )
    assert resp.status_code == 200
    name, args = _FakeEngine.last_call
    payload = args[0]
    assert "discord_webhook_url" in payload
    assert payload["discord_webhook_url"] == ""
    assert payload["apprise_urls"] == "https://a"
    assert "ntfy_url" not in payload
    assert "email_timeout_minutes" not in payload


def test_channels_test(monkeypatch):
    _patch_engine(monkeypatch, result={"sent": True, "channels": ["discord"]})
    resp = _make_client().post("/api/applicant/setup/channels/test")
    assert resp.status_code == 200
    assert resp.json()["channels"] == ["discord"]


def test_channels_test_forwards_single_channel(monkeypatch):
    # P1-4: a `{"channel": ...}` body scopes the test to one channel; the proxy
    # forwards the channel name to the engine client verbatim.
    _patch_engine(monkeypatch, result={"sent": True, "live": False, "channels": ["discord"]})
    resp = _make_client().post(
        "/api/applicant/setup/channels/test", json={"channel": "discord"}
    )
    assert resp.status_code == 200
    assert resp.json()["channels"] == ["discord"]
    assert _FakeEngine.last_call == ("setup_test_channels", ("discord",))


def test_channels_test_without_body_forwards_empty_channel(monkeypatch):
    # The historical no-body shape keeps the fan-out behavior (empty channel).
    _patch_engine(monkeypatch, result={"sent": True, "channels": ["discord", "ntfy"]})
    resp = _make_client().post("/api/applicant/setup/channels/test")
    assert resp.status_code == 200
    assert _FakeEngine.last_call == ("setup_test_channels", ("",))


def test_channels_test_passes_through_dry_run_state(monkeypatch):
    # K6: the engine's live-vs-dry-run honesty fields reach the front-door unchanged.
    _patch_engine(
        monkeypatch,
        result={"sent": True, "live": False, "note": "dry run — set NOTIFICATIONS_LIVE=true to deliver", "channels": ["ntfy"]},
    )
    resp = _make_client().post("/api/applicant/setup/channels/test")
    assert resp.status_code == 200
    body = resp.json()
    assert body["live"] is False
    assert "NOTIFICATIONS_LIVE" in body["note"]


# ── quiet hours (FR-NOTIF-5) ────────────────────────────────────────────────


def test_quiet_hours_get_and_save(monkeypatch):
    _patch_engine(
        monkeypatch,
        result={"enabled": True, "start": "22:00", "end": "07:00", "tz": ""},
    )
    r = _make_client().get("/api/applicant/setup/channels/quiet-hours")
    assert r.status_code == 200
    assert r.json()["enabled"] is True
    assert _FakeEngine.last_call == ("setup_get_quiet_hours", ())

    _patch_engine(monkeypatch, result=None)
    resp = _make_client().post(
        "/api/applicant/setup/channels/quiet-hours",
        json={"enabled": True, "start": "22:30", "end": "07:15", "tz": "America/Phoenix"},
    )
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}
    name, args = _FakeEngine.last_call
    assert name == "setup_configure_quiet_hours"
    assert args[0]["enabled"] is True
    assert args[0]["start"] == "22:30"
    assert args[0]["tz"] == "America/Phoenix"


def test_quiet_hours_forwards_per_channel_respects_quiet(monkeypatch):
    """#302 regression: QuietHoursIn now declares discord_respects_quiet /
    email_respects_quiet, so they reach the engine payload. Previously the
    model didn't declare these fields and pydantic silently stripped them
    before the request ever left the proxy (the wizard's toggle was a no-op)."""
    _patch_engine(monkeypatch, result=None)
    resp = _make_client().post(
        "/api/applicant/setup/channels/quiet-hours",
        json={
            "enabled": True,
            "start": "22:00",
            "end": "07:00",
            "tz": "UTC",
            "discord_respects_quiet": True,
            "email_respects_quiet": False,
        },
    )
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}
    name, args = _FakeEngine.last_call
    assert name == "setup_configure_quiet_hours"
    payload = args[0]
    # the new per-channel fields actually reach the outbound payload
    assert payload["discord_respects_quiet"] is True
    assert payload["email_respects_quiet"] is False
    # baseline fields still round-trip correctly (no regression there)
    assert payload["enabled"] is True
    assert payload["start"] == "22:00"
    assert payload["end"] == "07:00"
    assert payload["tz"] == "UTC"

    # Omitting the new fields still forwards them (as None, the "leave saved
    # value alone" default) rather than raising or dropping the whole request.
    _patch_engine(monkeypatch, result=None)
    resp2 = _make_client().post(
        "/api/applicant/setup/channels/quiet-hours",
        json={"enabled": False, "start": "22:00", "end": "07:00", "tz": ""},
    )
    assert resp2.status_code == 200
    _, args2 = _FakeEngine.last_call
    payload2 = args2[0]
    assert payload2["discord_respects_quiet"] is None
    assert payload2["email_respects_quiet"] is None


def test_quiet_hours_engine_400_passed_through(monkeypatch):
    err = EngineError("bad", status=400, detail="Quiet-hours start must be a time")
    _patch_engine(monkeypatch, error=err)
    resp = _make_client().post(
        "/api/applicant/setup/channels/quiet-hours",
        json={"enabled": True, "start": "25:00", "end": "07:00"},
    )
    assert resp.status_code == 400


# ── automation sandbox backend (FR-SANDBOX-1) ───────────────────────────────


def test_sandbox_connection_get_passes_engine_json_through(monkeypatch):
    payload = {
        "backend": "local",
        "connection": {},
        "configured": False,
        "backend_ready": True,
    }
    _patch_engine(monkeypatch, result=payload)
    resp = _make_client().get("/api/applicant/setup/sandbox-connection")
    assert resp.status_code == 200
    assert resp.json() == payload
    assert _FakeEngine.last_call == ("setup_get_sandbox_connection", ())


def test_sandbox_connection_save_forwards_body_and_keeps_secrets(monkeypatch):
    _patch_engine(monkeypatch, result=None)
    body = {
        "proxmox_api_url": "https://pve:8006/api2/json",
        "proxmox_node": "pve",
        "proxmox_token_id": "root@pam!applicant",
        "proxmox_token_secret": "s3cr3t",
        "template_vmid": 100,
        "clone_mode": "snapshot-revert",
        "rdp_username": "Administrator",
        "rdp_password": "p@ss",
        "takeover_method": "rdp",
    }
    resp = _make_client().post("/api/applicant/setup/sandbox-connection", json=body)
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}
    name, args = _FakeEngine.last_call
    assert name == "setup_configure_sandbox_connection"
    # The proxy forwards the full body (incl. secrets) to the engine, which vaults
    # them; nothing is dropped on the way through.
    assert args[0]["proxmox_node"] == "pve"
    assert args[0]["template_vmid"] == 100
    assert args[0]["proxmox_token_secret"] == "s3cr3t"
    assert args[0]["rdp_password"] == "p@ss"


def test_sandbox_connection_engine_400_passed_through(monkeypatch):
    err = EngineError("bad", status=400, detail="A Windows template/persistent VMID is required")
    _patch_engine(monkeypatch, error=err)
    resp = _make_client().post(
        "/api/applicant/setup/sandbox-connection",
        json={
            "proxmox_api_url": "https://pve:8006/api2/json",
            "proxmox_node": "pve",
            "proxmox_token_id": "id",
            "proxmox_token_secret": "s",
            "template_vmid": 0,
        },
    )
    assert resp.status_code == 400
    assert "VMID" in resp.json()["detail"]


def test_fonts_list_detect_install(monkeypatch):
    _patch_engine(monkeypatch, result={"installed": ["Arial"]})
    assert _make_client().get("/api/applicant/setup/fonts").status_code == 200
    assert _FakeEngine.last_call == ("list_fonts", ())

    _patch_engine(monkeypatch, result={"required": ["X"], "missing": ["X"], "installed": []})
    resp = _make_client().post(
        "/api/applicant/setup/fonts/detect",
        files={"file": ("resume.docx", b"data", "application/octet-stream")},
    )
    assert resp.status_code == 200
    assert _FakeEngine.last_call[0] == "detect_fonts"

    _patch_engine(monkeypatch, result={"installed": ["X"], "confirmed": True})
    resp = _make_client().post(
        "/api/applicant/setup/fonts/install",
        data={"name": "X"},
        files={"file": ("X.ttf", b"fontbytes", "font/ttf")},
    )
    assert resp.status_code == 200
    name, args = _FakeEngine.last_call
    assert name == "install_font"
    assert args[1] == {"name": "X"}


def test_campaigns_list_and_create(monkeypatch):
    _patch_engine(monkeypatch, result=[{"id": "c1", "name": "Search"}])
    assert _make_client().get("/api/applicant/setup/campaigns").status_code == 200
    assert _FakeEngine.last_call == ("list_campaigns", ())

    _patch_engine(monkeypatch, result={"id": "c2", "name": "New"})
    resp = _make_client().post("/api/applicant/setup/campaigns", json={"name": "New"})
    assert resp.status_code == 200
    assert _FakeEngine.last_call == ("create_campaign", ("New",))


def test_onboarding_state_section_complete(monkeypatch):
    _patch_engine(monkeypatch, result={"campaign_id": "c1", "complete": False, "sections_complete": []})
    assert _make_client().get("/api/applicant/setup/onboarding/c1").status_code == 200
    assert _FakeEngine.last_call == ("onboarding_state", ("c1",))

    _patch_engine(monkeypatch, result={"campaign_id": "c1", "sections_complete": ["identity"]})
    resp = _make_client().post(
        "/api/applicant/setup/onboarding/c1/section",
        json={"section": "identity", "data": {"email": "a@b.c"}},
    )
    assert resp.status_code == 200
    name, args = _FakeEngine.last_call
    assert name == "onboarding_section"
    assert args[0] == "c1"
    assert args[1] == {"section": "identity", "data": {"email": "a@b.c"}}

    _patch_engine(monkeypatch, result={"campaign_id": "c1", "complete": True})
    resp = _make_client().post("/api/applicant/setup/onboarding/c1/complete")
    assert resp.status_code == 200
    assert _FakeEngine.last_call == ("onboarding_complete", ("c1",))


def test_base_resume_upload_and_confirm(monkeypatch):
    _patch_engine(monkeypatch, result={"attribute_count": 5, "conflicts": [], "requires_confirmation": False})
    resp = _make_client().post(
        "/api/applicant/setup/onboarding/c1/base-resume",
        files={"file": ("cv.docx", b"resume", "application/octet-stream")},
    )
    assert resp.status_code == 200
    assert resp.json()["attribute_count"] == 5
    assert _FakeEngine.last_call[0] == "onboarding_base_resume"

    _patch_engine(monkeypatch, result={"campaign_id": "c1"})
    resp = _make_client().post(
        "/api/applicant/setup/onboarding/c1/confirm-conflict",
        json={"attribute": "email", "value": "a@b.c"},
    )
    assert resp.status_code == 200
    name, args = _FakeEngine.last_call
    assert name == "onboarding_confirm_conflict"
    assert args[1] == {"attribute": "email", "value": "a@b.c"}


def test_conversion_preview_accept_reject(monkeypatch):
    _patch_engine(monkeypatch, result={"page_count": 1, "fidelity_ok": True, "notes": []})
    resp = _make_client().post("/api/applicant/setup/conversion/c1/preview", json={"source": ""})
    assert resp.status_code == 200
    assert _FakeEngine.last_call == ("conversion_preview", ("c1", ""))

    _patch_engine(monkeypatch, result={"engine": "latex"})
    assert _make_client().post("/api/applicant/setup/conversion/c1/accept").status_code == 200
    assert _FakeEngine.last_call == ("conversion_accept", ("c1",))

    _patch_engine(monkeypatch, result={"engine": "docx"})
    assert _make_client().post("/api/applicant/setup/conversion/c1/reject").status_code == 200
    assert _FakeEngine.last_call == ("conversion_reject", ("c1",))


# ── error translation ───────────────────────────────────────────────────────


def test_engine_http_status_passed_through(monkeypatch):
    """A 409 onboarding-incomplete from the engine surfaces as a 409 to the UI."""
    err = EngineError("incomplete", status=409, detail={"missing_sections": ["eeo"]})
    _patch_engine(monkeypatch, error=err)
    resp = _make_client().post("/api/applicant/setup/onboarding/c1/complete")
    assert resp.status_code == 409
    body = resp.json()
    assert body["error"] == "engine_error"
    assert body["engine_status"] == 409
    assert body["detail"] == {"missing_sections": ["eeo"]}


def test_engine_400_bad_llm_passed_through(monkeypatch):
    err = EngineError("bad", status=400, detail="invalid model")
    _patch_engine(monkeypatch, error=err)
    resp = _make_client().post(
        "/api/applicant/setup/llm",
        json={"provider": "x", "model": "m"},
    )
    assert resp.status_code == 400
    assert resp.json()["detail"] == "invalid model"


def test_engine_timeout_becomes_502(monkeypatch):
    err = EngineError("timed out", is_timeout=True)
    _patch_engine(monkeypatch, error=err)
    resp = _make_client().get("/api/applicant/setup/status")
    assert resp.status_code == 502
    assert "timed out" in resp.json()["message"].lower()


def test_engine_connection_error_becomes_502(monkeypatch):
    err = EngineError("connection refused")
    _patch_engine(monkeypatch, error=err)
    resp = _make_client().get("/api/applicant/setup/fonts")
    assert resp.status_code == 502
    assert resp.json()["message"] == "The application engine is unavailable."


# ── auth gate ────────────────────────────────────────────────────────────────


def test_requires_authentication(monkeypatch):
    class _Configured:
        is_configured = True

    def _boom(*a, **k):  # pragma: no cover - must not run
        raise AssertionError("engine must not be called when unauthenticated")

    monkeypatch.setattr(setup_routes, "ApplicantEngineClient", _boom)

    app = FastAPI()
    app.state.auth_manager = _Configured()
    app.include_router(setup_applicant_setup_routes())
    client = TestClient(app)

    assert client.get("/api/applicant/setup/status").status_code == 401


# ── owner-scoped config privilege gate (mutations require can_configure) ──────


class _PrivAuthManager:
    is_configured = True

    def __init__(self, privileges):
        self._privs = privileges

    def get_privileges(self, _user):
        return dict(self._privs)


def _make_priv_client(privileges, *, user="restricted"):
    app = FastAPI()
    app.state.auth_manager = _PrivAuthManager(privileges)

    @app.middleware("http")
    async def _set_user(request: Request, call_next):
        request.state.current_user = user
        return await call_next(request)

    app.include_router(setup_applicant_setup_routes())
    return TestClient(app)


def test_config_writes_require_can_configure(monkeypatch):
    def _boom(*a, **k):  # pragma: no cover - must not run when forbidden
        raise AssertionError("engine must not be called when privilege is denied")

    monkeypatch.setattr(setup_routes, "ApplicantEngineClient", _boom)
    client = _make_priv_client({"can_configure": False})

    writes = [
        ("POST", "/api/applicant/setup/advance/llm", None, None),
        ("POST", "/api/applicant/setup/llm", {"provider": "x", "model": "m"}, None),
        ("POST", "/api/applicant/setup/channels", {"discord_webhook_url": "d"}, None),
        ("POST", "/api/applicant/setup/channels/test", None, None),
        (
            "POST",
            "/api/applicant/setup/sandbox-connection",
            {
                "proxmox_api_url": "https://pve:8006/api2/json",
                "proxmox_node": "pve",
                "proxmox_token_id": "id",
                "proxmox_token_secret": "s",
                "template_vmid": 100,
            },
            None,
        ),
        ("POST", "/api/applicant/setup/campaigns", {"name": "n"}, None),
        ("POST", "/api/applicant/setup/onboarding/c1/complete", None, None),
    ]
    for method, path, body, _ in writes:
        resp = client.request(method, path, json=body)
        assert resp.status_code == 403, f"{method} {path} -> {resp.status_code}"


def test_reads_allowed_without_config_privilege(monkeypatch):
    _patch_engine(monkeypatch, result={"llm_configured": True})
    client = _make_priv_client({"can_configure": False})
    assert client.get("/api/applicant/setup/status").status_code == 200
    assert client.get("/api/applicant/setup/channels").status_code == 200
    assert client.get("/api/applicant/setup/sandbox-connection").status_code == 200


def test_config_writes_allowed_with_privilege(monkeypatch):
    _patch_engine(monkeypatch, result=None)
    client = _make_priv_client({"can_configure": True})
    resp = client.post("/api/applicant/setup/channels", json={"discord_webhook_url": "d"})
    assert resp.status_code == 200
    assert _FakeEngine.last_call[0] == "setup_configure_channels"
