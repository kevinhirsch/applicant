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

import time
from collections.abc import Callable
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
#: Default per-call HTTP timeout for the SHORT callbacks (ping, calendar, local
#: models) — these answer quickly, so a tight bound surfaces a down workspace fast.
_DEFAULT_TIMEOUT = 10.0
#: Deep research is a multi-source synchronous LLM job, so it needs a much longer
#: HTTP read budget than the snappy callbacks. This is the *transport* ceiling; the
#: research *budget* is carried separately in the ``max_time`` body field.
_DEFAULT_RESEARCH_TIMEOUT = 30.0
#: HTTP statuses treated as transient here: a fronting proxy returns these while the
#: workspace container is restarting / redeploying, so the request never reached the
#: app. They are safe to retry; every other 4xx/5xx is surfaced immediately.
_RETRYABLE_STATUS = frozenset({502, 503})
#: How many EXTRA attempts (beyond the first) a retryable call gets. Bounded so a
#: persistently-down workspace still fails fast rather than hanging the tick.
_DEFAULT_RETRY_ATTEMPTS = 2
#: Base seconds for exponential backoff between attempts (0.5, 1.0, ...). Small,
#: because the callbacks run inside a scheduler tick and must not stall it for long.
_DEFAULT_RETRY_BACKOFF = 0.5


