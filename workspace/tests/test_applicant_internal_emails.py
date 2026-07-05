"""Hermetic tests for Stage 2.5 lane C — the owner's recent inbox, read for the
rejection/interview/offer scan sweep (dark-engine audit B2 item 10;
``routes/applicant_internal_routes.py::emails_recent`` + ``_read_owner_recent_emails``).

Two layers, both network-free:

1. The route itself (token-gated, owner-scoped) with
   ``_read_owner_recent_emails`` monkeypatched out entirely — proves auth/
   gating/degrade independent of the mailbox-loopback plumbing (mirrors
   ``test_applicant_internal_calendar.py``'s harness).
2. ``_read_owner_recent_emails`` itself, with ``httpx.AsyncClient`` swapped
   for an in-memory fake — proves it reuses the workspace's OWN
   ``GET /api/email/list`` + ``GET /api/email/read/{uid}`` loopback (never a
   second IMAP implementation), never marks a message read, and degrades to
   an empty list on any failure.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from routes import applicant_internal_routes as ir
from routes.applicant_internal_routes import (
    INTERNAL_OWNER_HEADER,
    INTERNAL_TOKEN_HEADER,
    setup_applicant_internal_routes,
)

TOKEN = "s" * 64


# ── 1. Route (token-gated, owner-scoped, mailbox layer faked) ────────────


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(setup_applicant_internal_routes())
    return TestClient(app)


@pytest.fixture
def fake_inbox(monkeypatch):
    """Replace the mailbox reader with an owner-keyed in-memory fake."""
    by_owner = {
        "kevin": [
            {
                "uid": "1",
                "subject": "Update on your application",
                "from": "recruiting@acme.example",
                "body": "Unfortunately we will not be proceeding.",
                "date": "2026-07-01T10:00:00+00:00",
            }
        ],
        "other": [
            {"uid": "2", "subject": "Hi", "from": "a@b.com", "body": "", "date": ""}
        ],
    }
    seen = {}

    async def _fake(owner, *, limit=20):
        seen["owner"] = owner
        seen["limit"] = limit
        return by_owner.get(owner, [])

    monkeypatch.setattr(ir, "_read_owner_recent_emails", _fake)
    return seen


def test_emails_recent_requires_token(client, monkeypatch):
    monkeypatch.setenv("APPLICANT_INTERNAL_TOKEN", TOKEN)
    assert client.get("/api/applicant/internal/emails/recent").status_code == 403
    bad = client.get(
        "/api/applicant/internal/emails/recent",
        headers={INTERNAL_TOKEN_HEADER: "wrong"},
    )
    assert bad.status_code == 403


def test_emails_recent_disabled_without_secret(client, monkeypatch):
    monkeypatch.delenv("APPLICANT_INTERNAL_TOKEN", raising=False)
    resp = client.get(
        "/api/applicant/internal/emails/recent",
        headers={INTERNAL_TOKEN_HEADER: TOKEN},
    )
    assert resp.status_code == 403


def test_emails_recent_requires_owner_attribution(client, monkeypatch):
    monkeypatch.setenv("APPLICANT_INTERNAL_TOKEN", TOKEN)
    resp = client.get(
        "/api/applicant/internal/emails/recent",
        headers={INTERNAL_TOKEN_HEADER: TOKEN},
    )
    assert resp.status_code == 400


def test_emails_recent_owner_scoped(client, monkeypatch, fake_inbox):
    monkeypatch.setenv("APPLICANT_INTERNAL_TOKEN", TOKEN)
    resp = client.get(
        "/api/applicant/internal/emails/recent",
        headers={INTERNAL_TOKEN_HEADER: TOKEN, INTERNAL_OWNER_HEADER: "kevin"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["emails"]) == 1
    assert body["emails"][0]["subject"] == "Update on your application"
    # The reader was scoped to the attributed owner — never a body field.
    assert fake_inbox["owner"] == "kevin"


def test_emails_recent_read_failure_degrades(client, monkeypatch):
    monkeypatch.setenv("APPLICANT_INTERNAL_TOKEN", TOKEN)

    async def _boom(owner, *, limit=20):
        raise RuntimeError("mailbox down")

    monkeypatch.setattr(ir, "_read_owner_recent_emails", _boom)
    resp = client.get(
        "/api/applicant/internal/emails/recent",
        headers={INTERNAL_TOKEN_HEADER: TOKEN, INTERNAL_OWNER_HEADER: "someone"},
    )
    assert resp.status_code == 200
    assert resp.json() == {"emails": []}


def test_emails_recent_unconfigured_mailbox_is_empty_not_an_error(client, monkeypatch, fake_inbox):
    monkeypatch.setenv("APPLICANT_INTERNAL_TOKEN", TOKEN)
    resp = client.get(
        "/api/applicant/internal/emails/recent",
        headers={INTERNAL_TOKEN_HEADER: TOKEN, INTERNAL_OWNER_HEADER: "nobody-configured"},
    )
    assert resp.status_code == 200
    assert resp.json() == {"emails": []}


# ── 2. ``_read_owner_recent_emails`` itself — the loopback reuse ─────────


class _FakeResponse:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


class _FakeAsyncClient:
    """Stands in for ``httpx.AsyncClient`` — no network, no real mailbox."""

    calls: list = []
    list_payload: dict = {"emails": []}
    read_payloads: dict = {}  # uid -> body dict
    list_status: int = 200

    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return None

    async def get(self, url, params=None, headers=None):
        _FakeAsyncClient.calls.append((url, params, headers))
        if url.endswith("/api/email/list"):
            return _FakeResponse(_FakeAsyncClient.list_status, _FakeAsyncClient.list_payload)
        uid = url.rsplit("/", 1)[-1]
        return _FakeResponse(200, _FakeAsyncClient.read_payloads.get(uid, {"body": ""}))


@pytest.fixture(autouse=True)
def _reset_fake_client():
    _FakeAsyncClient.calls = []
    _FakeAsyncClient.list_payload = {"emails": []}
    _FakeAsyncClient.read_payloads = {}
    _FakeAsyncClient.list_status = 200
    yield


@pytest.fixture
def fake_httpx(monkeypatch):
    monkeypatch.setattr("httpx.AsyncClient", _FakeAsyncClient)
    return _FakeAsyncClient


@pytest.mark.asyncio
async def test_reads_list_then_body_via_the_workspaces_own_mailbox_endpoints(
    fake_httpx, monkeypatch
):
    monkeypatch.setenv("APPLICANT_INTERNAL_TOKEN", TOKEN)
    _FakeAsyncClient.list_payload = {
        "emails": [
            {"uid": "42", "subject": "Re: Acme application", "from_address": "hr@acme.example"}
        ]
    }
    _FakeAsyncClient.read_payloads = {"42": {"body": "Thanks for applying."}}

    out = await ir._read_owner_recent_emails("kevin", limit=5)

    assert out == [
        {
            "uid": "42",
            "subject": "Re: Acme application",
            "from": "hr@acme.example",
            "body": "Thanks for applying.",
            "date": "",
        }
    ]
    # Reused the workspace's OWN two mailbox endpoints, in order.
    list_call = fake_httpx.calls[0]
    assert list_call[0].endswith("/api/email/list")
    assert list_call[1]["limit"] == 5
    read_call = fake_httpx.calls[1]
    assert read_call[0].endswith("/api/email/read/42")
    # NEVER marks a message read — a background scan mustn't disturb the
    # owner's real unread state.
    assert read_call[1]["mark_seen"] == "false"
    # Presented the SAME internal-token/owner headers the route itself was
    # gated on — the loopback authenticates via the existing bypass.
    assert list_call[2][INTERNAL_TOKEN_HEADER] == TOKEN
    assert list_call[2][INTERNAL_OWNER_HEADER] == "kevin"


@pytest.mark.asyncio
async def test_list_failure_status_degrades_to_empty(fake_httpx, monkeypatch):
    monkeypatch.setenv("APPLICANT_INTERNAL_TOKEN", TOKEN)
    _FakeAsyncClient.list_status = 500

    out = await ir._read_owner_recent_emails("kevin")

    assert out == []


@pytest.mark.asyncio
async def test_transport_exception_degrades_to_empty(monkeypatch):
    monkeypatch.setenv("APPLICANT_INTERNAL_TOKEN", TOKEN)

    class _BoomClient:
        def __init__(self, *a, **k):
            raise RuntimeError("connection refused")

    monkeypatch.setattr("httpx.AsyncClient", _BoomClient)

    out = await ir._read_owner_recent_emails("kevin")

    assert out == []


@pytest.mark.asyncio
async def test_body_read_failure_still_returns_the_email_with_empty_body(fake_httpx, monkeypatch):
    """A body-fetch hiccup for one message must not drop the whole sweep --
    it degrades to an empty body for that one row."""
    monkeypatch.setenv("APPLICANT_INTERNAL_TOKEN", TOKEN)
    _FakeAsyncClient.list_payload = {"emails": [{"uid": "1", "subject": "Hi", "from_address": "a@b.com"}]}

    class _PartialFailClient(_FakeAsyncClient):
        async def get(self, url, params=None, headers=None):
            if url.endswith("/api/email/read/1"):
                raise RuntimeError("read timed out")
            return await super().get(url, params=params, headers=headers)

    monkeypatch.setattr("httpx.AsyncClient", _PartialFailClient)

    out = await ir._read_owner_recent_emails("kevin")

    assert len(out) == 1
    assert out[0]["subject"] == "Hi"
    assert out[0]["body"] == ""


@pytest.mark.asyncio
async def test_limit_is_bounded_to_the_max(fake_httpx, monkeypatch):
    monkeypatch.setenv("APPLICANT_INTERNAL_TOKEN", TOKEN)

    await ir._read_owner_recent_emails("kevin", limit=9999)

    assert fake_httpx.calls[0][1]["limit"] == ir._RECENT_EMAILS_MAX
