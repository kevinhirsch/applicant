"""Lens 04 #8 — bounded retry for the engine -> workspace research callback.

The engine -> workspace callback client used to be one-shot: a transient hop
failure (connection refused/reset while the workspace restarts, or a 502/503 from
a fronting proxy mid-deploy) failed the whole research callback immediately. These
hermetic tests pin the fix: an idempotent/safe callback (``run_research`` and the
read-only GETs) retries a transient failure with bounded backoff, but 4xx client
errors and timeouts are NOT retried, and the retry budget is bounded.

All HTTP is faked via ``httpx.MockTransport`` and the backoff ``sleep`` is injected
as a recording no-op, so the suite is fully hermetic and fast.
"""

from __future__ import annotations

import httpx
import pytest

from applicant.adapters.workspace.http_workspace_client import HttpWorkspaceClient
from applicant.ports.driven.workspace import WorkspaceError


def _client(handler, *, sleeps=None, **kw):
    """Build a client whose backoff sleep records (never really waits)."""
    def _sleep(secs: float) -> None:
        if sleeps is not None:
            sleeps.append(secs)

    return HttpWorkspaceClient(
        base_url="http://applicant-ui:7000",
        token="secret-token",
        transport=httpx.MockTransport(handler),
        sleep=_sleep,
        **kw,
    )


def test_research_retries_connection_error_then_succeeds():
    """A connect refused/reset (workspace restarting) is retried, then succeeds."""
    calls = {"n": 0}
    sleeps: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            raise httpx.ConnectError("connection refused", request=request)
        return httpx.Response(200, json={"run": "r1"})

    out = _client(handler, sleeps=sleeps).run_research(query="ml roles", owner="kev")
    assert out == {"run": "r1"}
    assert calls["n"] == 2  # first attempt failed transiently, retry succeeded
    assert len(sleeps) == 1  # exactly one backoff between the two attempts
    assert sleeps[0] > 0


@pytest.mark.parametrize("status", [502, 503])
def test_research_retries_gateway_status_then_succeeds(status):
    """A 502/503 from a fronting proxy mid-deploy is retried, then succeeds."""
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(status, json={"detail": "restarting"})
        return httpx.Response(200, json={"run": "ok"})

    out = _client(handler).run_research(query="ml roles")
    assert out == {"run": "ok"}
    assert calls["n"] == 2


def test_client_4xx_is_not_retried():
    """A 4xx is a client error, not transient — surfaced immediately, no retry."""
    calls = {"n": 0}
    sleeps: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(400, json={"detail": "bad query"})

    with pytest.raises(WorkspaceError) as exc:
        _client(handler, sleeps=sleeps).run_research(query="ml roles")
    assert exc.value.status == 400
    assert calls["n"] == 1  # NOT retried
    assert sleeps == []


def test_403_is_not_retried():
    """Auth failures (bad internal token) must not be retried either."""
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(403, json={"detail": "Invalid internal token"})

    with pytest.raises(WorkspaceError) as exc:
        _client(handler).run_research(query="ml roles")
    assert exc.value.status == 403
    assert calls["n"] == 1


def test_retries_are_bounded_and_error_surface_unchanged():
    """A persistently-down workspace fails after a BOUNDED number of attempts, with
    the same error surface a one-shot call would have produced."""
    calls = {"n": 0}
    sleeps: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        raise httpx.ConnectError("refused", request=request)

    client = _client(handler, sleeps=sleeps, retry_attempts=2)
    with pytest.raises(WorkspaceError) as exc:
        client.run_research(query="ml roles")
    # 1 first attempt + 2 retries = 3 total, then give up.
    assert calls["n"] == 3
    assert len(sleeps) == 2
    # Exhausted-retry error surface is identical to the one-shot connect-error path.
    assert exc.value.is_timeout is False
    assert exc.value.status is None


def test_timeout_is_not_retried():
    """A read timeout may be in-flight non-idempotent work — never re-issued; the
    is_timeout flag is preserved so callers can distinguish it."""
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        raise httpx.ReadTimeout("slow research", request=request)

    with pytest.raises(WorkspaceError) as exc:
        _client(handler).run_research(query="ml roles")
    assert exc.value.is_timeout is True
    assert calls["n"] == 1  # NOT retried


def test_backoff_is_exponential_between_attempts():
    """Backoff grows (bounded exponential): the second wait is longer than the first."""
    calls = {"n": 0}
    sleeps: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] < 3:
            raise httpx.ConnectError("refused", request=request)
        return httpx.Response(200, json={"run": "late"})

    out = _client(handler, sleeps=sleeps, retry_attempts=3).run_research(query="q")
    assert out == {"run": "late"}
    assert len(sleeps) == 2
    assert sleeps[1] > sleeps[0]


def test_read_only_get_also_retries_transient():
    """The idempotent read-only callbacks share the retry policy (calendar read)."""
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(503, text="restarting")
        return httpx.Response(200, json={"items": []})

    out = _client(handler).calendar_interviews(owner="kev")
    assert out == {"items": []}
    assert calls["n"] == 2


def test_retry_disabled_when_budget_zero():
    """retry_attempts=0 restores strict one-shot behaviour for a transient failure."""
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        raise httpx.ConnectError("refused", request=request)

    with pytest.raises(WorkspaceError):
        _client(handler, retry_attempts=0).run_research(query="q")
    assert calls["n"] == 1
