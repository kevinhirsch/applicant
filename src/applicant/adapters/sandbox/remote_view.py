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
from typing import Protocol, runtime_checkable


class _TokenMixin:
    """Shared one-click token minting + takeover state for remote-view adapters."""

    def __init__(self) -> None:
        #: session_id -> per-session access token (one-click auth).
        self._tokens: dict[str, str] = {}
        #: session_id -> whether the user currently holds control.
        self._takeovers: dict[str, bool] = {}

    def _token(self, session_id: str) -> str:
        # Stable per-session token so the same session yields the same one-click URL.
        tok = self._tokens.get(session_id)
        if tok is None:
            tok = secrets.token_urlsafe(16)
            self._tokens[session_id] = tok
        return tok

    def authorize_takeover(self, session_id: str) -> None:
        """Hand control to the user (live takeover, FR-SANDBOX-3)."""
        self._takeovers[session_id] = True

    def revoke_takeover(self, session_id: str) -> None:
        """Return control to the engine after the human step (FR-SANDBOX-3)."""
        self._takeovers[session_id] = False

    def has_takeover(self, session_id: str) -> bool:
        """Introspection helper: has the user been handed control?"""
        return self._takeovers.get(session_id, False)


class NekoRemoteView(_TokenMixin):
    """RemoteViewPort adapter — Neko/WebRTC default (FR-SANDBOX-2)."""

    provider = "neko"

    def __init__(self, base_url: str = "https://sandbox.local/neko") -> None:
        super().__init__()
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

    def __init__(self, base_url: str = "https://sandbox.local/novnc") -> None:
        super().__init__()
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
