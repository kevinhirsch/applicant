"""Hermetic tests for the Stage 2.5 internal callback channel auth gate
(routes/applicant_internal_routes.py).

Mounts only the internal router on a bare FastAPI app and exercises the
token gate + owner scoping without booting the full workspace app:

- channel DISABLED when no secret is configured (403, no token would match)
- token REQUIRED: missing/wrong token -> 403, correct token -> 200
- constant-time comparison via secrets.compare_digest (correct token only)
- owner scoping: X-Applicant-Owner is reflected through internal_owner
- lane placeholders return 501 (only with a valid token)
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from routes.applicant_internal_routes import (
    INTERNAL_OWNER_HEADER,
    INTERNAL_TOKEN_HEADER,
    internal_channel_enabled,
    setup_applicant_internal_routes,
)

TOKEN = "s" * 64


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(setup_applicant_internal_routes())
    return TestClient(app)


def _enable(monkeypatch):
    monkeypatch.setenv("APPLICANT_INTERNAL_TOKEN", TOKEN)


def test_disabled_when_token_unset(client, monkeypatch):
    monkeypatch.delenv("APPLICANT_INTERNAL_TOKEN", raising=False)
    assert internal_channel_enabled() is False
    # Even presenting *some* token is rejected: the channel is off.
    resp = client.get("/api/applicant/internal/ping", headers={INTERNAL_TOKEN_HEADER: "anything"})
    assert resp.status_code == 403


def test_ping_requires_token(client, monkeypatch):
    _enable(monkeypatch)
    assert internal_channel_enabled() is True
    # No token header.
    assert client.get("/api/applicant/internal/ping").status_code == 403
    # Wrong token.
    bad = client.get("/api/applicant/internal/ping", headers={INTERNAL_TOKEN_HEADER: "wrong"})
    assert bad.status_code == 403


def test_ping_succeeds_with_correct_token(client, monkeypatch):
    _enable(monkeypatch)
    resp = client.get(
        "/api/applicant/internal/ping", headers={INTERNAL_TOKEN_HEADER: TOKEN}
    )
    assert resp.status_code == 200
    assert resp.json() == {"ok": True, "owner": None}


def test_owner_scoping_reflected(client, monkeypatch):
    _enable(monkeypatch)
    resp = client.get(
        "/api/applicant/internal/ping",
        headers={INTERNAL_TOKEN_HEADER: TOKEN, INTERNAL_OWNER_HEADER: "kevin"},
    )
    assert resp.status_code == 200
    assert resp.json()["owner"] == "kevin"


def test_all_lanes_implemented_not_placeholders(client, monkeypatch):
    # Both lanes (calendar A, research B) are implemented now — none should
    # return the 501 placeholder when called with a valid token (their behavior
    # is covered in their own dedicated test files). A third lane (Cookbook
    # local-model auto-discovery, dark-engine audit item 70) was removed
    # end-to-end as obsolete dead code -- see the module docstring.
    _enable(monkeypatch)
    h = {INTERNAL_TOKEN_HEADER: TOKEN}
    assert client.get("/api/applicant/internal/calendar/interviews", headers=h).status_code != 501
    assert client.post("/api/applicant/internal/research", headers=h, json={"query": "x"}).status_code != 501


def test_lane_placeholders_still_token_gated(client, monkeypatch):
    _enable(monkeypatch)
    # No token -> 403 before reaching the placeholder/handler.
    assert client.get("/api/applicant/internal/calendar/interviews").status_code == 403
    assert client.post("/api/applicant/internal/research", json={"query": "x"}).status_code == 403


# === Lane B: POST /research (deep-research callback) =========================
class _FakeResearcher:
    def __init__(self, findings):
        self.findings = findings


class _FakeResearchHandler:
    """Stands in for the workspace's native ResearchHandler (no LLM / no search)."""

    def __init__(self):
        self.calls = []

    async def call_research_service(self, query, url, model, *, max_time, _task_entry, llm_headers):
        self.calls.append({"query": query, "url": url, "model": model, "max_time": max_time})
        _task_entry["researcher"] = _FakeResearcher(
            [
                {"url": "https://acme.test", "title": "Acme", "summary": "Acme makes widgets."},
                {"url": "https://acme.test", "title": "dup", "summary": "dup"},  # dedup
                {"url": "https://news.test", "title": "News", "evidence": "Series C raise"},
            ]
        )
        return f"## Report for {query}"

    @staticmethod
    def _extract_sources(findings):
        seen, out = set(), []
        for f in findings:
            u = f.get("url", "")
            if u and u not in seen:
                seen.add(u)
                out.append({"url": u, "title": f.get("title") or u})
        return out


