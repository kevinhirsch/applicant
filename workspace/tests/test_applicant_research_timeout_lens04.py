"""Lens 04 #10 — the deep-research ``run`` proxy gets a real, overridable timeout.

Before the fix, ``POST /{campaign_id}/run`` opened its engine client with no
timeout override, so it rode ``ApplicantEngineClient``'s default (30s read) —
far too short for a deep-research run, which the engine bounds with its own
``max_time`` (clamped 30-600s server-side, ``applicant_internal_routes.py``).
A run that legitimately took more than 30s to synthesize would 503 the caller
even though the engine was still faithfully working the request.

The fix threads a per-call timeout into ``ApplicantEngineClient(timeout=...)``
(mirroring ``applicant_documents_routes.py``'s ``_TURN_TIMEOUT`` precedent),
sized off the caller's own ``max_time`` when supplied. This test captures the
``timeout=`` kwarg the route actually constructs its engine client with and
asserts it is (a) longer than the library default read timeout and (b) grows
with a caller-supplied ``max_time`` — i.e. genuinely overridable, not a fixed
constant that ignores the request.
"""

from __future__ import annotations

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import routes.applicant_research_routes as mod
from routes.applicant_research_routes import setup_applicant_research_routes
from src.applicant_engine import _DEFAULT_TIMEOUT


def _make_app(*, user="alice") -> FastAPI:
    app = FastAPI()

    @app.middleware("http")
    async def _auth(request, call_next):
        request.state.current_user = user
        return await call_next(request)

    app.include_router(setup_applicant_research_routes())
    return app


class RecordingEngine:
    """Stands in for ``ApplicantEngineClient``; records the ``timeout`` kwarg
    each construction was given, so the test can assert on it directly instead
    of guessing at wall-clock behaviour."""

    seen_timeouts: list = []

    def __init__(self, *a, **k):
        RecordingEngine.seen_timeouts.append(k.get("timeout"))

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return None

    async def research_run(self, cid, body):
        return {
            "campaign_id": cid,
            "budget_remaining": 1,
            "query": body.get("query"),
            "summary": "ok",
            "key_findings": [],
            "sources": [],
            "cached": False,
            "unavailable": False,
            "reason": "",
        }

    async def research_cached(self, cid, query):
        return {"campaign_id": cid}

    async def research_budget(self, cid):
        return {"campaign_id": cid, "available": True, "calls_made": 0, "budget_remaining": 1}


@pytest.fixture(autouse=True)
def _reset():
    RecordingEngine.seen_timeouts = []
    yield


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(mod, "ApplicantEngineClient", RecordingEngine)
    return TestClient(_make_app())


def _read_seconds(timeout) -> float:
    assert isinstance(timeout, httpx.Timeout)
    return timeout.read


def test_run_gets_a_longer_read_timeout_than_the_client_default(client):
    r = client.post("/api/applicant/research/c1/run", json={"query": "Acme platform team"})
    assert r.status_code == 200

    assert len(RecordingEngine.seen_timeouts) == 1
    given = RecordingEngine.seen_timeouts[0]
    assert given is not None, "run must override the client's default timeout, not rely on it"
    assert _read_seconds(given) > _read_seconds(_DEFAULT_TIMEOUT)


def test_run_timeout_grows_with_a_longer_caller_supplied_max_time(client):
    client.post("/api/applicant/research/c1/run", json={"query": "x", "max_time": 30})
    short_timeout = RecordingEngine.seen_timeouts[-1]

    client.post("/api/applicant/research/c1/run", json={"query": "x", "max_time": 500})
    long_timeout = RecordingEngine.seen_timeouts[-1]

    # Genuinely overridable: a caller asking for a longer research budget gets a
    # correspondingly longer transport timeout, not one fixed constant.
    assert _read_seconds(long_timeout) > _read_seconds(short_timeout)
    # And still comfortably covers the requested research budget itself.
    assert _read_seconds(long_timeout) > 500


def test_run_timeout_has_a_sane_ceiling_for_a_runaway_max_time(client):
    client.post("/api/applicant/research/c1/run", json={"query": "x", "max_time": 10_000_000})
    given = RecordingEngine.seen_timeouts[-1]
    # Doesn't just blindly forward an absurd caller value forever.
    assert _read_seconds(given) < 3600


def test_cached_and_budget_reads_are_unaffected(client):
    """Only the heavy ``run`` write needs the longer window — the cheap reads
    keep riding the client's normal default (no timeout override)."""
    RecordingEngine.seen_timeouts = []
    client.get("/api/applicant/research/c1/cached", params={"query": "x"})
    client.get("/api/applicant/research/c1/budget")
    assert RecordingEngine.seen_timeouts == [None, None]
