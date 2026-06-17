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


class ApplicantEngineClient:
    """Async httpx client for the engine API.

    Use as an async context manager so the underlying connection pool is reused
    and cleanly closed::

        async with ApplicantEngineClient() as engine:
            status = await engine.setup_status()

    Or share a single long-lived instance and call :meth:`aclose` on shutdown.
    The default ``base_url`` comes from ``ENGINE_URL`` so tests can inject a
    transport / override the URL without touching the environment.
    """

    def __init__(
        self,
        base_url: Optional[str] = None,
        *,
        timeout: Optional[httpx.Timeout] = None,
        transport: Optional[httpx.AsyncBaseTransport] = None,
    ) -> None:
        self.base_url = (base_url or engine_base_url()).rstrip("/")
        self._timeout = timeout or _DEFAULT_TIMEOUT
        # ``transport`` is the hermetic-test seam: pass an httpx.MockTransport to
        # exercise this client with zero network (see tests/test_applicant_engine.py).
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=self._timeout,
            transport=transport,
        )

    # -- lifecycle ---------------------------------------------------------

    async def __aenter__(self) -> "ApplicantEngineClient":
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
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

    # -- documents / variants (Lane A) -----------------------------------

    async def list_documents(self) -> Any:
        return await self._request("GET", "/api/documents")

    async def documents_for_application(self, application_id: str) -> Any:
        return await self._request("GET", f"/api/documents/applications/{application_id}")

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

    async def resolve_pending_action(self, action_id: str) -> Any:
        return await self._request("POST", f"/api/pending-actions/{action_id}/resolve")

    # -- notification center (in-app inbox) ------------------------------

    async def list_notifications(self) -> Any:
        return await self._request("GET", "/api/notifications")

    async def dismiss_notification(self, notification_id: str) -> Any:
        return await self._request(
            "POST", f"/api/notifications/{notification_id}/seen"
        )

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

    async def admin_stealth(self) -> Any:
        return await self._request("GET", "/api/admin/stealth")

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

    # -- in-UI update button (engine routers/update.py) ----------------------

    async def update_status(self) -> Any:
        return await self._request("GET", "/api/update")

    async def update_trigger(self) -> Any:
        return await self._request("POST", "/api/update/trigger")

    # -- run-mode / throughput controls (engine routers/agent_runs.py) -------

    async def agent_runs_list(self, campaign_id: str) -> Any:
        return await self._request("GET", f"/api/agent-runs/{campaign_id}")

    async def agent_run_intent(self, campaign_id: str) -> Any:
        return await self._request("GET", f"/api/agent-runs/{campaign_id}/intent")

    async def agent_run_configure(self, campaign_id: str, body: dict) -> Any:
        return await self._request("PUT", f"/api/agent-runs/{campaign_id}/config", json=body)

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

    async def stealth_caveat(self) -> Any:
        """The honest best-effort anti-detection + egress caveat copy + posture."""
        return await self._request("GET", "/api/admin/stealth")

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
