"""Workspace callback port (Stage 2.5 engine -> workspace reverse channel).

The engine normally exposes surfaces that the front-door **workspace UI** calls
*into*. Stage 2.5 adds the *reverse*: the engine calls BACK into the workspace
``applicant-ui`` app (over the private docker network) to read things only the
front-door app knows — auto-detected interview calendar events (lane A), deep
research runs (lane B), and Cookbook-served local models (lane C).

This is the **driven (outbound) port** for that reverse direction. The adapter
(``adapters/workspace/http_workspace_client.py``) speaks HTTP to the workspace's
``/api/applicant/internal/*`` channel, presenting the shared secret token and an
owner attribution header. Every failure (timeout, connection refused, 4xx/5xx,
bad JSON) surfaces as :class:`WorkspaceError` — a raw httpx exception must never
escape — so callers can degrade gracefully.

When the shared secret is unset, :meth:`WorkspacePort.available` is False and
callers should skip the callback entirely (the channel is OFF).
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


class WorkspaceError(RuntimeError):
    """Raised for ANY failure talking to the workspace callback channel.

    Wraps transport errors (timeout / connection refused), non-2xx responses,
    and decode failures so the engine never sees a raw httpx exception.
    """

    def __init__(
        self,
        message: str,
        *,
        status: int | None = None,
        detail: Any = None,
        is_timeout: bool = False,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.status = status  # HTTP status, or None for transport-level failures
        self.detail = detail  # decoded error body when available
        self.is_timeout = is_timeout


@runtime_checkable
class WorkspacePort(Protocol):
    """Outbound port: the engine calling back into the front-door workspace app."""

    def available(self) -> bool:
        """True only when the channel is configured (shared secret present).

        Never raises and never touches the network — a cheap config gate so
        callers can skip the callback when the channel is OFF.
        """
        ...

    def ping(self, *, owner: str | None = None) -> dict:
        """Liveness + auth probe (``GET /api/applicant/internal/ping``).

        Returns the workspace's ping payload (``{"ok": True, "owner": ...}``) or
        raises :class:`WorkspaceError`.
        """
        ...

    # --- Lane-owned typed methods (raise WorkspaceError on failure) ----------
    def calendar_interviews(self, *, owner: str | None = None) -> dict:
        """LANE A — auto-detected interview calendar events for ``owner``."""
        ...

    def run_research(self, *, query: str, owner: str | None = None) -> dict:
        """LANE B — run deep research for ``owner``; returns the run/report."""
        ...

    def local_models(self, *, owner: str | None = None) -> dict:
        """LANE C — list Cookbook-served local models."""
        ...
