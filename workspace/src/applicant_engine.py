# src/applicant_engine.py
"""HTTP client for the Applicant ENGINE (the internal ``api`` service).

The front-door workspace UI is the owner's own app; the *engine* is the
job-application engine that lives behind ``http://api:8000`` (internal only in
the prod compose). This module is the SHARED FOUNDATION the four Stage-2 wiring
lanes build on, so they all talk to the engine through one client instead of
hand-rolling URLs and error handling four different ways.

Design goals (kept deliberately small):

* httpx only — no new deps (matches the httpx usage already in ``src/``, e.g.
  ``integrations.py`` / ``embeddings.py``).
* Reads ``ENGINE_URL`` (default ``http://api:8000``); every request is relative
  to that base.
* Async-first (FastAPI route handlers are ``async``) with a thin sync helper for
  non-async callers (scripts, startup probes).
* Clean error handling: timeouts / connection failures / HTTP errors all surface
  as :class:`EngineError` (a typed exception) — the client NEVER lets an httpx
  exception escape, so a wired UI surface degrades gracefully instead of 500ing.
* ``engine_available()`` pings the engine ``/healthz`` so the feature layer can
  report which surfaces are reachable.

Each method maps 1:1 to an engine endpoint group documented in
``workspace/APPLICANT_INTEGRATION.md``. Lanes add methods here as they wire new
surfaces; keep them small and typed.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Optional

import httpx

logger = logging.getLogger(__name__)

#: Default in-network address of the engine (see docker/docker-compose.prod.yml).
DEFAULT_ENGINE_URL = "http://api:8000"

#: Conservative timeouts. The engine is in-network, so a slow response almost
#: always means it is down/overloaded — fast-fail to a typed error rather than
#: hang a UI request behind it. Read stays generous for LLM-backed endpoints
#: (chat / document generation) which legitimately take a few seconds.
_DEFAULT_TIMEOUT = httpx.Timeout(connect=3.0, read=30.0, write=10.0, pool=3.0)


def engine_base_url() -> str:
    """Resolve the engine base URL from the environment (trailing slash stripped)."""
    return (os.getenv("ENGINE_URL") or DEFAULT_ENGINE_URL).rstrip("/")


def build_shared_http_client() -> httpx.AsyncClient:
    """Build the ONE app-lifetime ``httpx.AsyncClient`` the workspace app holds
    for the life of the process (``workspace/app.py``'s startup event stores it
    as ``app.state.http_client``; the shutdown event calls ``aclose()`` on it).

    Uses the exact same ``base_url``/``timeout`` defaults an un-injected
    :class:`ApplicantEngineClient` would construct on its own, so passing this
    client in via ``ApplicantEngineClient(client=...)`` is behaviourally
    identical to today's per-call construction — just with a pooled,
    keep-alive-reusing connection instead of a fresh one per request (perf
    lens finding #3: ~180 call sites otherwise pay a new TCP/TLS handshake on
    every single workspace→engine proxy hop).
    """
    return httpx.AsyncClient(base_url=engine_base_url(), timeout=_DEFAULT_TIMEOUT)


def shared_engine_http_client(request: Any) -> Optional[httpx.AsyncClient]:
    """Reusable per-request dependency: resolve the shared app-lifetime
    ``httpx.AsyncClient`` a route should ride, or ``None`` when there isn't one.

    ``request`` is a FastAPI/Starlette ``Request`` (typed ``Any`` here so this
    module keeps its only hard dependency on ``httpx`` — see the module
    docstring). Reads ``request.app.state.http_client`` (set up by
    ``workspace/app.py``'s startup event via :func:`build_shared_http_client`).

    Deliberately returns the raw client rather than wrapping it in an
    :class:`ApplicantEngineClient` itself: call sites keep constructing
    ``ApplicantEngineClient(client=shared_engine_http_client(request))``
    through their OWN already-imported ``ApplicantEngineClient`` name. That
    keeps this a pure one-kwarg, mechanical change per call site — safe to
    land incrementally across the ~180 existing ``async with
    ApplicantEngineClient()`` sites without touching their imports, and it
    means any test that patches a route module's ``ApplicantEngineClient``
    (the established convention — see e.g. ``test_applicant_portal_routes.py``)
    keeps working unchanged, since the patched name is still what gets called.
    Returns ``None`` (⇒ falls back to :class:`ApplicantEngineClient`'s own
    private pool, unchanged behaviour) when ``app.state.http_client`` was never
    set up — e.g. a bare test app that doesn't run the real startup event.
    """
    app_obj = getattr(request, "app", None)
    state = getattr(app_obj, "state", None)
    return getattr(state, "http_client", None) if state is not None else None


class EngineError(Exception):
    """Any failure talking to the engine (timeout, connection, or HTTP 4xx/5xx).

    Carries enough context for a route handler to decide what to show the user
    without re-inspecting raw httpx objects.

    ``status`` is the HTTP status code for an error *response* (or ``None`` for a
    transport-level failure such as a timeout, where no response was received).
    """

    def __init__(
        self,
        message: str,
        *,
        status: Optional[int] = None,
        detail: Any = None,
        is_timeout: bool = False,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.status = status
        self.detail = detail
        self.is_timeout = is_timeout

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"EngineError(status={self.status!r}, is_timeout={self.is_timeout!r}, message={self.message!r})"


#: HTTP statuses that mean "the engine is UP but is refusing this read because a
#: client-correctable setup gate is in force" — NOT that the engine is offline.
#: 401/403 = auth/permission gate, 409 = a precondition gate (e.g. automated work
#: blocked until onboarding + model + notification channels are configured, or no
#: campaign exists yet), 422 = the engine rejected the input. These are honestly
#: surfaced as a GATE with the engine's own plain-language message, so the UI can
#: tell the owner what to fix instead of falsely reporting "engine offline".
GATE_STATUSES = frozenset({401, 403, 409, 422})


def soft_degrade(exc: "EngineError", base: Optional[dict] = None) -> dict:
    """Classify a soft-degrading read failure as GATED vs TRANSPORT-OFFLINE.

    A read endpoint that wants to degrade gracefully (return a well-formed empty
    body rather than 5xx) calls this with the caught :class:`EngineError` and the
    endpoint's own base payload (campaign id, empty ``items``, etc.). It returns a
    *new* dict layering the right honesty flags on top of ``base``:

    * A gate (status in :data:`GATE_STATUSES`) → ``{"gated": True, "message": …,
      "engine_available": True}``. The engine is reachable; the owner needs to
      finish setup / has no permission / supplied a bad value. The engine's own
      plain-language detail is forwarded as ``message`` so the UI can show it.
    * A transport failure (``status is None``) or any other status (e.g. 404/5xx)
      → ``{"engine_available": False}``. The engine is genuinely unreachable (or
      returned something we can't honestly call a gate), so the offline empty
      state is correct.

    The proxy stays a forwarder: the engine owns the gate rules and the message;
    this only routes the failure to the honest empty state.
    """
    out = dict(base or {})
    if exc.status in GATE_STATUSES:
        message = exc.detail if isinstance(exc.detail, str) and exc.detail else exc.message
        out["engine_available"] = True
        out["gated"] = True
        out["message"] = message or "Setup is required before this is available."
    else:
        out["engine_available"] = False
    return out


class ApplicantEngineClient:
    """Async httpx client for the engine API.

    Use as an async context manager so the underlying connection pool is reused
    and cleanly closed::

        async with ApplicantEngineClient() as engine:
            status = await engine.setup_status()

    Or share a single long-lived instance and call :meth:`aclose` on shutdown.
    The default ``base_url`` comes from ``ENGINE_URL`` so tests can inject a
    transport / override the URL without touching the environment.

    **Shared-client mode.** Every route historically did ``async with
    ApplicantEngineClient()``, which opens a brand-new connection pool (fresh
    TCP/TLS handshake, zero keep-alive reuse) on *every single proxy hop* — the
    dominant per-request cost for an in-network call. Pass ``client=`` (an
    already-open ``httpx.AsyncClient``, typically the one app-lifetime instance
    ``workspace/app.py`` builds via :func:`build_shared_http_client` and stores
    on ``app.state.http_client``) to ride that pooled connection instead. This
    instance then does NOT own the client's lifecycle — :meth:`aclose` becomes a
    no-op — so the exact same ``async with ApplicantEngineClient(client=...) as
    engine:`` pattern already used everywhere is a safe drop-in swap; nothing
    else about the call site needs to change.
    """

    def __init__(
        self,
        base_url: Optional[str] = None,
        *,
        timeout: Optional[httpx.Timeout] = None,
        transport: Optional[httpx.AsyncBaseTransport] = None,
        client: Optional[httpx.AsyncClient] = None,
    ) -> None:
        self.base_url = (base_url or engine_base_url()).rstrip("/")
        self._timeout = timeout or _DEFAULT_TIMEOUT
        if client is not None:
            # Shared, app-lifetime client injected by the caller — see
            # "Shared-client mode" above. We don't own it, so we must never
            # close it out from under other in-flight requests.
            self._client = client
            self._owns_client = False
        else:
            # ``transport`` is the hermetic-test seam: pass an httpx.MockTransport
            # to exercise this client with zero network (see
            # tests/test_applicant_engine.py).
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                timeout=self._timeout,
                transport=transport,
            )
            self._owns_client = True

    # -- lifecycle ---------------------------------------------------------

    async def __aenter__(self) -> "ApplicantEngineClient":
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        # Only close a pool we opened ourselves; a shared/injected client
        # outlives this instance and is closed once, by its owner, at app
        # shutdown (see build_shared_http_client's caller in workspace/app.py).
        if self._owns_client:
            await self._client.aclose()

    # -- low-level request -------------------------------------------------

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json: Any = None,
        params: Optional[dict] = None,
        files: Any = None,
        data: Any = None,
        expect_json: bool = True,
    ) -> Any:
        """Issue one request and normalise every failure to :class:`EngineError`.

        Returns the decoded JSON body (``expect_json=True``, the default) or the
        raw :class:`httpx.Response` for non-JSON endpoints (e.g. file payloads).
        A 2xx with an empty body (the engine's ``204 No Content`` writes) returns
        ``None`` rather than raising.
        """
        try:
            resp = await self._client.request(
                method, path, json=json, params=params, files=files, data=data
            )
        except httpx.TimeoutException as exc:
            raise EngineError(
                f"Engine request timed out: {method} {path}",
                is_timeout=True,
            ) from exc
        except httpx.HTTPError as exc:
            # ConnectError, ReadError, pool errors, invalid URL, etc.
            raise EngineError(
                f"Engine request failed: {method} {path}: {exc}",
            ) from exc

        if resp.status_code >= 400:
            detail = _safe_detail(resp)
            raise EngineError(
                f"Engine returned HTTP {resp.status_code} for {method} {path}",
                status=resp.status_code,
                detail=detail,
            )

        if not expect_json:
            return resp
        if resp.status_code == 204 or not resp.content:
            return None
        try:
            return resp.json()
        except ValueError:
            # 2xx but non-JSON body — hand back text so the caller can decide.
            return resp.text

    # -- health ------------------------------------------------------------

    async def engine_available(self) -> bool:
        """Ping the engine ``/healthz``. Returns ``True`` iff it answers 2xx.

        Never raises — a down engine is a normal, expected state the UI reports
        (sections stay locked) rather than an error.
        """
        try:
            resp = await self._client.get("/healthz")
        except httpx.HTTPError:
            return False
        return resp.is_success

    async def healthz(self) -> dict:
        """Return the engine health payload (raises :class:`EngineError` if down)."""
        return await self._request("GET", "/healthz")

    # -- setup / gate (FR-OOBE) -------------------------------------------

    async def setup_status(self) -> dict:
        """Engine wizard/gate status: ``llm_configured``, ``channels_configured``,
        ``onboarding_complete``, ``gate_open``, ``automated_work_allowed`` …"""
        return await self._request("GET", "/api/setup/status")

    async def dormant_surfaces(self) -> list[dict]:
        """The engine's dormant-surface registry (key/status/live_phase/...)."""
        result = await self._request("GET", "/api/dormant-surfaces")
        return result if isinstance(result, list) else []

    # -- setup wizard: LLM + channels + step advance (FR-OOBE-2/3) --------

    async def setup_configure_llm(self, body: dict) -> Any:
        """Set the LLM provider/model/key directly (FR-LLM-2). 204 -> None."""
        return await self._request("POST", "/api/setup/llm", json=body)

    async def setup_configure_llm_from_endpoint(self, body: dict) -> Any:
        """Set the chat model from a saved endpoint + chosen model. 204 -> None."""
        return await self._request("POST", "/api/setup/llm/from-endpoint", json=body)

    async def setup_get_tiers(self) -> Any:
        return await self._request("GET", "/api/setup/llm/tiers")

    async def setup_set_tiers(self, body: dict) -> Any:
        return await self._request("PUT", "/api/setup/llm/tiers", json=body)

    async def setup_get_channels(self) -> Any:
        return await self._request("GET", "/api/setup/channels")

    async def setup_configure_channels(self, body: dict) -> Any:
        """Set notification channels (Discord/email via Apprise). 204 -> None."""
        return await self._request("POST", "/api/setup/channels", json=body)

    async def setup_test_channels(self) -> Any:
        return await self._request("POST", "/api/setup/channels/test")

    async def setup_get_quiet_hours(self) -> Any:
        """The persisted quiet-hours window for approvals/digests (FR-NOTIF-5)."""
        return await self._request("GET", "/api/setup/channels/quiet-hours")

    async def setup_configure_quiet_hours(self, body: dict) -> Any:
        """Set the quiet-hours window (enabled/start/end/tz). 204 -> None."""
        return await self._request("POST", "/api/setup/channels/quiet-hours", json=body)

    async def setup_advance(self, step: str) -> Any:
        return await self._request("POST", f"/api/setup/advance/{step}")

    # -- setup wizard: automation sandbox backend (FR-SANDBOX-1, FR-OOBE) --

    async def setup_get_sandbox_connection(self) -> Any:
        """The persisted Proxmox Windows connection (NO secrets) + readiness flags."""
        return await self._request("GET", "/api/setup/sandbox-connection")

    async def setup_configure_sandbox_connection(self, body: dict) -> Any:
        """Save the native Windows VM connection/login (secrets vaulted). 204 -> None."""
        return await self._request("POST", "/api/setup/sandbox-connection", json=body)

    # -- model endpoints: paste a base URL, auto-list its models ----------

    async def list_model_endpoints(self, refresh: bool = False) -> Any:
        return await self._request(
            "GET", "/api/model-endpoints", params={"refresh": str(bool(refresh)).lower()}
        )

    async def add_model_endpoint(self, data: dict) -> Any:
        """Add a model source and live-list its models (engine reads form data)."""
        return await self._request("POST", "/api/model-endpoints", data=data)

    async def test_model_endpoint(self, data: dict) -> Any:
        """Probe a model source without saving (engine reads form data)."""
        return await self._request("POST", "/api/model-endpoints/test", data=data)

    async def model_endpoint_models(self, endpoint_id: str, refresh: bool = False) -> Any:
        return await self._request(
            "GET",
            f"/api/model-endpoints/{endpoint_id}/models",
            params={"refresh": str(bool(refresh)).lower()},
        )

    # -- fonts: detect/install for resume fidelity (FR-FONT) -------------

    async def list_fonts(self) -> Any:
        return await self._request("GET", "/api/fonts")

    async def detect_fonts(self, files: Any) -> Any:
        """Detect required/missing fonts for an uploaded resume."""
        return await self._request("POST", "/api/fonts/detect", files=files)

    async def install_font(self, files: Any, data: Any) -> Any:
        """Install an uploaded font file (multipart name + file)."""
        return await self._request("POST", "/api/fonts/install", files=files, data=data)

    # -- campaigns --------------------------------------------------------

    async def list_campaigns(self) -> Any:
        return await self._request("GET", "/api/campaigns")

    async def create_campaign(self, name: str) -> Any:
        return await self._request("POST", "/api/campaigns", json={"name": name})

    async def update_campaign(self, campaign_id: str, body: dict) -> Any:
        """Rename / archive / re-tune a campaign's run config (#301, FR-CRIT-4)."""
        return await self._request("PATCH", f"/api/campaigns/{campaign_id}", json=body)

    async def delete_campaign(self, campaign_id: str) -> Any:
        """Delete a campaign and PURGE all its associated data (#363, FR-CRIT-4,
        NFR-PRIV-1) -- résumés/variants, parsed PII, EEO answers, generated
        materials, attributes, application-scoped children, and banked
        credentials. Irreversible; the engine itself refuses to delete the
        reserved system campaign."""
        return await self._request("DELETE", f"/api/campaigns/{campaign_id}")

    # -- discovery sources (#301, FR-DISC-2/5) ---------------------------

    async def list_discovery_sources(self, campaign_id: str) -> Any:
        return await self._request("GET", f"/api/discovery-sources/{campaign_id}")

    async def toggle_discovery_source(
        self, campaign_id: str, source_key: str, enabled: bool
    ) -> Any:
        return await self._request(
            "PUT",
            f"/api/discovery-sources/{campaign_id}/{source_key}",
            json={"enabled": enabled},
        )

    # -- documents / variants (Lane A) -----------------------------------

    async def list_documents(self) -> Any:
        return await self._request("GET", "/api/documents")

    async def documents_for_application(self, application_id: str) -> Any:
        return await self._request("GET", f"/api/documents/applications/{application_id}")

    async def list_variants(self, campaign_id: str) -> Any:
        """Owner-scoped résumé-variant library (lineage / scores / approval state)."""
        return await self._request("GET", f"/api/documents/variants/{campaign_id}")

    async def generate_cover_letter(self, body: Any) -> Any:
        """Generate a cover letter on demand; routed to review (FR-RESUME-10)."""
        return await self._request("POST", "/api/documents/cover-letter", json=body)

    async def generate_screening_answer(self, body: Any) -> Any:
        """Generate a screening answer on demand; routed to review (FR-ANSWER-1)."""
        return await self._request("POST", "/api/documents/screening-answer", json=body)

    async def screening_answer_library(self, campaign_id: str) -> Any:
        """The reusable, campaign-scoped screening-answer library (product-gaps
        backlog #20): common questions answered once, that a prior generation
        quietly saved (see engine ``MaterialService._save_to_screening_library``),
        surfaced so the UI can browse and reuse them."""
        return await self._request(
            "GET", f"/api/documents/screening-answer-library/{campaign_id}"
        )

    async def reuse_screening_answer(self, body: Any) -> Any:
        """Reuse a library answer for a NEW application instead of regenerating it
        (#20). ``found: false`` when no library entry matches the question."""
        return await self._request(
            "POST", "/api/documents/screening-answer-library/reuse", json=body
        )

    async def interview_prep(self, campaign_id: str, application_id: str) -> Any:
        """A plain-language interview-prep brief (product-gaps backlog #30).

        ``generated: false`` until the application has reached the
        ``interview_invited`` outcome signal -- the engine enforces that gate
        itself, never trusting a caller-supplied flag."""
        return await self._request(
            "GET", f"/api/documents/interview-prep/{campaign_id}/{application_id}"
        )

    async def review_document(self, document_id: str) -> Any:
        return await self._request("POST", f"/api/documents/{document_id}/review")

    async def turn_document(self, document_id: str, body: dict) -> Any:
        """Apply a revision turn (``kind``/``instruction``/``true_source``)."""
        return await self._request("POST", f"/api/documents/{document_id}/turn", json=body)

    async def approve_document(self, document_id: str) -> Any:
        return await self._request("POST", f"/api/documents/{document_id}/approve")

    async def decline_document(self, document_id: str) -> Any:
        return await self._request("POST", f"/api/documents/{document_id}/decline")

    async def approve_variant(self, variant_id: str) -> Any:
        return await self._request("POST", f"/api/documents/variants/{variant_id}/approve")

    async def download_variant_pdf(self, variant_id: str) -> Any:
        """Download the compiled résumé PDF for a variant (dark-engine audit item
        16), mirroring the ``audit_log_*_export`` binary-passthrough convention:
        returns the raw ``httpx.Response`` rather than trying to JSON-decode a
        binary body."""
        return await self._request(
            "GET",
            f"/api/documents/variants/{variant_id}/download",
            expect_json=False,
        )

    async def set_document_aggressiveness(self, aggressiveness: Any) -> Any:
        return await self._request(
            "POST", "/api/documents/aggressiveness", json={"aggressiveness": aggressiveness}
        )

    # -- onboarding / intake (Lane A) ------------------------------------

    async def onboarding_state(self, campaign_id: str) -> Any:
        return await self._request("GET", f"/api/onboarding/{campaign_id}")

    async def onboarding_section(self, campaign_id: str, body: dict) -> Any:
        """Persist one intake section (``section`` + ``data``)."""
        return await self._request("POST", f"/api/onboarding/{campaign_id}/section", json=body)

    async def onboarding_complete(self, campaign_id: str) -> Any:
        return await self._request("POST", f"/api/onboarding/{campaign_id}/complete")

    async def onboarding_base_resume(self, campaign_id: str, files: Any) -> Any:
        """Upload the base resume; engine parses + reconciles (FR-ONBOARD-3)."""
        return await self._request(
            "POST", f"/api/onboarding/{campaign_id}/base-resume", files=files
        )

    async def onboarding_confirm_conflict(self, campaign_id: str, body: dict) -> Any:
        """Apply a flagged integral change after explicit confirmation (FR-FB-3)."""
        return await self._request(
            "POST", f"/api/onboarding/{campaign_id}/confirm-conflict", json=body
        )

    # -- attributes (Lane B) ---------------------------------------------

    async def list_attributes(self, campaign_id: str) -> Any:
        return await self._request("GET", f"/api/attributes/{campaign_id}")

    async def add_attribute(self, body: dict) -> Any:
        return await self._request("POST", "/api/attributes", json=body)

    async def ai_add_attribute(self, body: dict) -> Any:
        return await self._request("POST", "/api/attributes/ai-add", json=body)

    async def bind_attribute(self, body: dict) -> Any:
        return await self._request("POST", "/api/attributes/bindings", json=body)

    async def acquire_missing_attribute(self, body: dict) -> Any:
        return await self._request("POST", "/api/attributes/acquire-missing", json=body)

    # CRIT-profile: attribute delete (FR-ATTR-3) + banned-phrase list (FR-RESUME-5).
    async def delete_attribute(self, campaign_id: str, attribute_id: str) -> Any:
        return await self._request(
            "DELETE", f"/api/attributes/{campaign_id}/{attribute_id}"
        )

    async def get_banned_phrases(self) -> Any:
        return await self._request("GET", "/api/documents/banned-phrases")

    async def set_banned_phrases(self, phrases: list[str]) -> Any:
        return await self._request(
            "POST", "/api/documents/banned-phrases", json={"phrases": phrases}
        )
    # CRIT-profile: end

    # -- conversion / learning (Lane B) ----------------------------------

    async def conversion_engine(self, campaign_id: str) -> Any:
        return await self._request("GET", f"/api/conversion/{campaign_id}/engine")

    async def conversion_preview(self, campaign_id: str, source: Any) -> Any:
        return await self._request(
            "POST", f"/api/conversion/{campaign_id}/preview", json={"source": source}
        )

    async def conversion_accept(self, campaign_id: str) -> Any:
        return await self._request("POST", f"/api/conversion/{campaign_id}/accept")

    async def conversion_reject(self, campaign_id: str) -> Any:
        return await self._request("POST", f"/api/conversion/{campaign_id}/reject")

    # -- chat / assistant (Lane C) ---------------------------------------

    async def chat(self, body: dict) -> Any:
        """Conversational turn (``campaign_id`` + ``message``) -> reply + gaps."""
        return await self._request("POST", "/api/chat", json=body)

    async def chat_confirm(self, body: dict) -> Any:
        """Commit an integral change after the user confirms it."""
        return await self._request("POST", "/api/chat/confirm", json=body)

    # -- pending actions (Lane C) ----------------------------------------

    async def list_pending_actions(self, campaign_id: str) -> Any:
        return await self._request("GET", f"/api/pending-actions/{campaign_id}")

    async def resolve_pending_action(self, action_id: str, body: Any | None = None) -> Any:
        # ``body`` (e.g. {"apply": true}) confirms/applies a held integral change
        # before the item is cleared (FR-FB-3); omitted for a plain resolve.
        return await self._request(
            "POST", f"/api/pending-actions/{action_id}/resolve", json=body or None
        )

    async def resolve_pending_actions_bulk(self, campaign_id: str, action_ids: list) -> Any:
        # Resolve a batch in one call — "approve all N digest items" (#295). The
        # engine campaign-scopes the ids so a stray id can't clear another campaign.
        return await self._request(
            "POST",
            f"/api/pending-actions/{campaign_id}/resolve-bulk",
            json={"action_ids": list(action_ids)},
        )

    async def snooze_pending_action(self, action_id: str, body: Any | None = None) -> Any:
        # Reschedule an action — "remind me tomorrow" (#295). ``body`` may carry
        # ``until`` (ISO) or ``hours``; omitted snoozes ~24h by default.
        return await self._request(
            "POST", f"/api/pending-actions/{action_id}/snooze", json=body or None
        )

    # -- notification center (in-app inbox) ------------------------------

    async def list_notifications(self) -> Any:
        return await self._request("GET", "/api/notifications")

    async def dismiss_notification(self, notification_id: str) -> Any:
        return await self._request(
            "POST", f"/api/notifications/{notification_id}/seen"
        )

    async def deliver_notifications_now(self) -> Any:
        """Force-flush notifications held back by quiet hours (#302)."""
        return await self._request("POST", "/api/notifications/deliver-now")

    # -- digest / notifications (Lane D) ---------------------------------

    async def digest(self, campaign_id: str) -> Any:
        return await self._request("GET", f"/api/digest/{campaign_id}")

    async def digest_email(self, campaign_id: str) -> Any:
        return await self._request("GET", f"/api/digest/{campaign_id}/email")

    async def deliver_digest(self, campaign_id: str) -> Any:
        return await self._request("POST", f"/api/digest/{campaign_id}/deliver")

    async def approve_digest_application(self, application_id: str) -> Any:
        return await self._request(
            "POST", f"/api/digest/applications/{application_id}/approve"
        )

    async def decline_digest_application(self, application_id: str, body: dict | None = None) -> Any:
        """Decline a digested role with optional ``feedback_text``/``criteria_delta``."""
        return await self._request(
            "POST", f"/api/digest/applications/{application_id}/decline", json=body or {}
        )

    # -- feedback (Lane D) -----------------------------------------------

    async def feedback_freetext(self, body: dict) -> Any:
        return await self._request("POST", "/api/feedback/freetext", json=body)

    async def feedback_survey(self, body: dict) -> Any:
        return await self._request("POST", "/api/feedback/survey", json=body)

    # === CRIT-ops: debug/observability + run controls + update + discovery ===
    # Added by the crit-ops lane. Each maps 1:1 to an engine endpoint group
    # (routers/admin.py, outcomes.py, update.py, agent_runs.py, discovery_sources.py)
    # surfaced by the workspace Activity/Update/Run-controls proxies. Append-only.

    # -- audit log export (engine routers/audit.py) -------------------------

    async def audit_log_campaign_export(self, campaign_id: str) -> Any:
        """Download the full action trail for a campaign (Content-Disposition: attachment)."""
        return await self._request(
            "GET",
            f"/api/admin/audit-log/{campaign_id}/export.json",
            expect_json=False,  # raw Response for the attachment
        )

    async def audit_log_application_export(self, application_id: str) -> Any:
        """Download the full action trail for one application."""
        return await self._request(
            "GET",
            f"/api/admin/audit-log/application/{application_id}/export.json",
            expect_json=False,
        )

    # -- debug/observability surface (engine routers/admin.py, outcomes.py) --

    async def admin_application_history(self, campaign_id: str, limit: int = 200) -> Any:
        return await self._request(
            "GET", f"/api/admin/history/{campaign_id}", params={"limit": limit}
        )

    async def admin_application_outcomes(self, application_id: str) -> Any:
        return await self._request("GET", f"/api/admin/outcomes/{application_id}")

    async def admin_detections(self, campaign_id: str) -> Any:
        return await self._request("GET", f"/api/admin/detections/{campaign_id}")

    async def admin_workflow_state(self, application_id: str) -> Any:
        return await self._request("GET", f"/api/admin/workflow/{application_id}")

    async def admin_screenshots(self, application_id: str) -> Any:
        return await self._request("GET", f"/api/admin/screenshots/{application_id}")

    async def admin_logs(self, limit: int = 100) -> Any:
        return await self._request("GET", "/api/admin/logs", params={"limit": limit})

    async def admin_variants(self, campaign_id: str) -> Any:
        return await self._request("GET", f"/api/admin/variants/{campaign_id}")

    async def admin_learning(self, campaign_id: str) -> Any:
        """Plain-language summary of what the engine has learned for a campaign.

        Conversion totals, the source funnel ranked by conversion, the roles that
        actually convert, and the exploration budget — read-only operator visibility.
        """
        return await self._request("GET", f"/api/admin/learning/{campaign_id}")

    async def admin_stealth(self) -> Any:
        return await self._request("GET", "/api/admin/stealth")

    # -- gallery collections (engine routers/gallery.py, issue #296) ----------
    # Screenshots + generated materials for a campaign, grouped into collections
    # for a simple grid view. Read-only; backed 1:1 by AdminQueryService.

    async def gallery(self, campaign_id: str) -> Any:
        """Screenshot + material collections for a campaign (#296)."""
        return await self._request("GET", f"/api/gallery/{campaign_id}")

    async def outcome_log(self, application_id: str) -> Any:
        return await self._request(
            "GET", f"/api/outcomes/applications/{application_id}/log"
        )

    async def outcome_mark_submitted(self, application_id: str, body: dict | None = None) -> Any:
        return await self._request(
            "POST", f"/api/outcomes/applications/{application_id}/mark-submitted",
            json=body or {},
        )

    async def outcome_detect(self, application_id: str) -> Any:
        return await self._request(
            "POST", f"/api/outcomes/applications/{application_id}/detect"
        )

    async def submission_snapshot(self, application_id: str) -> Any:
        """The immutable submission snapshot for an application (#372)."""
        return await self._request(
            "GET", f"/api/outcomes/applications/{application_id}/snapshot"
        )

    # -- post-submission tracker (engine routers/post_submission.py, G16/#190,
    #    design-audit Top-25 #4) -------------------------------------------
    # The applied -> awaiting response -> interview/offer signals -> rejected /
    # ghosted / archived board, plus the owner's manual "record what happened".

    async def tracker_board(self, campaign_id: str) -> Any:
        """Tracker-board rows for one campaign, newest first."""
        return await self._request("GET", f"/api/post-submission/{campaign_id}")

    async def tracker_record_outcome(self, application_id: str, outcome_type: str) -> Any:
        """Manually record an outcome (interview/offer/rejected/ghosted/...)."""
        return await self._request(
            "POST",
            f"/api/post-submission/applications/{application_id}/outcome",
            json={"outcome_type": outcome_type},
        )

    async def tracker_scan_email(self, application_id: str, subject: str, body: str) -> Any:
        """Run one pasted email's subject/body through the engine's outcome
        detectors (rejection/interview/offer, design-audit Top-25 #5) for a
        SPECIFIC application the owner has already identified — this is the
        deliberately manual, zero-ambiguity sibling of automatic inbox
        matching (out of scope; a mis-attributed email could record a fake
        outcome against the wrong application)."""
        return await self._request(
            "POST",
            f"/api/post-submission/applications/{application_id}/scan-email",
            json={"subject": subject, "body": body},
        )

    # -- in-UI update button (engine routers/update.py) ----------------------

    async def update_status(self) -> Any:
        return await self._request("GET", "/api/update")

    async def update_trigger(self) -> Any:
        return await self._request("POST", "/api/update/trigger")

    # -- run-mode / throughput controls (engine routers/agent_runs.py) -------

    async def agent_runs_list(self, campaign_id: str) -> Any:
        return await self._request("GET", f"/api/agent-runs/{campaign_id}")

    #: Readable alias for the run-history read used by the agent-activity surface
    #: (status strip + Activity page). Same endpoint as :meth:`agent_runs_list` —
    #: a name-only convenience so the activity proxy reads as status/intent/runs.
    async def agent_runs(self, campaign_id: str) -> Any:
        return await self.agent_runs_list(campaign_id)

    async def agent_run_intent(self, campaign_id: str) -> Any:
        return await self._request("GET", f"/api/agent-runs/{campaign_id}/intent")

    async def agent_run_configure(self, campaign_id: str, body: dict) -> Any:
        return await self._request("PUT", f"/api/agent-runs/{campaign_id}/config", json=body)

    async def agent_run_status(self, campaign_id: str) -> Any:
        return await self._request("GET", f"/api/agent-runs/{campaign_id}/status")

    #: Consolidated, plain-language live snapshot (now / next / recent) the engine
    #: assembles fresh from the scheduler + run service + history + pending actions
    #: (engine routers/agent_status.py). Backs the front-door agent-activity panel.
    async def agent_status(self, campaign_id: str) -> Any:
        return await self._request("GET", f"/api/agent/status/{campaign_id}")

    async def agent_run_now(self, campaign_id: str) -> Any:
        return await self._request("POST", f"/api/agent-runs/{campaign_id}/run")

    async def agent_run_pause(self, campaign_id: str) -> Any:
        return await self._request("POST", f"/api/agent-runs/{campaign_id}/pause")

    async def agent_run_resume(self, campaign_id: str) -> Any:
        return await self._request("POST", f"/api/agent-runs/{campaign_id}/resume")

    # -- discovery-source toggles + yield (engine routers/discovery_sources.py)

    async def discovery_sources_list(self, campaign_id: str) -> Any:
        return await self._request("GET", f"/api/discovery-sources/{campaign_id}")

    async def discovery_source_toggle(self, campaign_id: str, source_key: str, enabled: bool) -> Any:
        return await self._request(
            "PUT", f"/api/discovery-sources/{campaign_id}/{source_key}",
            json={"enabled": enabled},
        )
    # === end CRIT-ops ========================================================
    # -- live remote session / takeover (CRIT-auto: automation surface) ----
    # Maps 1:1 to the engine's ``remote`` router (FR-SANDBOX-2/3/4, FR-PREFILL-5).
    # The final-submit/authorize methods hit the engine's EXPLICIT authorize
    # endpoints, which route the click through the core pre-fill stop-boundary —
    # the engine can never self-authorize the final submit.

    async def list_remote_sessions(self) -> Any:
        """All currently live sandbox sessions (multi-session picker)."""
        return await self._request("GET", "/api/remote/sessions")

    async def open_remote_session(self, application_id: str) -> Any:
        """Provision a sandbox for an application; returns its one-click view URL."""
        return await self._request(
            "POST", "/api/remote/sessions", json={"application_id": application_id}
        )

    async def remote_session_view_url(self, session_id: str) -> Any:
        """The (token-bearing) live-session URL for an existing session."""
        return await self._request("GET", f"/api/remote/sessions/{session_id}/view-url")

    async def takeover_remote_session(self, session_id: str) -> Any:
        """Hand live control of the session to the user (204 -> None)."""
        return await self._request("POST", f"/api/remote/sessions/{session_id}/takeover")

    async def request_final_approval(self, application_id: str) -> Any:
        """Notify the user that an application awaits final approval."""
        return await self._request(
            "POST", f"/api/remote/applications/{application_id}/request-final-approval"
        )

    async def submit_self(self, application_id: str) -> Any:
        """User submitted themselves in the live session (terminal decision)."""
        return await self._request(
            "POST", f"/api/remote/applications/{application_id}/submit-self"
        )

    async def authorize_engine_finish(self, application_id: str) -> Any:
        """Explicitly authorize the engine to click the final submit (boundary-gated)."""
        return await self._request(
            "POST", f"/api/remote/applications/{application_id}/authorize-engine-finish"
        )

    async def resume_account_step(self, application_id: str) -> Any:
        """Resume pre-fill after the user completed the human account-creation step."""
        return await self._request(
            "POST", f"/api/remote/applications/{application_id}/resume-account-step"
        )

    async def resume_detection_step(self, application_id: str) -> Any:
        """Resume pre-fill after the user cleared a detection challenge."""
        return await self._request(
            "POST", f"/api/remote/applications/{application_id}/resume-detection-step"
        )

    async def continue_two_factor(self, application_id: str) -> Any:
        """Continue a Google 2FA hand-off: trigger the push, wait up to 60s for the
        user's on-device approval, then continue pre-fill (or re-notify for a retry)."""
        return await self._request(
            "POST", f"/api/remote/applications/{application_id}/continue-two-factor"
        )

    async def stealth_caveat(self) -> Any:
        """The honest best-effort anti-detection + egress caveat copy + posture."""
        return await self._request("GET", "/api/admin/stealth")

    # -- desktop assist (FR-CUA): opt-in, per-session, ships DORMANT ----------
    # Lets the assistant help on the desktop (file pickers / OS dialogs the browser
    # can't reach) DURING an open live session — present-but-grayed until the desktop
    # helper is baked into the sandbox image and the health preflight passes. The
    # destructive-action passthrough is guarded by the engine's core safety machinery
    # (the engine still cannot self-authorize a final submit).

    async def desktop_assist_health(self) -> Any:
        """Desktop-assist preflight: is the helper present + the surface live?"""
        return await self._request("GET", "/api/remote/desktop/health")

    async def desktop_assist_state(self, session_id: str) -> Any:
        """Whether desktop assist is opted-in for this live session (+ health)."""
        return await self._request("GET", f"/api/remote/sessions/{session_id}/desktop")

    async def desktop_assist_enable(self, session_id: str) -> Any:
        """Opt this live session in to desktop assist (refused while dormant)."""
        return await self._request(
            "POST", f"/api/remote/sessions/{session_id}/desktop/enable"
        )

    async def desktop_assist_disable(self, session_id: str) -> Any:
        """Revoke desktop assist for this live session."""
        return await self._request(
            "POST", f"/api/remote/sessions/{session_id}/desktop/disable"
        )

    async def desktop_assist_action(self, session_id: str, body: dict) -> Any:
        """Perform a single guarded desktop action behind the engine's safety gates."""
        return await self._request(
            "POST", f"/api/remote/sessions/{session_id}/desktop/action", json=body
        )

    # -- credential vault (CRIT-auto: applicant vault, FR-VAULT-2) ---------
    # The engine seals secrets at rest; list NEVER returns plaintext.

    async def vault_store_credential(self, body: dict) -> Any:
        """Manually bank a per-tenant credential set in the vault."""
        return await self._request("POST", "/api/credentials", json=body)

    async def vault_capture_credential(self, body: dict) -> Any:
        """Auto-capture credentials entered during a live account-creation."""
        return await self._request("POST", "/api/credentials/capture", json=body)

    async def vault_list_tenants(self, campaign_id: str) -> Any:
        """Tenant keys that have stored credentials (no secrets returned)."""
        return await self._request("GET", f"/api/credentials/{campaign_id}/tenants")

    async def vault_store_account_credential(self, body: dict) -> Any:
        """Bank a GLOBAL account credential (Google / default new-account set) under
        the SYSTEM campaign so it applies to every job search — set once, reused
        everywhere."""
        return await self._request("POST", "/api/credentials/account", json=body)

    async def vault_account_status(self) -> Any:
        """Which global account credentials are set (no secrets returned)."""
        return await self._request("GET", "/api/credentials/account")

    # -- manual deep-research trigger (engine routers/research.py) ----------
    # The agent auto-escalates to research already; these expose the engine's
    # SAME capped/deduped/cached path as an explicit, user-initiated run + a
    # budget read. ``run`` returns the structured report (200 with
    # ``unavailable: true`` + ``reason`` when the channel is off / budget is
    # exhausted — a degraded state, not an error).

    async def research_run(self, campaign_id: str, body: dict) -> Any:
        """Run (or reuse) deep research for a campaign — the manual trigger."""
        return await self._request("POST", f"/api/research/{campaign_id}/run", json=body)

    async def research_budget(self, campaign_id: str) -> Any:
        """Read a campaign's research budget + channel availability."""
        return await self._request("GET", f"/api/research/{campaign_id}/budget")

    # -- review-gate ensure-submittable (engine routers/documents.py) --------
    # FR-RESUME-8: enforce the review gate before submission. Returns 409 when
    # the application has unapproved materials.

    async def ensure_submittable(self, application_id: str) -> Any:
        """Check that the application's materials have passed the review gate."""
        return await self._request(
            "POST", f"/api/documents/applications/{application_id}/ensure-submittable"
        )

    # -- chat: confirm-criteria refocus (engine routers/chat.py) --------------
    # FR-FB-3 / FR-CRIT: commit a confirmation-gated criteria refocus the user
    # approved through the chat surface. The engine's own gate raises 409 if
    # confirmation is still required.

    async def chat_confirm_criteria(self, body: dict) -> Any:
        """Commit a confirmation-gated criteria refocus (FR-FB-3)."""
        return await self._request("POST", "/api/chat/confirm-criteria", json=body)

    # -- criteria: apply learned adjustment (engine routers/criteria.py) ------
    # FR-CRIT-3: surface a learned criteria adjustment from the LLM + rationale,
    # returning the updated criteria. Write-through, user-visible, overridable.

    async def criteria_apply_learned(self, campaign_id: str, body: dict) -> Any:
        """Apply an LLM-suggested learned criteria adjustment (FR-CRIT-3)."""
        return await self._request(
            "POST", f"/api/criteria/{campaign_id}/learned", json=body
        )

    # -- compare: cross-entity diffs (engine routers/compare.py, #297) -------
    # Real cross-entity comparison. The engine's CompareService returns a
    # dimension table (entity_ids / entity_labels / dimensions[].values+diff /
    # summary) for applications or postings, optionally campaign-scoped (FR-CRIT-4).
    # The engine route POSTs a bare list body of ids + a ``campaign_id`` query
    # param, so these pass the ids as the JSON body and the campaign id as a query
    # param to match its signature 1:1.

    async def compare_applications(
        self, application_ids: list[str], campaign_id: str | None = None
    ) -> Any:
        """Compare >=2 applications side-by-side (status / job-title diffs)."""
        params = {"campaign_id": campaign_id} if campaign_id else None
        return await self._request(
            "POST", "/api/compare/applications", json=application_ids, params=params
        )

    async def compare_postings(
        self, posting_ids: list[str], campaign_id: str | None = None
    ) -> Any:
        """Compare >=2 postings side-by-side (title / company / location diffs)."""
        params = {"campaign_id": campaign_id} if campaign_id else None
        return await self._request(
            "POST", "/api/compare/postings", json=posting_ids, params=params
        )


# ---------------------------------------------------------------------------
# Sync convenience helpers (non-async callers: startup probes, scripts, the
# feature layer when it has no running event loop). Thin wrappers over a
# short-lived httpx.Client so we don't keep a second pool around.
# ---------------------------------------------------------------------------


def engine_available_sync(
    base_url: Optional[str] = None,
    *,
    transport: Optional[httpx.BaseTransport] = None,
) -> bool:
    """Synchronously ping the engine ``/healthz``; ``True`` iff it answers 2xx.

    Never raises (a down engine is an expected state). ``transport`` is the
    hermetic-test seam (pass ``httpx.MockTransport``).
    """
    url = (base_url or engine_base_url()).rstrip("/")
    try:
        with httpx.Client(base_url=url, timeout=_DEFAULT_TIMEOUT, transport=transport) as client:
            return client.get("/healthz").is_success
    except httpx.HTTPError:
        return False


def get_sync(
    path: str,
    *,
    base_url: Optional[str] = None,
    params: Optional[dict] = None,
    transport: Optional[httpx.BaseTransport] = None,
) -> Any:
    """Synchronous GET returning decoded JSON, or raising :class:`EngineError`.

    Used by the feature layer to read ``/api/setup/status`` +
    ``/api/dormant-surfaces`` from contexts without an event loop.
    """
    url = (base_url or engine_base_url()).rstrip("/")
    try:
        with httpx.Client(base_url=url, timeout=_DEFAULT_TIMEOUT, transport=transport) as client:
            resp = client.get(path, params=params)
    except httpx.TimeoutException as exc:
        raise EngineError(f"Engine request timed out: GET {path}", is_timeout=True) from exc
    except httpx.HTTPError as exc:
        raise EngineError(f"Engine request failed: GET {path}: {exc}") from exc
    if resp.status_code >= 400:
        raise EngineError(
            f"Engine returned HTTP {resp.status_code} for GET {path}",
            status=resp.status_code,
            detail=_safe_detail(resp),
        )
    if resp.status_code == 204 or not resp.content:
        return None
    try:
        return resp.json()
    except ValueError:
        return resp.text


def _safe_detail(resp: httpx.Response) -> Any:
    """Best-effort extraction of an error body without raising."""
    try:
        data = resp.json()
    except ValueError:
        return (resp.text or "")[:500]
    if isinstance(data, dict) and "detail" in data:
        return data["detail"]
    return data
