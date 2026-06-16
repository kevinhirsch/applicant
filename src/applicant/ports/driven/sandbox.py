"""Sandbox + RemoteView ports (FR-SANDBOX-1/2/3/4).

Each active application runs in an isolated browser sandbox on the host. The
remote-view provider is its own **swappable sub-port** (Neko/WebRTC default,
noVNC alternative). Sessions are multi, independently controllable, ephemeral.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from applicant.core.ids import ApplicationId


@dataclass(frozen=True)
class SandboxSession:
    session_id: str
    application_id: ApplicationId
    remote_view_url: str | None = None


@runtime_checkable
class RemoteViewPort(Protocol):
    """Swappable remote-view sub-port (Neko <-> noVNC) (FR-SANDBOX-2)."""

    def view_url(self, session_id: str) -> str:
        """Return a one-click live-session URL for ``session_id``."""
        ...

    def authorize_takeover(self, session_id: str) -> None:
        """Hand control to the user (live takeover)."""
        ...

    def revoke_takeover(self, session_id: str) -> None:
        """Return control to the engine (user finished the human step)."""
        ...

    def has_takeover(self, session_id: str) -> bool:
        """Whether the user currently holds live control of ``session_id``."""
        ...


@runtime_checkable
class SandboxPort(Protocol):
    """Outbound port for provisioning isolated browser sandboxes."""

    def provision(self, application_id: ApplicationId) -> SandboxSession:
        """Spin up an isolated, ephemeral sandbox for the application (FR-SANDBOX-1)."""
        ...

    def teardown(self, session_id: str) -> None:
        """Destroy the ephemeral sandbox (FR-SANDBOX-4)."""
        ...

    def remote_view(self) -> RemoteViewPort:
        """Return the swappable remote-view sub-port."""
        ...

    def active_sessions(self) -> list[SandboxSession]:
        """All currently live sandbox sessions (multi-session, FR-SANDBOX-4)."""
        ...
