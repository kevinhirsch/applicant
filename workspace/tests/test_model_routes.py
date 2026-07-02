"""Tests for model route helper functions — pure logic, no server needed."""
import os
import subprocess
import sys
import types
from unittest.mock import MagicMock

import httpx
import pytest

_endpoint_resolver = sys.modules.get("src.endpoint_resolver")
if _endpoint_resolver is not None and not getattr(_endpoint_resolver, "__file__", None):
    # Other tests stub this module during collection. These helper tests need
    # the real URL normalization helpers so Anthropic /v1 handling is covered.
    sys.modules.pop("src.endpoint_resolver", None)
    sys.modules.pop("routes.model_routes", None)

if "core.database" not in sys.modules:
    _core_db = types.ModuleType("core.database")
    for _name in [
        "SessionLocal", "ModelEndpoint", "Session", "ChatMessage", "Document",
        "DocumentVersion", "GalleryImage", "GalleryAlbum", "Note",
        "CalendarCal", "CalendarEvent", "ScheduledTask", "TaskRun",
        "McpServer",
    ]:
        setattr(_core_db, _name, MagicMock())
    sys.modules["core.database"] = _core_db

import routes.model_routes as model_routes
import src.endpoint_resolver as endpoint_resolver
from routes.model_routes import (
    _match_provider_curated,
    _curate_models,
    _is_chat_model,
    _classify_endpoint,
    _probe_endpoint,
    _truthy,
    _PROVIDER_CURATED,
)
from src.llm_core import ANTHROPIC_MODELS


# ── _match_provider_curated ──

class TestMatchProviderCurated:
    def test_url_match_overrides_provider(self):
        assert _match_provider_curated("https://z.ai/v1", "openai") == "zai"

    def test_deepseek_url(self):
        assert _match_provider_curated("https://api.deepseek.com/v1", "openai") == "deepseek"

    def test_groq_url(self):
        assert _match_provider_curated("https://api.groq.com/openai/v1", "openai") == "groq"

    def test_mistral_url(self):
        assert _match_provider_curated("https://api.mistral.ai/v1", "openai") == "mistral"

    def test_together_url(self):
        assert _match_provider_curated("https://api.together.xyz/v1", "openai") == "together"

    def test_fireworks_url(self):
        assert _match_provider_curated("https://api.fireworks.ai/inference/v1", "openai") == "fireworks"

    def test_google_url(self):
        assert _match_provider_curated("https://generativelanguage.googleapis.com/v1beta", "openai") == "google"

    def test_xai_url(self):
        assert _match_provider_curated("https://api.x.ai/v1", "openai") == "xai"

    def test_ollama_url(self):
        assert _match_provider_curated("https://ollama.com/api", "openai") == "ollama"

    def test_no_url_match_returns_provider(self):
        assert _match_provider_curated("https://localhost:1234", "openai") == "openai"

    def test_none_provider_passthrough(self):
        assert _match_provider_curated("https://localhost:1234", None) is None

    def test_none_url_safe(self):
        assert _match_provider_curated(None, "openai") == "openai"


# ── _curate_models ──

class TestCurateModels:
    def test_known_provider_partitions(self):
        models = ["gpt-4o", "gpt-4o-mini", "ft:gpt-4o:custom", "some-random-model"]
        curated, extra = _curate_models(models, "openai")
        assert "gpt-4o" in curated
        assert "gpt-4o-mini" in curated
        assert "some-random-model" in extra

    def test_unknown_provider_returns_all_as_curated(self):
        models = ["model-a", "model-b"]
        curated, extra = _curate_models(models, "unknown_provider")
        assert curated == models
        assert extra == []

    def test_curated_sorted_by_priority(self):
        models = ["gpt-4o-mini", "gpt-4o", "o3"]
        curated, _ = _curate_models(models, "openai")
        # gpt-4o should come before gpt-4o-mini in the curated list priority
        gpt4o_idx = curated.index("gpt-4o")
        gpt4o_mini_idx = curated.index("gpt-4o-mini")
        assert gpt4o_idx < gpt4o_mini_idx

    def test_empty_models(self):
        curated, extra = _curate_models([], "openai")
        assert curated == []
        assert extra == []

    def test_deepseek_curated(self):
        models = ["deepseek-chat", "deepseek-reasoner", "deepseek-coder"]
        curated, extra = _curate_models(models, "deepseek")
        assert "deepseek-chat" in curated
        assert "deepseek-reasoner" in curated
        assert "deepseek-coder" in extra

    def test_xai_curated(self):
        models = ["grok-4", "grok-3-fast", "grok-2"]
        curated, extra = _curate_models(models, "xai")
        assert "grok-4" in curated
        assert "grok-3-fast" in curated
        assert "grok-2" in extra

    def test_xai_current_grok_43_curated(self):
        curated, extra = _curate_models(["grok-4.3", "grok-4.3-fast"], "xai")
        assert curated == ["grok-4.3", "grok-4.3-fast"]
        assert extra == []

    def test_groq_current_models_curated(self):
        models = [
            "openai/gpt-oss-120b",
            "groq/compound",
            "llama-3.1-8b-instant",
            "llama-4-scout-17b-16e-instruct",
        ]
        curated, extra = _curate_models(models, "groq")
        assert curated == models
        assert extra == []

    def test_google_current_gemini_curated(self):
        curated, extra = _curate_models(["gemini-3.5-flash", "gemini-3.1-pro"], "google")
        assert curated == ["gemini-3.5-flash", "gemini-3.1-pro"]
        assert extra == []


