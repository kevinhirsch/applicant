"""Hermetic tests for the Applicant engine client (src/applicant_engine.py).

Zero network: every request is served by an ``httpx.MockTransport`` injected into
the client. Covers URL resolution, JSON decoding, 204/empty handling, the typed
``EngineError`` for HTTP + timeout failures, and the sync helpers.
"""

import httpx
import pytest

from src.applicant_engine import (
    DEFAULT_ENGINE_URL,
    ApplicantEngineClient,
    EngineError,
    engine_available_sync,
    engine_base_url,
    get_sync,
)


def _transport(handler):
    return httpx.MockTransport(handler)


def test_engine_base_url_default(monkeypatch):
    monkeypatch.delenv("ENGINE_URL", raising=False)
    assert engine_base_url() == DEFAULT_ENGINE_URL


def test_engine_base_url_from_env_strips_slash(monkeypatch):
    monkeypatch.setenv("ENGINE_URL", "http://engine.example:9000/")
    assert engine_base_url() == "http://engine.example:9000"


@pytest.mark.asyncio
async def test_setup_status_returns_json():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["method"] = request.method
        return httpx.Response(200, json={"llm_configured": True, "gate_open": False})

    async with ApplicantEngineClient(
        base_url="http://api:8000", transport=_transport(handler)
    ) as engine:
        data = await engine.setup_status()

    assert data == {"llm_configured": True, "gate_open": False}
    assert captured["url"] == "http://api:8000/api/setup/status"
    assert captured["method"] == "GET"


@pytest.mark.asyncio
async def test_path_params_and_body_are_sent():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["body"] = request.content.decode() if request.content else ""
        return httpx.Response(200, json={"ok": True})

    async with ApplicantEngineClient(
        base_url="http://api:8000", transport=_transport(handler)
    ) as engine:
        await engine.turn_document("doc-42", {"kind": "add", "instruction": "x"})

    assert captured["url"] == "http://api:8000/api/documents/doc-42/turn"
    assert '"kind"' in captured["body"] and '"add"' in captured["body"]


@pytest.mark.asyncio
async def test_204_returns_none():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(204)

    async with ApplicantEngineClient(
        base_url="http://api:8000", transport=_transport(handler)
    ) as engine:
        assert await engine.approve_document("doc-1") is None


@pytest.mark.asyncio
async def test_http_error_raises_engine_error_with_detail():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(409, json={"detail": "review required"})

    async with ApplicantEngineClient(
        base_url="http://api:8000", transport=_transport(handler)
    ) as engine:
        with pytest.raises(EngineError) as exc:
            await engine.approve_document("doc-1")

    assert exc.value.status == 409
    assert exc.value.detail == "review required"
    assert exc.value.is_timeout is False


@pytest.mark.asyncio
async def test_timeout_raises_typed_error_not_httpx():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    async with ApplicantEngineClient(
        base_url="http://api:8000", transport=_transport(handler)
    ) as engine:
        with pytest.raises(EngineError) as exc:
            await engine.setup_status()

    assert exc.value.is_timeout is True
    assert exc.value.status is None


@pytest.mark.asyncio
async def test_connect_error_raises_engine_error():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    async with ApplicantEngineClient(
        base_url="http://api:8000", transport=_transport(handler)
    ) as engine:
        with pytest.raises(EngineError) as exc:
            await engine.list_documents()
    assert exc.value.is_timeout is False
    assert exc.value.status is None


@pytest.mark.asyncio
async def test_engine_available_true_and_false():
    def up(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/healthz"
        return httpx.Response(200, json={"status": "ok"})

    def down(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    async with ApplicantEngineClient(base_url="http://api:8000", transport=_transport(up)) as e:
        assert await e.engine_available() is True
    async with ApplicantEngineClient(base_url="http://api:8000", transport=_transport(down)) as e:
        assert await e.engine_available() is False


@pytest.mark.asyncio
async def test_dormant_surfaces_returns_list():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[{"key": "chatbot", "status": "live"}])

    async with ApplicantEngineClient(
        base_url="http://api:8000", transport=_transport(handler)
    ) as engine:
        out = await engine.dormant_surfaces()
    assert out == [{"key": "chatbot", "status": "live"}]


# -- sync helpers ----------------------------------------------------------


def test_engine_available_sync_true_false():
    def up(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200)

    def down(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    assert engine_available_sync(base_url="http://api:8000", transport=_transport(up)) is True
    assert engine_available_sync(base_url="http://api:8000", transport=_transport(down)) is False


def test_get_sync_json_and_error():
    def ok(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"a": 1})

    def boom(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="nope")

    assert get_sync("/api/setup/status", base_url="http://api:8000", transport=_transport(ok)) == {"a": 1}
    with pytest.raises(EngineError) as exc:
        get_sync("/api/setup/status", base_url="http://api:8000", transport=_transport(boom))
    assert exc.value.status == 500


def test_get_sync_timeout_is_typed():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("slow", request=request)

    with pytest.raises(EngineError) as exc:
        get_sync("/healthz", base_url="http://api:8000", transport=_transport(handler))
    assert exc.value.is_timeout is True
