"""Remote-view sub-port adapter (Neko/WebRTC default, noVNC alt) (FR-SANDBOX-2).

# STAGE B — owned by Phase 2; flesh out here.
"""

from __future__ import annotations


class NekoRemoteView:
    """RemoteViewPort adapter (stub until Phase 2)."""

    def view_url(self, session_id: str) -> str:
        raise NotImplementedError("STAGE B — Phase 2: Neko/noVNC session URL.")

    def authorize_takeover(self, session_id: str) -> None:
        raise NotImplementedError("STAGE B — Phase 2: hand control to the user.")
