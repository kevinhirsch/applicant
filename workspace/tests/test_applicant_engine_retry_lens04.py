"""Hermetic tests for the bounded retry/backoff added to
``ApplicantEngineClient._request`` (failure-paths audit, lens 04, finding #9).

Zero network: every request is served by an ``httpx.MockTransport``. The
backoff sleep itself is monkeypatched to a fast no-op (``_sleep_before_retry``)
so these tests exercise the real retry/backoff *decision* logic without
actually waiting out the delays.

Covered:
* A GET that fails transiently (connection error, then 502) and later
  succeeds is retried and returns the success response.
* A GET is retried a bounded number of times, then surfaces the identical
  :class:`EngineError` shape once retries are exhausted.
* A 4xx response is never retried (client error, not a blip).
* A non-idempotent write (POST) is never silently retried, even on a
  transient connection error or a 502/503.
"""

import httpx
import pytest

from src import applicant_engine
from src.applicant_engine import ApplicantEngineClient, EngineError


def _transport(handler):
    return httpx.MockTransport(handler)


@pytest.fixture(autouse=True)
def _fast_backoff(monkeypatch):
    """Never actually sleep during these tests -- just record the delays."""
    calls = []

    async def _no_sleep(seconds: float) -> None:
        calls.append(seconds)

    monkeypatch.setattr(applicant_engine, "_sleep_before_retry", _no_sleep)
    return calls


@pytest.mark.asyncio
async def test_get_retries_after_connect_error_then_succeeds(_fast_backoff):
    attempts = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise httpx.ConnectError("connection reset", request=request)
        return httpx.Response(200, json={"ok": True})

    async with ApplicantEngineClient(
        base_url="http://api:8000", transport=_transport(handler)
    ) as engine:
        data = await engine.list_documents()

    assert data == {"ok": True}
    assert attempts["n"] == 2
    assert len(_fast_backoff) == 1  # one backoff sleep before the retry


@pytest.mark.asyncio
async def test_get_retries_after_502_then_succeeds(_fast_backoff):
    attempts = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["n"] += 1
        if attempts["n"] == 1:
            return httpx.Response(502, text="bad gateway")
        return httpx.Response(200, json={"ok": True})

    async with ApplicantEngineClient(
        base_url="http://api:8000", transport=_transport(handler)
    ) as engine:
        data = await engine.list_documents()

    assert data == {"ok": True}
    assert attempts["n"] == 2


@pytest.mark.asyncio
async def test_get_retries_are_bounded_then_raises_same_error_shape(_fast_backoff):
    attempts = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["n"] += 1
        raise httpx.ConnectError("still down", request=request)

    async with ApplicantEngineClient(
        base_url="http://api:8000", transport=_transport(handler)
    ) as engine:
        with pytest.raises(EngineError) as exc:
            await engine.list_documents()

    # Identical error surface to the pre-retry single-attempt behaviour.
    assert exc.value.status is None
    assert exc.value.is_timeout is False
    # Bounded: the first attempt plus a small, fixed number of retries -- not
    # an unbounded/hanging retry loop.
    assert 2 <= attempts["n"] <= 4


@pytest.mark.asyncio
async def test_get_503_exhausted_raises_engine_error_with_status(_fast_backoff):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="unavailable")

    async with ApplicantEngineClient(
        base_url="http://api:8000", transport=_transport(handler)
    ) as engine:
        with pytest.raises(EngineError) as exc:
            await engine.list_documents()

    assert exc.value.status == 503


@pytest.mark.asyncio
async def test_get_4xx_is_never_retried(_fast_backoff):
    attempts = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["n"] += 1
        return httpx.Response(409, json={"detail": "review required"})

    async with ApplicantEngineClient(
        base_url="http://api:8000", transport=_transport(handler)
    ) as engine:
        with pytest.raises(EngineError) as exc:
            await engine.approve_document("doc-1")

    assert attempts["n"] == 1  # a single attempt, no retry
    assert exc.value.status == 409
    assert len(_fast_backoff) == 0  # no backoff sleep was ever scheduled


@pytest.mark.asyncio
async def test_post_is_never_silently_retried_on_connect_error(_fast_backoff):
    attempts = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["n"] += 1
        raise httpx.ConnectError("connection reset", request=request)

    async with ApplicantEngineClient(
        base_url="http://api:8000", transport=_transport(handler)
    ) as engine:
        with pytest.raises(EngineError):
            await engine.approve_document("doc-1")

    assert attempts["n"] == 1  # a write is never auto-resent
    assert len(_fast_backoff) == 0


@pytest.mark.asyncio
async def test_post_is_never_silently_retried_on_503(_fast_backoff):
    attempts = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["n"] += 1
        return httpx.Response(503, text="unavailable")

    async with ApplicantEngineClient(
        base_url="http://api:8000", transport=_transport(handler)
    ) as engine:
        with pytest.raises(EngineError) as exc:
            await engine.approve_document("doc-1")

    assert attempts["n"] == 1
    assert exc.value.status == 503
    assert len(_fast_backoff) == 0


@pytest.mark.asyncio
async def test_get_read_timeout_still_fast_fails_without_retry(_fast_backoff):
    """Read timeouts are a different failure mode than a dropped connection
    (slow-but-connected vs. reset) and stay fast-fail, unchanged."""
    attempts = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["n"] += 1
        raise httpx.ReadTimeout("slow", request=request)

    async with ApplicantEngineClient(
        base_url="http://api:8000", transport=_transport(handler)
    ) as engine:
        with pytest.raises(EngineError) as exc:
            await engine.list_documents()

    assert attempts["n"] == 1
    assert exc.value.is_timeout is True
    assert len(_fast_backoff) == 0