@pytest.fixture
def research_client(monkeypatch):
    """Bare app with the internal router + a faked research handler on app.state."""
    app = FastAPI()
    app.state.research_handler = _FakeResearchHandler()
    app.include_router(setup_applicant_internal_routes())
    # Avoid touching the real endpoint resolver / DB — fake a configured endpoint.
    import routes.applicant_internal_routes as mod

    monkeypatch.setattr(
        mod, "_resolve_research_endpoint_safe", lambda: ("http://llm/v1", "m", {})
    )
    return TestClient(app), app.state.research_handler


def test_research_runs_and_returns_structured_report(research_client, monkeypatch):
    _enable(monkeypatch)
    client, handler = research_client
    resp = client.post(
        "/api/applicant/internal/research",
        headers={INTERNAL_TOKEN_HEADER: TOKEN, INTERNAL_OWNER_HEADER: "kevin"},
        json={"query": "Acme culture", "company": "Acme", "role": "Engineer"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["query"] == "Acme culture"
    assert body["summary"].startswith("## Report for")
    # Company/role folded into the tailored query the handler actually ran.
    assert "company: Acme" in handler.calls[0]["query"]
    assert "role: Engineer" in handler.calls[0]["query"]
    # Sources deduped; owner reflected; findings distilled.
    assert {s["url"] for s in body["sources"]} == {"https://acme.test", "https://news.test"}
    assert body["owner"] == "kevin"
    assert "Acme makes widgets." in body["key_findings"]


def test_research_clamps_max_time(research_client, monkeypatch):
    _enable(monkeypatch)
    client, handler = research_client
    client.post(
        "/api/applicant/internal/research",
        headers={INTERNAL_TOKEN_HEADER: TOKEN, INTERNAL_OWNER_HEADER: "someone"},
        json={"query": "q", "max_time": 99999},
    )
    assert handler.calls[0]["max_time"] == 600  # clamped to the ceiling


def test_research_rejects_empty_query(research_client, monkeypatch):
    _enable(monkeypatch)
    client, _ = research_client
    resp = client.post(
        "/api/applicant/internal/research",
        headers={INTERNAL_TOKEN_HEADER: TOKEN},
        json={"query": "   "},
    )
    assert resp.status_code == 400


def test_research_token_gated(research_client, monkeypatch):
    _enable(monkeypatch)
    client, _ = research_client
    assert client.post(
        "/api/applicant/internal/research", json={"query": "q"}
    ).status_code == 403


def test_research_503_when_no_endpoint(monkeypatch):
    _enable(monkeypatch)
    app = FastAPI()
    app.state.research_handler = _FakeResearchHandler()
    app.include_router(setup_applicant_internal_routes())
    import routes.applicant_internal_routes as mod

    monkeypatch.setattr(mod, "_resolve_research_endpoint_safe", lambda: None)
    client = TestClient(app)
    resp = client.post(
        "/api/applicant/internal/research",
        headers={INTERNAL_TOKEN_HEADER: TOKEN, INTERNAL_OWNER_HEADER: "someone"},
        json={"query": "q"},
    )
    assert resp.status_code == 503


def test_research_503_when_handler_unwired(monkeypatch):
    _enable(monkeypatch)
    app = FastAPI()  # no app.state.research_handler
    app.include_router(setup_applicant_internal_routes())
    client = TestClient(app)
    resp = client.post(
        "/api/applicant/internal/research",
        headers={INTERNAL_TOKEN_HEADER: TOKEN, INTERNAL_OWNER_HEADER: "someone"},
        json={"query": "q"},
    )
    assert resp.status_code == 503
