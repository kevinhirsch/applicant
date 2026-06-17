"""httpx adapter for the engine -> workspace callback channel (Stage 2.5).

Implements :class:`~applicant.ports.driven.workspace.WorkspacePort` by speaking
HTTP to the front-door workspace app's ``/api/applicant/internal/*`` channel.

Trust model (mirrors ``workspace/routes/applicant_internal_routes.py``):

* The boundary is a **shared secret** (``APPLICANT_INTERNAL_TOKEN``), presented
  in the ``X-Applicant-Internal-Token`` header. The workspace compares it
  constant-time and DISABLES the channel entirely when unset.
* When the secret is unset here, :meth:`available` is False and the typed methods
  raise :class:`WorkspaceError` without ever touching the network — callers are
  expected to gate on ``available()`` and degrade gracefully.
* Each call may carry ``X-Applicant-Owner`` so the workspace scopes the work to
  one user (its AuthMiddleware attributes the request to that user).

Every transport error, non-2xx response, and decode failure is wrapped in
:class:`WorkspaceError`; a raw httpx exception MUST NOT escape (so a flaky or
down workspace never 500s the engine).
"""

from __future__ import annotations

from typing import Any

import httpx

from applicant.observability.logging import get_logger
from applicant.ports.driven.workspace import WorkspaceError

log = get_logger(__name__)

#: Default in-network address of the front-door workspace app (compose wires this).
DEFAULT_WORKSPACE_URL = "http://applicant-ui:7000"
INTERNAL_TOKEN_HEADER = "X-Applicant-Internal-Token"
INTERNAL_OWNER_HEADER = "X-Applicant-Owner"
_INTERNAL_PREFIX = "/api/applicant/internal"
_DEFAULT_TIMEOUT = 10.0


class HttpWorkspaceClient:
    """WorkspacePort adapter over httpx (sync; no new heavy deps)."""

    def __init__(
        self,
        *,
        base_url: str = DEFAULT_WORKSPACE_URL,
        token: str = "",
        timeout: float = _DEFAULT_TIMEOUT,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        # Strip a trailing slash so path joins are predictable.
        self._base_url = (base_url or DEFAULT_WORKSPACE_URL).rstrip("/")
        self._token = (token or "").strip()
        self._timeout = timeout
        # Injectable transport so tests use httpx.MockTransport (hermetic).
        self._transport = transport

    # --- config gate ------------------------------------------------------
    def available(self) -> bool:
        """True only when a shared secret is configured. Never raises/networks."""
        return bool(self._token)

    # --- internal request helper -----------------------------------------
    def _headers(self, owner: str | None) -> dict[str, str]:
        headers = {INTERNAL_TOKEN_HEADER: self._token}
        owner = (owner or "").strip()
        if owner:
            headers[INTERNAL_OWNER_HEADER] = owner
        return headers

    def _request(
        self,
        method: str,
        path: str,
        *,
        owner: str | None = None,
        json: Any = None,
    ) -> Any:
        """Make one request and return decoded JSON, or raise WorkspaceError.

        Guards the disabled channel up front (no network) and wraps every httpx
        failure mode in :class:`WorkspaceError`.
        """
        if not self.available():
            raise WorkspaceError(
                "Workspace callback channel disabled (APPLICANT_INTERNAL_TOKEN unset).",
            )
        url = f"{self._base_url}{_INTERNAL_PREFIX}{path}"
        try:
            with httpx.Client(timeout=self._timeout, transport=self._transport) as client:
                resp = client.request(method, url, headers=self._headers(owner), json=json)
        except httpx.TimeoutException as exc:
            log.warning("workspace_callback_timeout", path=path)
            raise WorkspaceError(
                f"Workspace request to {path} timed out.", is_timeout=True
            ) from exc
        except httpx.HTTPError as exc:  # connect refused, DNS, protocol, …
            log.warning("workspace_callback_transport_error", path=path, error=str(exc))
            raise WorkspaceError(
                f"Workspace request to {path} failed: {exc}"
            ) from exc

        if resp.status_code >= 400:
            detail: Any = None
            try:
                detail = resp.json()
            except Exception:
                detail = resp.text
            log.warning(
                "workspace_callback_http_error", path=path, status=resp.status_code
            )
            raise WorkspaceError(
                f"Workspace returned HTTP {resp.status_code} for {path}.",
                status=resp.status_code,
                detail=detail,
            )
        # 204 / empty body -> no JSON to decode.
        if resp.status_code == 204 or not resp.content:
            return None
        try:
            return resp.json()
        except Exception as exc:
            raise WorkspaceError(
                f"Workspace returned non-JSON for {path}.", status=resp.status_code
            ) from exc

    # --- public API -------------------------------------------------------
    def ping(self, *, owner: str | None = None) -> dict:
        return self._request("GET", "/ping", owner=owner)

    def calendar_interviews(self, *, owner: str | None = None) -> dict:
        """LANE A — auto-detected interview calendar events for ``owner``."""
        return self._request("GET", "/calendar/interviews", owner=owner)

    def run_research(self, *, query: str, owner: str | None = None) -> dict:
        """LANE B — run deep research for ``owner``; returns the run/report."""
        return self._request("POST", "/research", owner=owner, json={"query": query})

    def local_models(self, *, owner: str | None = None) -> dict:
        """LANE C — list Cookbook-served local models."""
        return self._request("GET", "/local-models", owner=owner)
