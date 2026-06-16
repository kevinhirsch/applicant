"""RemoteSessionControl driving port (FR-SANDBOX-3, FR-PREFILL-5).

Open/control a live session; the user submits themselves or authorizes the engine
to finish (friction-free). Live in Phase 2 (grayed until then).
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from applicant.core.ids import ApplicationId


@runtime_checkable
class RemoteSessionControlPort(Protocol):
    """Inbound port for live-session takeover and final-submit authorization."""

    def open_session(self, application_id: ApplicationId) -> str:
        """Return a one-click live-session (VNC) URL."""
        ...

    def authorize_engine_submit(self, application_id: ApplicationId) -> None:
        """Authorize friction-free engine final submit (FR-PREFILL-5)."""
        ...

    def mark_submitted_by_user(self, application_id: ApplicationId) -> None:
        """Record that the user submitted in the live session."""
        ...
