"""Local browser-sandbox adapter (FR-SANDBOX-1/4).

# STAGE B — owned by Phase 2; flesh out here.

Provisions isolated, ephemeral browser sandboxes on the host (Neko + neko-rooms);
exposes the swappable remote-view sub-port.
"""

from __future__ import annotations

from applicant.adapters.sandbox.remote_view import NekoRemoteView
from applicant.core.ids import ApplicationId
from applicant.ports.driven.sandbox import RemoteViewPort, SandboxSession


class LocalSandbox:
    """SandboxPort adapter (stub until Phase 2)."""

    def __init__(self, remote_view: RemoteViewPort | None = None) -> None:
        self._remote_view = remote_view or NekoRemoteView()

    def provision(self, application_id: ApplicationId) -> SandboxSession:
        raise NotImplementedError("STAGE B — Phase 2: spin up isolated sandbox.")

    def teardown(self, session_id: str) -> None:
        raise NotImplementedError("STAGE B — Phase 2: destroy ephemeral sandbox.")

    def remote_view(self) -> RemoteViewPort:
        return self._remote_view