# ── _is_chat_model ──

class TestIsChatModel:
    @pytest.mark.parametrize("model_id", [
        "gpt-4o", "gpt-4o-mini", "claude-sonnet-4", "llama-3.3-70b",
        "deepseek-chat", "gemini-2.0-flash", "o3",
        "llama-4-scout-17b-16e-instruct",
    ])
    def test_chat_models(self, model_id):
        assert _is_chat_model(model_id) is True

    @pytest.mark.parametrize("model_id", [
        "dall-e-3", "tts-1", "whisper-1", "text-embedding-3-small",
        "gpt-image-1", "sora-1",
    ])
    def test_non_chat_models(self, model_id):
        assert _is_chat_model(model_id) is False

    def test_realtime_excluded(self):
        assert _is_chat_model("gpt-4o-realtime-preview") is False

    def test_audio_preview_is_chat(self):
        # gpt-4o-audio-preview is a chat model (has "audio" not "gpt-audio")
        assert _is_chat_model("gpt-4o-audio-preview") is True

    def test_gpt_audio_is_not_chat(self):
        assert _is_chat_model("gpt-audio") is False

    def test_legacy_openai_instruct_is_not_chat(self):
        assert _is_chat_model("gpt-3.5-turbo-instruct") is False


# ── _classify_endpoint ──

class TestClassifyEndpoint:
    def test_localhost(self):
        assert _classify_endpoint("http://localhost:1234") == "local"

    def test_127(self):
        assert _classify_endpoint("http://127.0.0.1:8080/v1") == "local"

    def test_private_192(self):
        assert _classify_endpoint("http://192.168.1.100:5000") == "local"

    def test_private_10(self):
        assert _classify_endpoint("http://10.0.0.5:8000") == "local"

    def test_public_api(self):
        assert _classify_endpoint("https://api.openai.com/v1") == "api"

    def test_empty_string(self):
        assert _classify_endpoint("") == "api"

    def test_malformed_url(self):
        assert _classify_endpoint("not-a-url") == "api"


# ── setup probing ──

