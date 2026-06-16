"""Remote-view sub-port adapter (Neko/WebRTC default, noVNC alt) (FR-SANDBOX-2).

The remote-view provider is its own **swappable sub-port** (Neko <-> noVNC <->
future). Both adapters below mint a **one-click live-session URL** for a session and
authorize/revoke a live takeover (FR-SANDBOX-3). The URL is a real, single-click
deep link: it carries a short-lived, per-session **access token** so the link can be
sent in a notification and opened straight into the controllable session without a
second auth step (this fills the Phase 2a "live-session URL provider" seam).

The default lane mints tokens in-process (no network). The real Neko/neko-rooms
control plane (room create/destroy + signed join URL) sits behind the clearly-marked
:class:`NekoRoomsControl` boundary, exercised only by an integration-gated test.
"""

from __future__ import annotations

import secrets
import time
from typing import Protocol, runtime_checkable

#: Default lifetime for a one-click live-session token (seconds) (FR-SANDBOX-2).
#: A deep link sent in a notification is short-lived: after this TTL the token is
#: rejected and a fresh ``view_url`` mints a new one. Override per-adapter.
DEFAULT_TOKEN_TTL_SECONDS = 15 * 60


class TokenExpired(Exception):
    """Raised when a one-click live-session token has expired or been revoked."""


class _TokenMixin:
    """Shared one-click token minting + takeover state for remote-view adapters."""

    #: Token lifetime; subclasses pass through ``token_ttl_seconds`` at construction.
    _token_ttl: float = DEFAULT_TOKEN_TTL_SECONDS

    def __init__(self, *, token_ttl_seconds: float = DEFAULT_TOKEN_TTL_SECONDS) -> None:
        #: session_id -> (token, expires_at_monotonic). Tokens carry a TTL so a
        #: torn-down/stale deep link stops working (FR-SANDBOX-2).
        self._tokens: dict[str, tuple[str, float]] = {}
        #: session_id -> whether the user currently holds control.
        self._takeovers: dict[str, bool] = {}
        self._token_ttl = float(token_ttl_seconds)

    def _now(self) -> float:
        return time.monotonic()

    def _token(self, session_id: str) -> str:
        """Mint (or refresh) a short-lived per-session token (FR-SANDBOX-2).

        Re-issues a fresh token + expiry whenever the current one is missing or has
        expired, so a freshly-requested ``view_url`` is always usable for the TTL.
        """
        entry = self._tokens.get(session_id)
        if entry is None or entry[1] <= self._now():
            tok = secrets.token_urlsafe(16)
            self._tokens[session_id] = (tok, self._now() + self._token_ttl)
            return tok
        return entry[0]

    def token_valid(self, session_id: str, token: str) -> bool:
        """Whether ``token`` is the live, unexpired, non-revoked session token."""
        entry = self._tokens.get(session_id)
        if entry is None:
            return False
        tok, expires_at = entry
        return tok == token and expires_at > self._now()

    def authorize_takeover(self, session_id: str) -> None:
        """Hand control to the user (live takeover, FR-SANDBOX-3)."""
        self._takeovers[session_id] = True

    def revoke_takeover(self, session_id: str) -> None:
        """Return control to the engine + INVALIDATE the deep link (FR-SANDBOX-3).

        Revoking control also drops the session's access token so the previously
        minted one-click URL stops working (it must be re-issued to re-enter).
        """
        self._takeovers[session_id] = False
        self._tokens.pop(session_id, None)

    def invalidate(self, session_id: str) -> None:
        """Drop all token/takeover state for a session (called on teardown)."""
        self._tokens.pop(session_id, None)
        self._takeovers.pop(session_id, None)

    def has_takeover(self, session_id: str) -> bool:
        """Introspection helper: has the user been handed control?"""
        return self._takeovers.get(session_id, False)


class NekoRemoteView(_TokenMixin):
    """RemoteViewPort adapter — Neko/WebRTC default (FR-SANDBOX-2)."""

    provider = "neko"

    def __init__(
        self,
        base_url: str = "https://sandbox.local/neko",
        *,
        token_ttl_seconds: float = DEFAULT_TOKEN_TTL_SECONDS,
    ) -> None:
        super().__init__(token_ttl_seconds=token_ttl_seconds)
        self._base_url = base_url.rstrip("/")

    def view_url(self, session_id: str) -> str:
        """Return a one-click, token-bearing live-session URL (FR-SANDBOX-2)."""
        return f"{self._base_url}/{session_id}?token={self._token(session_id)}"


class NoVncRemoteView(_TokenMixin):
    """RemoteViewPort adapter — noVNC alternative, proving sub-port swappability.

    Honors the identical contract as :class:`NekoRemoteView` so the sandbox can
    swap providers (Neko <-> noVNC) without any core or service change.
    """

    provider = "novnc"

    def __init__(
        self,
        base_url: str = "https://sandbox.local/novnc",
        *,
        token_ttl_seconds: float = DEFAULT_TOKEN_TTL_SECONDS,
    ) -> None:
        super().__init__(token_ttl_seconds=token_ttl_seconds)
        self._base_url = base_url.rstrip("/")

    def view_url(self, session_id: str) -> str:
        return f"{self._base_url}/vnc.html?token={self._token(session_id)}&session={session_id}"


# --- real Neko/neko-rooms control plane (REAL, integration-gated) -----------
@runtime_checkable
class RoomControl(Protocol):
    """The swappable control-plane behind a remote-view provider (room lifecycle)."""

    def create_room(self, session_id: str) -> str: ...

    def destroy_room(self, session_id: str) -> None: ...


class NekoRoomsControl:
    """REAL neko-rooms control-plane client (FR-SANDBOX-1/2) — integration-gated.

    Talks to a running neko-rooms API to create/destroy an ephemeral Neko room per
    application and returns its signed join URL. The HTTP client is imported lazily
    so the default lane never needs the dependency or a running server; an
    integration test (skipped without ``NEKO_ROOMS_URL``) drives it.
    """

    def __init__(self, api_url: str, api_token: str = "") -> None:  # pragma: no cover
        self._api_url = api_url.rstrip("/")
        self._api_token = api_token

    def create_room(self, session_id: str) -> str:  # pragma: no cover - integration
        import httpx

        headers = {"Authorization": f"Bearer {self._api_token}"} if self._api_token else {}
        resp = httpx.post(
            f"{self._api_url}/api/rooms",
            json={"name": session_id, "max_connections": 2},
            headers=headers,
            timeout=30.0,
        )
        resp.raise_for_status()
        return resp.json().get("url", f"{self._api_url}/room/{session_id}")

    def destroy_room(self, session_id: str) -> None:  # pragma: no cover - integration
        import httpx

        headers = {"Authorization": f"Bearer {self._api_token}"} if self._api_token else {}
        httpx.delete(
            f"{self._api_url}/api/rooms/{session_id}", headers=headers, timeout=30.0
        )
