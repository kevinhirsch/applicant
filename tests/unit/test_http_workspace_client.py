"""Hermetic tests for the engine -> workspace callback client (Stage 2.5).

All HTTP is faked via ``httpx.MockTransport`` — no live network. Covers:
availability gate (token unset), header presentation (token + owner), happy-path
JSON decode for each typed method, and that every failure mode (timeout,
connection error, non-2xx, bad JSON) raises ``WorkspaceError`` rather than letting
a raw httpx exception escape.
"""

from __future__ import annotations

import httpx
import pytest

from applicant.adapters.workspace.http_workspace_client import (
    INTERNAL_OWNER_HEADER,
    INTERNAL_TOKEN_HEADER,
    HttpWorkspaceClient,
)
from applicant.ports.driven.workspace import WorkspaceError, WorkspacePort


def _client(handler, *, token="secret-token", base_url="http://applicant-ui:7000"):
    return HttpWorkspaceClient(
        base_url=base_url, token=token, transport=httpx.MockTransport(handler)
    )


def test_satisfies_port_protocol():
    assert isinstance(HttpWorkspaceClient(token="x"), WorkspacePort)


def test_available_false_when_token_unset():
    client = HttpWorkspaceClient(token="")
    assert client.available() is False


def test_available_true_when_token_set():
    assert HttpWorkspaceClient(token="abc").available() is True


def test_disabled_channel_raises_without_network():
    # No transport touched: token unset means available() is False and the call
    # raises WorkspaceError up front.
    client = HttpWorkspaceClient(token="")
    with pytest.raises(WorkspaceError):
        client.ping()


def test_ping_sends_token_and_owner_and_decodes():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["token"] = request.headers.get(INTERNAL_TOKEN_HEADER)
        seen["owner"] = request.headers.get(INTERNAL_OWNER_HEADER)
        return httpx.Response(200, json={"ok": True, "owner": "kev"})

    client = _client(handler)
    out = client.ping(owner="kev")
    assert out == {"ok": True, "owner": "kev"}
    assert seen["url"] == "http://applicant-ui:7000/api/applicant/internal/ping"
    assert seen["token"] == "secret-token"
    assert seen["owner"] == "kev"


def test_owner_header_omitted_when_not_provided():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["owner"] = request.headers.get(INTERNAL_OWNER_HEADER)
        return httpx.Response(200, json={"ok": True})

    _client(handler).ping()
    assert seen["owner"] is None


def test_typed_methods_hit_expected_paths():
    paths = []

    def handler(request: httpx.Request) -> httpx.Response:
        paths.append((request.method, request.url.path))
        if request.url.path.endswith("/research"):
            import json as _json

            body = _json.loads(request.content.decode() or "{}")
            assert body == {"query": "ml roles"}
            return httpx.Response(200, json={"run": "r1"})
        return httpx.Response(200, json={"items": []})

    client = _client(handler)
    assert client.calendar_interviews(owner="kev") == {"items": []}
    assert client.run_research(query="ml roles", owner="kev") == {"run": "r1"}
    assert ("GET", "/api/applicant/internal/calendar/interviews") in paths
    assert ("POST", "/api/applicant/internal/research") in paths


def test_create_calendar_event_posts_expected_payload():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        import json as _json

        seen["path"] = request.url.path
        seen["method"] = request.method
        seen["owner"] = request.headers.get(INTERNAL_OWNER_HEADER)
        seen["body"] = _json.loads(request.content.decode() or "{}")
        return httpx.Response(200, json={"ok": True, "uid": "abc123", "created": True})

    client = _client(handler)
    out = client.create_calendar_event(
        title="Interview invite: Acme Corp",
        start="2026-07-10T00:00:00",
        owner="kev",
        notes="Detected from an email",
        location="https://example.com/job",
        all_day=True,
        dedupe_key="app-1",
    )
    assert out == {"ok": True, "uid": "abc123", "created": True}
    assert seen["method"] == "POST"
    assert seen["path"] == "/api/applicant/internal/calendar/events"
    assert seen["owner"] == "kev"
    assert seen["body"] == {
        "title": "Interview invite: Acme Corp",
        "start": "2026-07-10T00:00:00",
        "all_day": True,
        "notes": "Detected from an email",
        "location": "https://example.com/job",
        "dedupe_key": "app-1",
    }


def test_create_calendar_event_omits_optional_fields_when_absent():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        import json as _json

        seen["body"] = _json.loads(request.content.decode() or "{}")
        return httpx.Response(200, json={"ok": True, "uid": "x", "created": True})

    client = _client(handler)
    client.create_calendar_event(title="Interview", start="2026-07-10T09:00:00")
    assert seen["body"] == {
        "title": "Interview",
        "start": "2026-07-10T09:00:00",
        "all_day": False,
    }


def test_create_calendar_event_disabled_channel_raises_without_network():
    client = HttpWorkspaceClient(token="")
    with pytest.raises(WorkspaceError):
        client.create_calendar_event(title="Interview", start="2026-07-10T09:00:00")