class TestSetupProbeSafety:
    @pytest.mark.parametrize("value", ["true", "1", "yes", "on", " TRUE "])
    def test_truthy_true_values(self, value):
        assert _truthy(value) is True

    @pytest.mark.parametrize("value", ["false", "0", "no", "", None])
    def test_truthy_false_values(self, value):
        assert _truthy(value) is False

    def test_keyed_probe_does_not_fallback_to_curated_on_auth_failure(self, monkeypatch):
        monkeypatch.setattr(endpoint_resolver, "resolve_url", lambda url: url, raising=False)
        monkeypatch.setattr(model_routes, "_normalize_base", lambda url: url.rstrip("/"))

        def fake_get(url, headers=None, timeout=None):
            request = httpx.Request("GET", url)
            response = httpx.Response(401, request=request)
            raise httpx.HTTPStatusError("unauthorized", request=request, response=response)

        monkeypatch.setattr(model_routes.httpx, "get", fake_get)

        assert _probe_endpoint("https://api.groq.com/openai/v1", "bad-key") == []

    def test_unkeyed_probe_can_still_use_curated_fallback(self, monkeypatch):
        monkeypatch.setattr(endpoint_resolver, "resolve_url", lambda url: url, raising=False)
        monkeypatch.setattr(model_routes, "_normalize_base", lambda url: url.rstrip("/"))

        def fake_get(url, headers=None, timeout=None):
            raise httpx.ConnectError("offline")

        monkeypatch.setattr(model_routes.httpx, "get", fake_get)

        assert _probe_endpoint("https://api.groq.com/openai/v1") == _PROVIDER_CURATED["groq"]

    def test_keyed_anthropic_probe_does_not_fallback_on_failure(self, monkeypatch):
        monkeypatch.setattr(endpoint_resolver, "resolve_url", lambda url: url, raising=False)
        monkeypatch.setattr(model_routes, "_normalize_base", lambda url: url.rstrip("/"))

        def fake_get(url, headers=None, timeout=None):
            raise httpx.ConnectError("offline")

        monkeypatch.setattr(model_routes.httpx, "get", fake_get)

        assert _probe_endpoint("https://api.anthropic.com/v1", "bad-key") == []

    def test_anthropic_probe_does_not_double_v1(self, monkeypatch):
        monkeypatch.setattr(endpoint_resolver, "resolve_url", lambda url: url, raising=False)
        monkeypatch.setattr(model_routes, "_normalize_base", lambda url: url.rstrip("/"))
        seen = []

        def fake_get(url, headers=None, timeout=None):
            seen.append(url)
            request = httpx.Request("GET", url)
            response = httpx.Response(
                200,
                request=request,
                json={"data": [{"id": "claude-sonnet-4-5"}]},
            )
            return response

        monkeypatch.setattr(model_routes.httpx, "get", fake_get)

        assert _probe_endpoint("https://api.anthropic.com/v1", "good-key") == ["claude-sonnet-4-5"]
        assert seen == ["https://api.anthropic.com/v1/models"]

    def test_ollama_cloud_probe_uses_native_tags_endpoint(self, monkeypatch):
        monkeypatch.setattr(endpoint_resolver, "resolve_url", lambda url: url, raising=False)
        monkeypatch.setattr(model_routes, "_normalize_base", lambda url: url.rstrip("/"))
        seen = []

        def fake_get(url, headers=None, timeout=None):
            seen.append((url, headers))
            request = httpx.Request("GET", url)
            response = httpx.Response(
                200,
                request=request,
                json={"models": [{"name": "gpt-oss:120b"}, {"model": "qwen3:235b"}]},
            )
            return response

        monkeypatch.setattr(model_routes.httpx, "get", fake_get)

        assert _probe_endpoint("https://ollama.com/api", "ollama-key") == ["gpt-oss:120b", "qwen3:235b"]
        assert seen == [("https://ollama.com/api/tags", {"Authorization": "Bearer ollama-key"})]

    def test_unkeyed_anthropic_probe_can_use_curated_fallback(self, monkeypatch):
        monkeypatch.setattr(endpoint_resolver, "resolve_url", lambda url: url, raising=False)
        monkeypatch.setattr(model_routes, "_normalize_base", lambda url: url.rstrip("/"))

        def fake_get(url, headers=None, timeout=None):
            raise httpx.ConnectError("offline")

        monkeypatch.setattr(model_routes.httpx, "get", fake_get)

        assert _probe_endpoint("https://api.anthropic.com/v1") == ANTHROPIC_MODELS

def test_ollama_endpoint_error_message_includes_troubleshooting():
    msg = model_routes._model_endpoint_error_message(
        "http://localhost:11434/v1",
        {"error": "Connection refused"},
    )

    assert "No Ollama models found" in msg
    assert "Connection refused" in msg
    assert "http://localhost:11434/v1" in msg
    assert "ollama list" in msg


def test_generic_endpoint_error_message_preserves_probe_error():
    msg = model_routes._model_endpoint_error_message(
        "https://api.example.com/v1",
        {"error": "HTTP 401"},
    )

    assert msg == "No models found for that provider/key. Last probe error: HTTP 401."


# ── GET /api/model-endpoints/available (non-admin OOBE picker, #new) ────────
#
# Runs in an isolated subprocess against a real temp SQLite DB, mirroring
# tests/test_entity_store_owner_scope.py: importing the real `core.database`
# runs init_db() at import time (needs a writable DB path) and this module's
# own collection-time stubbing (above) replaces `core.database`/ModelEndpoint
# with MagicMocks in *this* process, so the real ORM + route can only be
# exercised safely in a fresh subprocess. Skips when app deps aren't installed.

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

