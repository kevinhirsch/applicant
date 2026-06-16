"""Local browser-sandbox adapter (FR-SANDBOX-1/4).

# STAGE B — owned by Phase 2; fleshed out as a thin scaffold.

Provisions isolated, **ephemeral, per-application** browser sandboxes on the host
(Neko + neko-rooms in production) and exposes the swappable remote-view sub-port.
Sessions are **multi and independently controllable** (FR-SANDBOX-4); teardown is
idempotent so a crashed/duplicated teardown never errors.

Scope note: thin scaffold — no real container is spun up. The session lifecycle,
the one-click live-session URL, and remote-view sub-port swapping are real.
"""

from __future__ import annotations

from applicant.adapters.sandbox.remote_view import NekoRemoteView
from applicant.core.ids import ApplicationId, new_id
from applicant.ports.driven.sandbox import RemoteViewPort, SandboxSession


class LocalSandbox:
    """SandboxPort adapter — ephemeral per-application sandboxes (FR-SANDBOX-1/4)."""

    def __init__(self, remote_view: RemoteViewPort | None = None) -> None:
        self._remote_view = remote_view or NekoRemoteView()
        #: session_id -> SandboxSession (live sessions only; popped on teardown).
        self._sessions: dict[str, SandboxSession] = {}

    def provision(self, application_id: ApplicationId) -> SandboxSession:
        """Spin up an isolated, ephemeral sandbox for the application (FR-SANDBOX-1).

        Each call mints a fresh session (multi-session: FR-SANDBOX-4) and binds a
        one-click remote-view URL.
        """
        session_id = f"sbx-{new_id()[:12]}"
        session = SandboxSession(
            session_id=session_id,
            application_id=application_id,
            remote_view_url=self._remote_view.view_url(session_id),
        )
        self._sessions[session_id] = session
        return session

    def teardown(self, session_id: str) -> None:
        """Destroy the ephemeral sandbox (FR-SANDBOX-4); idempotent."""
        self._sessions.pop(session_id, None)

    def remote_view(self) -> RemoteViewPort:
        """Return the swappable remote-view sub-port (FR-SANDBOX-2)."""
        return self._remote_view

    # --- introspection helpers -------------------------------------------
    def active_sessions(self) -> list[SandboxSession]:
        """All currently live sandbox sessions (multi-session support)."""
        return list(self._sessions.values())

    def get(self, session_id: str) -> SandboxSession | None:
        return self._sessions.get(session_id)