def test_http_error_raises_workspace_error_with_detail():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"detail": "Invalid internal token"})

    with pytest.raises(WorkspaceError) as exc:
        _client(handler).ping()
    assert exc.value.status == 403
    assert exc.value.detail == {"detail": "Invalid internal token"}


def test_timeout_raises_workspace_error_flagged_timeout():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("slow", request=request)

    with pytest.raises(WorkspaceError) as exc:
        _client(handler).ping()
    assert exc.value.is_timeout is True


def test_research_uses_longer_research_timeout():
    # Resilience fix: the snappy callbacks use the short default timeout, but the
    # multi-source research call gets its own (longer) HTTP read ceiling so a valid
    # run isn't cut off. httpx surfaces the per-call timeout in request.extensions.
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen[request.url.path] = request.extensions.get("timeout")
        return httpx.Response(200, json={"ok": True})

    client = HttpWorkspaceClient(
        base_url="http://applicant-ui:7000",
        token="secret-token",
        timeout=10.0,
        research_timeout=30.0,
        transport=httpx.MockTransport(handler),
    )
    client.ping()
    client.run_research(query="ml roles")

    ping_to = seen["/api/applicant/internal/ping"]["read"]
    research_to = seen["/api/applicant/internal/research"]["read"]
    assert ping_to == 10.0
    assert research_to == 30.0
    assert research_to > ping_to


def test_research_timeout_default_outlasts_workspace_budget(monkeypatch):
    # DISC-5 regression: the engine->workspace research INNER hop must default to a
    # transport ceiling that outlasts the workspace's own research budget (clamped up
    # to _RESEARCH_MAX_MAX_TIME=600s in applicant_internal_routes.py), matching the
    # front-door route's 630s read ceiling — not the snappy 30s that 502'd any run
    # longer than a trivial cache hit. Pinned so a regression is caught w/o a live run.
    monkeypatch.delenv("WORKSPACE_RESEARCH_TIMEOUT", raising=False)
    client = HttpWorkspaceClient(base_url="http://applicant-ui:7000", token="t")
    assert client._research_timeout == 630.0
    # And it must dwarf the snappy default used by the other callbacks.
    assert client._research_timeout > client._timeout


def test_research_timeout_env_override(monkeypatch):
    # Config-local (adapter-local) tuning: a deploy can widen/narrow the ceiling via
    # env without threading a new setting through the container.
    monkeypatch.setenv("WORKSPACE_RESEARCH_TIMEOUT", "720")
    client = HttpWorkspaceClient(base_url="http://applicant-ui:7000", token="t")
    assert client._research_timeout == 720.0


def test_research_timeout_env_ignored_when_invalid(monkeypatch):
    # A junk / non-positive override falls back to the sane default (never 0/negative,
    # which would instantly time out every research call).
    for bad in ("", "not-a-number", "0", "-5"):
        monkeypatch.setenv("WORKSPACE_RESEARCH_TIMEOUT", bad)
        client = HttpWorkspaceClient(base_url="http://applicant-ui:7000", token="t")
        assert client._research_timeout == 630.0


def test_research_default_timeout_is_applied_on_the_wire(monkeypatch):
    # End-to-end (hermetic): with no explicit research_timeout and no env override,
    # the actual per-call read timeout the client puts on the /research request is the
    # long default — proving the inner hop won't 502 a legitimate multi-minute run.
    monkeypatch.delenv("WORKSPACE_RESEARCH_TIMEOUT", raising=False)
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen[request.url.path] = request.extensions.get("timeout")
        return httpx.Response(200, json={"ok": True})

    client = HttpWorkspaceClient(
        base_url="http://applicant-ui:7000",
        token="secret-token",
        transport=httpx.MockTransport(handler),
    )
    client.run_research(query="ml roles")
    assert seen["/api/applicant/internal/research"]["read"] == 630.0


def test_research_timeout_sets_is_timeout():
    # An ephemeral timeout on the research call must still be distinguishable from a
    # connection-refused (is_timeout=True) so callers can retry vs. degrade.
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow research", request=request)

    with pytest.raises(WorkspaceError) as exc:
        _client(handler).run_research(query="ml roles")
    assert exc.value.is_timeout is True


def test_connection_error_raises_workspace_error():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    with pytest.raises(WorkspaceError) as exc:
        _client(handler).ping()
    assert exc.value.is_timeout is False
    assert exc.value.status is None


def test_non_json_body_raises_workspace_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="not json", headers={"content-type": "text/plain"})

    with pytest.raises(WorkspaceError):
        _client(handler).ping()


def test_base_url_trailing_slash_stripped():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        return httpx.Response(200, json={"ok": True})

    _client(handler, base_url="http://applicant-ui:7000/").ping()
    assert seen["url"] == "http://applicant-ui:7000/api/applicant/internal/ping"
