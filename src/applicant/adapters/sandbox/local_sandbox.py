"""Local browser-sandbox adapter (FR-SANDBOX-1/4).

Provisions isolated, **ephemeral, per-application** browser sandboxes on the host
(Neko + neko-rooms in production) and exposes the swappable remote-view sub-port.
Sessions are **multi and independently controllable** (FR-SANDBOX-4); teardown is
idempotent so a crashed/duplicated teardown never errors.

A real Neko/neko-rooms control-plane (``RoomControl``) can be injected to create and
destroy ephemeral rooms per application — that is the clearly-marked boundary to the
real container. The DEFAULT lane uses the in-memory fake (no container), but the
session lifecycle, the one-click live-session URL, multi-session bookkeeping, and
remote-view sub-port swapping are all real and contract-tested today.
"""

from __future__ import annotations

from applicant.adapters.sandbox.remote_view import NekoRemoteView
from applicant.core.ids import ApplicationId, new_id
from applicant.ports.driven.sandbox import RemoteViewPort, SandboxSession


class LocalSandbox:
    """SandboxPort adapter — ephemeral per-application sandboxes (FR-SANDBOX-1/4)."""

    def __init__(
        self,
        remote_view: RemoteViewPort | None = None,
        *,
        room_control=None,
    ) -> None:
        self._remote_view = remote_view or NekoRemoteView()
        # Optional REAL neko-rooms control-plane (integration-gated); None -> fake.
        self._room_control = room_control
        #: session_id -> SandboxSession (live sessions only; popped on teardown).
        self._sessions: dict[str, SandboxSession] = {}
        #: application_id -> session_id (one active sandbox per application).
        self._by_application: dict[str, str] = {}

    def provision(self, application_id: ApplicationId) -> SandboxSession:
        """Spin up an isolated, ephemeral sandbox for the application (FR-SANDBOX-1).

        Each call mints a fresh session (multi-session: FR-SANDBOX-4) and binds a
        one-click remote-view URL. When a real room-control plane is injected, an
        ephemeral room is created and its signed URL is used.
        """
        session_id = f"sbx-{new_id()[:12]}"
        if self._room_control is not None:  # pragma: no cover - integration-gated
            view_url = self._room_control.create_room(session_id)
        else:
            view_url = self._remote_view.view_url(session_id)
        session = SandboxSession(
            session_id=session_id,
            application_id=application_id,
            remote_view_url=view_url,
        )
        self._sessions[session_id] = session
        self._by_application[str(application_id)] = session_id
        return session

    def teardown(self, session_id: str) -> None:
        """Destroy the ephemeral sandbox (FR-SANDBOX-4); idempotent."""
        session = self._sessions.pop(session_id, None)
        if session is not None:
            self._by_application.pop(str(session.application_id), None)
            # FR-SANDBOX-2: invalidate the live-session deep-link token/takeover so a
            # torn-down session's URL stops working (no dangling valid token).
            invalidate = getattr(self._remote_view, "invalidate", None)
            if callable(invalidate):
                invalidate(session_id)
            if self._room_control is not None:  # pragma: no cover - integration-gated
                self._room_control.destroy_room(session_id)

    def remote_view(self) -> RemoteViewPort:
        """Return the swappable remote-view sub-port (FR-SANDBOX-2)."""
        return self._remote_view

    # --- introspection helpers -------------------------------------------
    def active_sessions(self) -> list[SandboxSession]:
        """All currently live sandbox sessions (multi-session support)."""
        return list(self._sessions.values())

    def active_count(self) -> int:
        """Number of live sandboxes (drives the concurrency cap, FR-DUR-2)."""
        return len(self._sessions)

    def get(self, session_id: str) -> SandboxSession | None:
        return self._sessions.get(session_id)

    def for_application(self, application_id: ApplicationId) -> SandboxSession | None:
        """The live sandbox for an application, if any (one active per app)."""
        sid = self._by_application.get(str(application_id))
        return self._sessions.get(sid) if sid else None
