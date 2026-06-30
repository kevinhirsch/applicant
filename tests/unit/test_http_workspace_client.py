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
