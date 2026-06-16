"""Remote-view sub-port adapter (Neko/WebRTC default, noVNC alt) (FR-SANDBOX-2).

# STAGE B — owned by Phase 2; fleshed out as a thin scaffold.

The remote-view provider is its own **swappable sub-port** (Neko <-> noVNC <->
future). Both adapters below build a one-click live-session URL for a session and
authorize a live takeover. Real providers wire WebRTC/VNC transport here; the
shape (URL minting + takeover authorization + multi-session) is real today.
"""

from __future__ import annotations


class NekoRemoteView:
    """RemoteViewPort adapter — Neko/WebRTC default (FR-SANDBOX-2)."""

    provider = "neko"

    def __init__(self, base_url: str = "https://sandbox.local/neko") -> None:
        self._base_url = base_url.rstrip("/")
        #: session_id -> whether the user currently holds control.
        self._takeovers: dict[str, bool] = {}

    def view_url(self, session_id: str) -> str:
        """Return a one-click live-session URL for ``session_id`` (FR-SANDBOX-2)."""
        return f"{self._base_url}/{session_id}"

    def authorize_takeover(self, session_id: str) -> None:
        """Hand control to the user (live takeover, FR-SANDBOX-3)."""
        self._takeovers[session_id] = True

    def has_takeover(self, session_id: str) -> bool:
        """Introspection helper: has the user been handed control?"""
        return self._takeovers.get(session_id, False)


class NoVncRemoteView:
    """RemoteViewPort adapter — noVNC alternative, proving sub-port swappability.

    Honors the identical contract as :class:`NekoRemoteView` so the sandbox can
    swap providers (Neko <-> noVNC) without any core or service change.
    """

    provider = "novnc"

    def __init__(self, base_url: str = "https://sandbox.local/novnc") -> None:
        self._base_url = base_url.rstrip("/")
        self._takeovers: dict[str, bool] = {}

    def view_url(self, session_id: str) -> str:
        return f"{self._base_url}/vnc.html?token={session_id}"

    def authorize_takeover(self, session_id: str) -> None:
        self._takeovers[session_id] = True

    def has_takeover(self, session_id: str) -> bool:
        return self._takeovers.get(session_id, False)