_AVAILABLE_ENDPOINTS_SCRIPT = r"""
import os, sys, tempfile, json
os.environ["DATABASE_URL"] = "sqlite:///" + tempfile.mkstemp(suffix=".db")[1]
try:
    from core.database import SessionLocal, ModelEndpoint
    from fastapi import FastAPI, Request
    from fastapi.testclient import TestClient
    from routes.model_routes import setup_model_routes
except ModuleNotFoundError as ex:
    print("SKIP", ex)
    sys.exit(0)


class _FakeAuthManager:
    is_configured = True

    def __init__(self, admins):
        self._admins = set(admins)

    def is_admin(self, user):
        return user in self._admins


app = FastAPI()
app.state.auth_manager = _FakeAuthManager({"root"})


@app.middleware("http")
async def _set_user(request: Request, call_next):
    u = request.headers.get("X-Test-User")
    if u:
        request.state.current_user = u
    return await call_next(request)


app.include_router(setup_model_routes(object()))
client = TestClient(app)

# ── seed rows directly through the real ORM model ──
db = SessionLocal()
db.add_all([
    ModelEndpoint(id="shared1", name="Shared", base_url="https://api.example.com/v1",
                  is_enabled=True, cached_models=json.dumps(["m1", "m2"]), owner=None),
    ModelEndpoint(id="alice1", name="AliceOwn", base_url="https://alice.example.com/v1",
                  is_enabled=True, cached_models=json.dumps(["a1"]), owner="alice"),
    ModelEndpoint(id="bob1", name="BobOwn", base_url="https://bob.example.com/v1",
                  is_enabled=True, cached_models=json.dumps(["b1"]), owner="bob"),
    ModelEndpoint(id="disabled1", name="Disabled", base_url="https://disabled.example.com/v1",
                  is_enabled=False, cached_models=json.dumps(["d1"]), owner=None),
    ModelEndpoint(id="empty1", name="Empty", base_url="https://empty.example.com/v1",
                  is_enabled=True, cached_models=None, owner=None),
])
db.commit()
db.close()

# 1. anonymous / unauthenticated -> 401 (auth_manager is configured)
r = client.get("/api/model-endpoints/available")
assert r.status_code == 401, ("anon status", r.status_code, r.text)

# 2. non-admin "alice" -> 200; sees the null-owner shared endpoint + her own,
#    NOT bob's, NOT the disabled one, NOT the zero-models one.
r = client.get("/api/model-endpoints/available", headers={"X-Test-User": "alice"})
assert r.status_code == 200, r.text
by_id = {row["id"]: row for row in r.json()}
assert set(by_id) == {"shared1", "alice1"}, by_id
assert by_id["alice1"]["models"] == ["a1"]
assert by_id["shared1"]["models"] == ["m1", "m2"]

# 3. admin "root" -> sees every enabled+has-models endpoint regardless of owner
#    (including bob's, which alice cannot see), still excludes disabled/empty.
r = client.get("/api/model-endpoints/available", headers={"X-Test-User": "root"})
assert r.status_code == 200, r.text
admin_ids = {row["id"] for row in r.json()}
assert admin_ids == {"shared1", "alice1", "bob1"}, admin_ids

# 4. admin result is a strict superset of the non-admin result
alice_ids = set(by_id)
assert alice_ids.issubset(admin_ids)
assert admin_ids - alice_ids == {"bob1"}

# 5. the pre-existing admin-only CRUD routes remain admin-gated for a non-admin
for method, path, kwargs in [
    ("GET", "/api/model-endpoints", {}),
    ("POST", "/api/model-endpoints", {"data": {"base_url": "http://x"}}),
    ("POST", "/api/model-endpoints/test", {"data": {"base_url": "http://x"}}),
    ("PATCH", "/api/model-endpoints/shared1", {}),
    ("DELETE", "/api/model-endpoints/shared1", {}),
]:
    resp = client.request(method, path, headers={"X-Test-User": "alice"}, **kwargs)
    assert resp.status_code == 403, (method, path, resp.status_code, resp.text)

# ...and an admin actually clears the require_admin gate on those same routes
# (404 on a made-up id proves the handler body ran past require_admin, with no
# network I/O involved).
assert client.request("PATCH", "/api/model-endpoints/doesnotexist", headers={"X-Test-User": "root"}).status_code == 404
assert client.request("DELETE", "/api/model-endpoints/doesnotexist", headers={"X-Test-User": "root"}).status_code == 404

print("OK")
"""


def test_available_model_endpoints_non_admin_owner_scoped():
    """Non-admin OOBE picker (#new): a non-admin gets a 200 with admin-configured
    SHARED (null-owner) + own-owned enabled endpoints that have models; other
    users' owned endpoints, disabled endpoints, and zero-model endpoints are
    excluded. Anonymous is still rejected, admin sees a superset, and the
    pre-existing admin-only CRUD routes are untouched by the change."""
    p = subprocess.run(
        [sys.executable, "-c", _AVAILABLE_ENDPOINTS_SCRIPT],
        cwd=_ROOT, capture_output=True, text=True,
    )
    if "SKIP" in p.stdout:
        pytest.skip("deps not installed: " + p.stdout.strip())
    assert p.returncode == 0, (p.stdout + p.stderr)
    assert "OK" in p.stdout, (p.stdout + p.stderr)