class HttpWorkspaceClient:
    """WorkspacePort adapter over httpx (sync; no new heavy deps)."""

    def __init__(
        self,
        *,
        base_url: str = DEFAULT_WORKSPACE_URL,
        token: str = "",
        timeout: float = _DEFAULT_TIMEOUT,
        research_timeout: float = _DEFAULT_RESEARCH_TIMEOUT,
        transport: httpx.BaseTransport | None = None,
        retry_attempts: int = _DEFAULT_RETRY_ATTEMPTS,
        retry_backoff: float = _DEFAULT_RETRY_BACKOFF,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        # Strip a trailing slash so path joins are predictable.
        self._base_url = (base_url or DEFAULT_WORKSPACE_URL).rstrip("/")
        self._token = (token or "").strip()
        self._timeout = timeout
        # Research gets its own (longer) transport ceiling; the snappy callbacks
        # keep the short default so a down workspace is detected quickly.
        self._research_timeout = research_timeout
        # Injectable transport so tests use httpx.MockTransport (hermetic).
        self._transport = transport
        # Bounded retry with exponential backoff for the idempotent/safe callbacks
        # (see ``_request``). ``sleep`` is injectable so tests run without real waits.
        self._retry_attempts = max(0, int(retry_attempts))
        self._retry_backoff = max(0.0, float(retry_backoff))
        self._sleep = sleep

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
        timeout: float | None = None,
        retry: bool = False,
    ) -> Any:
        """Make one request and return decoded JSON, or raise WorkspaceError.

        Guards the disabled channel up front (no network) and wraps every httpx
        failure mode in :class:`WorkspaceError`. ``timeout`` overrides the short
        default for the longer-running research call; a timeout raises a
        ``WorkspaceError`` with ``is_timeout=True`` so callers can tell an ephemeral
        timeout apart from a connection-refused / down workspace.

        When ``retry`` is set (only for idempotent/safe callbacks — see
        :meth:`run_research`) a *transient* failure is retried with bounded
        exponential backoff before giving up. Transient means the workspace was
        unreachable or restarting so the request never landed: a
        :class:`httpx.ConnectError` (refused/reset at connect), or a 502/503 from a
        fronting proxy. Timeouts are deliberately NOT retried — the request may be
        in flight, and re-issuing could duplicate non-idempotent server work. 4xx
        client errors and every other status are surfaced immediately. When retries
        are exhausted the success path and error surface are identical to a
        one-shot call.
        """
        if not self.available():
            raise WorkspaceError(
                "Workspace callback channel disabled (APPLICANT_INTERNAL_TOKEN unset).",
            )
        call_timeout = self._timeout if timeout is None else timeout
        url = f"{self._base_url}{_INTERNAL_PREFIX}{path}"
        # Total attempts = 1 (first try) + configured retries, but only when the
        # caller opted in AND a positive retry budget is configured.
        attempts = 1 + (self._retry_attempts if retry else 0)
        for attempt in range(attempts):
            last = attempt == attempts - 1
            try:
                with httpx.Client(
                    timeout=call_timeout, transport=self._transport
                ) as client:
                    resp = client.request(
                        method, url, headers=self._headers(owner), json=json
                    )
            except httpx.TimeoutException as exc:
                # Not retried: an in-flight request may already be doing work.
                log.warning("workspace_callback_timeout", path=path)
                raise WorkspaceError(
                    f"Workspace request to {path} timed out.", is_timeout=True
                ) from exc
            except httpx.ConnectError as exc:  # refused/reset at connect — never landed
                if not last:
                    log.warning(
                        "workspace_callback_retry",
                        path=path,
                        attempt=attempt + 1,
                        reason="connect_error",
                    )
                    self._sleep(self._backoff(attempt))
                    continue
                log.warning(
                    "workspace_callback_transport_error", path=path, error=str(exc)
                )
                raise WorkspaceError(
                    f"Workspace request to {path} failed: {exc}"
                ) from exc
            except httpx.HTTPError as exc:  # DNS, protocol, … — not transient here
                log.warning(
                    "workspace_callback_transport_error", path=path, error=str(exc)
                )
                raise WorkspaceError(
                    f"Workspace request to {path} failed: {exc}"
                ) from exc

            if resp.status_code in _RETRYABLE_STATUS and not last:
                log.warning(
                    "workspace_callback_retry",
                    path=path,
                    attempt=attempt + 1,
                    status=resp.status_code,
                )
                self._sleep(self._backoff(attempt))
                continue

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
        # Unreachable: the loop either returns or raises on the last attempt.
        raise WorkspaceError(f"Workspace request to {path} failed.")  # pragma: no cover

    def _backoff(self, attempt: int) -> float:
        """Exponential backoff seconds for a zero-based ``attempt`` (0.5, 1.0, ...)."""
        return self._retry_backoff * (2**attempt)

    # --- public API -------------------------------------------------------
    def ping(self, *, owner: str | None = None) -> dict:
        return self._request("GET", "/ping", owner=owner, retry=True)

    def calendar_interviews(self, *, owner: str | None = None) -> dict:
        """LANE A — auto-detected interview calendar events for ``owner``."""
        return self._request("GET", "/calendar/interviews", owner=owner, retry=True)

    def run_research(
        self,
        *,
        query: str,
        owner: str | None = None,
        company: str | None = None,
        role: str | None = None,
        context: str | None = None,
        max_time: int | None = None,
    ) -> dict:
        """LANE B — run deep research for ``owner``; returns the run/report.

        Optional ``company`` / ``role`` / ``context`` / ``max_time`` are sent in
        the body; the workspace folds them into the query and bounds the run.
        """
        body: dict[str, Any] = {"query": query}
        if company:
            body["company"] = company
        if role:
            body["role"] = role
        if context:
            body["context"] = context
        if max_time is not None:
            body["max_time"] = max_time
        # Use the longer research transport ceiling (NOT the snappy default) so a
        # legitimate multi-source run isn't cut off; ``max_time`` is the *research*
        # budget the workspace enforces, distinct from this HTTP read timeout.
        # ``retry=True``: a research callback is safe to re-issue when the workspace
        # was simply unreachable/restarting (connect refused or 502/503), so a
        # transient hop failure during a deploy no longer kills the whole run.
        return self._request(
            "POST",
            "/research",
            owner=owner,
            json=body,
            timeout=self._research_timeout,
            retry=True,
        )

    def create_calendar_event(
        self,
        *,
        title: str,
        start: str,
        owner: str | None = None,
        end: str | None = None,
        notes: str | None = None,
        location: str | None = None,
        all_day: bool = False,
        dedupe_key: str | None = None,
    ) -> dict:
        """LANE A write-back — create/update a calendar event for ``owner``.

        Closes the loop with :meth:`calendar_interviews` (read-only): callers
        (``PostSubmissionService``) POST a detected interview here so it actually
        lands on the owner's real workspace calendar. ``dedupe_key`` (typically
        the application id) lets the workspace update the SAME event on a repeat
        detection instead of minting a duplicate. Like every other typed method,
        this raises :class:`WorkspaceError` up front (no network) when the
        channel is disabled — callers MUST treat the write as best-effort.
        """
        body: dict[str, Any] = {"title": title, "start": start, "all_day": bool(all_day)}
        if end:
            body["end"] = end
        if notes:
            body["notes"] = notes
        if location:
            body["location"] = location
        if dedupe_key:
            body["dedupe_key"] = dedupe_key
        return self._request("POST", "/calendar/events", owner=owner, json=body)

    def recent_emails(self, *, owner: str | None = None, limit: int = 20) -> dict:
        """LANE C -- the owner's most recent inbox messages (dark-engine audit
        B2 item 10). ``PostSubmissionService.scan_inbox_for_outcomes`` feeds
        each through the rejection/interview/offer detectors. Raises
        :class:`WorkspaceError` up front (no network) when the channel is
        disabled -- callers MUST treat this as best-effort."""
        return self._request(
            "GET", _q("/emails/recent", {"limit": limit}), owner=owner, retry=True
        )

    # --- FR-MIND agent-memory bridge (memory / skills / recall) ---------------
    # These reach the front-door memory/skills substrate (workspace/services/memory/)
    # over the same token-gated channel; the bridge adapters in
    # ``adapters/memory/bridge.py`` call these and translate WorkspaceError -> empty.
    def memory_snapshot(
        self,
        *,
        owner: str | None = None,
        scope: str | None = None,
        campaign_id: str | None = None,
    ) -> dict:
        """FR-MIND-1 — curated-memory snapshot for ``owner`` (env + user split)."""
        params = _drop_none({"scope": scope, "campaign_id": campaign_id})
        return self._request("GET", _q("/memory/snapshot", params), owner=owner, retry=True)

    def memory_add(self, *, owner: str | None = None, body: dict) -> dict:
        """FR-MIND-1 — append one curated memory line."""
        return self._request("POST", "/memory/add", owner=owner, json=body)

    def memory_replace(self, *, owner: str | None = None, body: dict) -> dict:
        """FR-MIND-1 — replace the first entry matching ``find``."""
        return self._request("POST", "/memory/replace", owner=owner, json=body)

    def memory_remove(self, *, owner: str | None = None, body: dict) -> dict:
        """FR-MIND-1 — remove entries matching ``find``."""
        return self._request("POST", "/memory/remove", owner=owner, json=body)

    def skills_list(
        self,
        *,
        owner: str | None = None,
        scope: str | None = None,
        campaign_id: str | None = None,
    ) -> dict:
        """FR-MIND-2 — L0 skill metadata list (cheap; no bodies)."""
        params = _drop_none({"scope": scope, "campaign_id": campaign_id})
        return self._request("GET", _q("/skills", params), owner=owner, retry=True)

    def skill_load(self, name: str, *, owner: str | None = None) -> dict:
        """FR-MIND-2 — L1 full skill body for ``name``."""
        return self._request("GET", f"/skills/{name}", owner=owner, retry=True)

    def skill_create(self, *, owner: str | None = None, body: dict) -> dict:
        """FR-MIND-2 — author a new skill."""
        return self._request("POST", "/skills", owner=owner, json=body)

    def skill_patch(self, name: str, *, owner: str | None = None, body: dict) -> dict:
        """FR-MIND-2 — targeted update of named fields on a skill."""
        return self._request("PATCH", f"/skills/{name}", owner=owner, json=body)

    def skill_edit(self, name: str, *, owner: str | None = None, body: dict) -> dict:
        """FR-MIND-2 — full rewrite of a skill."""
        return self._request("PUT", f"/skills/{name}", owner=owner, json=body)

    def skill_delete(self, name: str, *, owner: str | None = None) -> dict:
        """FR-MIND-2 — delete a skill."""
        return self._request("DELETE", f"/skills/{name}", owner=owner)

    def recall(
        self,
        *,
        query: str,
        owner: str | None = None,
        limit: int = 5,
        scope: str | None = None,
        campaign_id: str | None = None,
    ) -> dict:
        """FR-MIND-3 — full-text/semantic recall over past runs."""
        params = _drop_none(
            {"q": query, "limit": limit, "scope": scope, "campaign_id": campaign_id}
        )
        return self._request("GET", _q("/recall", params), owner=owner, retry=True)


def _drop_none(d: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in d.items() if v is not None}


def _q(path: str, params: dict[str, Any]) -> str:
    """Append a query string to ``path`` (values stringified; no new deps)."""
    if not params:
        return path
    from urllib.parse import urlencode

    return f"{path}?{urlencode(params)}"
