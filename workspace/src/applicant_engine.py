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

import asyncio
import logging
import os
import random
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

#: Bounded retry policy for SAFE, IDEMPOTENT requests only (``GET``). The engine
#: is internal and momentary blips are common during a restart/deploy — a
#: connection reset/refusal mid-request, or a 502/503 while the container comes
#: back up, is a transient shape worth one or two quick retries rather than
#: failing the whole front-door call. Writes (POST/PUT/DELETE) are NEVER
#: retried here (a lost response after the engine already committed a write
#: must not be silently re-sent), and a 4xx is NEVER retried (that's the engine
#: correctly rejecting the request, not a blip). Read timeouts also stay
#: fast-fail, unchanged: a slow-but-connected engine is a different failure
#: mode than a dropped connection, and stacking read-timeout waits behind one
#: UI request would undercut the module's deliberate fast-fail design.
_RETRYABLE_STATUSES = frozenset({502, 503})
_MAX_RETRY_ATTEMPTS = 2  # extra attempts after the first, i.e. up to 3 tries total
_RETRY_BACKOFF_BASE_SECONDS = 0.05


async def _sleep_before_retry(seconds: float) -> None:
    """Backoff sleep before a retried request.

    Isolated into its own (patchable) coroutine so hermetic tests can replace
    it with a no-op and keep the retry-path tests fast instead of actually
    waiting out the backoff.
    """
    await asyncio.sleep(seconds)


def _retry_delay_seconds(attempt: int) -> float:
    """Short exponential backoff for retry ``attempt`` (1-indexed), with light
    jitter so concurrent requests retrying together don't all land in lockstep."""
    base = _RETRY_BACKOFF_BASE_SECONDS * (2 ** (attempt - 1))
    return base + random.uniform(0, base / 4)


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

        Bounded retry (safe methods only): a ``GET`` is retried up to
        :data:`_MAX_RETRY_ATTEMPTS` times, with a short backoff between
        attempts, when the failure is a clearly-transient connection
        error/refusal or an HTTP 502/503 (see :data:`_RETRYABLE_STATUSES`).
        Every other method, and every other failure shape, behaves exactly as
        before — including the final error raised once retries are exhausted,
        which is identical to the single-attempt error.
        """
        is_retryable_method = method.upper() == "GET"
        attempt = 0
        while True:
            try:
                resp = await self._client.request(
                    method, path, json=json, params=params, files=files, data=data
                )
            except httpx.TimeoutException as exc:
                raise EngineError(
                    f"Engine request timed out: {method} {path}",
                    is_timeout=True,
                ) from exc
            except (httpx.ConnectError, httpx.ReadError) as exc:
                if is_retryable_method and attempt < _MAX_RETRY_ATTEMPTS:
                    attempt += 1
                    await _sleep_before_retry(_retry_delay_seconds(attempt))
                    continue
                raise EngineError(
                    f"Engine request failed: {method} {path}: {exc}",
                ) from exc
            except httpx.HTTPError as exc:
                # Pool errors, invalid URL, protocol errors, etc. — not
                # retried; only the connection-reset/refusal shape above is.
                raise EngineError(
                    f"Engine request failed: {method} {path}: {exc}",
                ) from exc

            if resp.status_code >= 400:
                if (
                    is_retryable_method
                    and resp.status_code in _RETRYABLE_STATUSES
                    and attempt < _MAX_RETRY_ATTEMPTS
                ):
                    attempt += 1
                    await _sleep_before_retry(_retry_delay_seconds(attempt))
                    continue
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

    # -- demo mode (P0-2 seeded demo) -------------------------------------

    async def demo_status(self) -> dict:
        """Whether the ``DEMO_MODE`` seed dataset is loaded (``/api/dev/seed/status``).

        Reachable ONLY when the engine runs under ``DEMO_MODE=1`` — the whole
        seed router 404s otherwise — so the front-door proxy treats an
        ``EngineError`` (incl. that 404) as "not in demo mode" and hides the
        banner. Returns the engine's ``{demo_active, campaign_id, counts}`` shape.
        """
        result = await self._request("GET", "/api/dev/seed/status")
        return result if isinstance(result, dict) else {}

    async def demo_clear(self) -> dict:
        """Clear the ``DEMO_MODE`` seed dataset (``POST /api/dev/seed/reset``).

        Reuses the engine's campaign-purge cascade so every seeded row is
        removed with no residue. Reachable only under ``DEMO_MODE`` (the seed
        router gate). Returns the engine's ``{reset, campaign_id, counts}`` shape.
        """
        result = await self._request("POST", "/api/dev/seed/reset")
        return result if isinstance(result, dict) else {}

    # -- setup / gate (FR-OOBE) -------------------------------------------

    async def setup_status(self) -> dict:
        """Engine wizard/gate status: ``llm_configured``, ``channels_configured``,
        ``onboarding_complete``, ``gate_open``, ``automated_work_allowed`` …"""
        return await self._request("GET", "/api/setup/status")

    async def dormant_surfaces(self) -> list[dict]:
        """The engine's dormant-surface registry (key/status/live_phase/...)."""
        result = await self._request("GET", "/api/dormant-surfaces")
        return result if isinstance(result, list) else []

    # -- honest health panel (P1-3, issue #655) ----------------------------

    async def health_capabilities(self) -> dict:
        """The boot-time capability self-report: postgres, résumé renderer,
        browser, orchestrator — each real-vs-stub with a plain-language label
        and actionable fix copy. Ungated on the engine (no llm-configured
        gate — see ``routers/health.py``), so it is reachable even before the
        owner has connected a model."""
        return await self._request("GET", "/api/health/capabilities")

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

    async def setup_get_gaps(self, campaign_id: str) -> Any:
        """A completeness checklist for one campaign (dark-engine audit item 51):
        which core profile attributes (name/email/phone/title) and search criteria
        are still missing. The SAME gap list the assistant chat already computes
        internally, surfaced as a plain read so it doesn't require a chat message."""
        return await self._request("GET", f"/api/setup/{campaign_id}/gaps")

    # -- setup: Settings > Automation (dark-engine audit items
    # 82/83/84/85/86/87/88/89/90/91/92/93/94/95/96/97/98/99/100/101/102/103/104/105/106/107) --

    async def setup_get_automation_prefs(self) -> Any:
        """Browser fingerprint timezone/locale, the automated-account-creation
        opt-in, the per-company daily application cap, retention/cooldown
        windows, the final-approval timeout, the check-for-work interval, the
        ATS fill-rate floor, eligibility/listing-age filters, memory
        write-approval + size caps, the smart-router prefer-local policy, the
        context-compression threshold, the failure-alert threshold, the
        sandbox/browser/stealth selectors, the assistant/loop tool-autonomy
        switches, company-research enrichment, desktop-assist backend/mode/
        approvals, proactive-cadence schedules, the discovery proxy list, the
        custom job-board RSS feed list (item 80, merged alongside the engine's
        hardcoded default feed), the live-takeover appearance, the resume render
        fidelity, the captcha-handling strategy/service (the API key surfaces only as a
        boolean ``captcha_api_key_configured``, never the key itself), and the
        residential-egress mode/attestation/proxy URL -- persisted overrides
        merged onto the engine's env defaults."""
        return await self._request("GET", "/api/setup/automation")

    async def setup_set_automation_prefs(self, body: dict) -> Any:
        """Save Settings > Automation overrides. 204 -> None."""
        return await self._request("PUT", "/api/setup/automation", json=body)

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

    async def patch_model_endpoint(self, endpoint_id: str) -> Any:
        """Toggle a saved model endpoint enabled/disabled (dark-engine audit item
        20; engine ``PATCH /api/model-endpoints/{id}``). The engine route takes no
        body -- it flips the current state."""
        return await self._request("PATCH", f"/api/model-endpoints/{endpoint_id}")

    async def delete_model_endpoint(self, endpoint_id: str) -> Any:
        """Remove a saved model endpoint (dark-engine audit item 20; engine
        ``DELETE /api/model-endpoints/{id}``) -- so a stale or mistyped endpoint
        doesn't accumulate forever in the engine's own endpoint registry."""
        return await self._request("DELETE", f"/api/model-endpoints/{endpoint_id}")

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

    async def clone_campaign(self, campaign_id: str, name: Optional[str] = None) -> Any:
        """Duplicate a campaign's criteria/settings under a new identity (dark-
        engine audit item 36) -- the natural "same search, new city" move. The
        engine names the copy from the source when ``name`` is omitted."""
        body: dict = {"name": name} if name else {}
        return await self._request("POST", f"/api/campaigns/{campaign_id}/clone", json=body)

    async def get_campaign_guardrails(self, campaign_id: str) -> Any:
        """Cost & pace guardrails (P1-6): today's pace/spend + a monthly projection.

        The engine enforces the daily target/hard cap and computes the cost
        estimate server-side (``GET /api/campaigns/{id}/guardrails``); this is a
        read-only proxy call, same shape as ``list_discovery_sources`` below.
        """
        return await self._request("GET", f"/api/campaigns/{campaign_id}/guardrails")

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

    async def fill_cover_letter_template(self, body: Any) -> Any:
        """Merge-fill a user's OWN saved cover-letter template's ``{{field}}``
        placeholders (dark-engine audit item 41). Deterministic string substitution
        -- no LLM call, complementary to ``generate_cover_letter`` above."""
        return await self._request("POST", "/api/documents/cover-letter/fill", json=body)

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

    async def generate_deferred_essay(self, body: Any) -> Any:
        """Resolve a DEFERRED essay screening question pre-fill parked instead of
        auto-answering (dark-engine audit item 21; engine ``POST
        /api/documents/deferred-essay``). Generates + routes the answer to
        review, and the engine clears the originating ``agent_question``
        pending action itself when a ``selector`` is supplied."""
        return await self._request("POST", "/api/documents/deferred-essay", json=body)

    async def render_redline(self, body: Any) -> Any:
        """Render an add/subtract/highlighted-HTML redline between two arbitrary
        text sources (dark-engine audit item 22; engine ``POST
        /api/documents/redline``) -- a pure, stateless diff (no persistence),
        reusable for "what changed vs. the original" outside a review session."""
        return await self._request("POST", "/api/documents/redline", json=body)

    async def document_flagged_facts(self, document_id: str) -> Any:
        """Facts in a generated draft not yet traceable to the candidate's profile
        (P1-13 truth-policy surfacing; engine ``GET
        /api/documents/{id}/flagged-facts``). Read-only detection the review UI shows
        with a one-tap confirm ("add to my profile") / remove choice."""
        return await self._request(
            "GET", f"/api/documents/{document_id}/flagged-facts"
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

    async def promote_variant(self, variant_id: str) -> Any:
        """Promote a résumé variant to be the new base résumé future tailoring
        forks from, instead of the user's original base résumé (dark-engine audit
        item 33; engine ``MaterialService.promote_to_base_resume``, #293)."""
        return await self._request("POST", f"/api/documents/variants/{variant_id}/promote")

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

    async def ingest_observations(self, campaign_id: str, observations: list[dict]) -> Any:
        """Bulk-reconcile a batch of parsed/observed facts into the attribute cloud
        (FR-LEARN-4, dark-engine audit #42): auto-applies non-integral values, holds
        integral ones for confirmation, surfaces conflicts, skips sensitive (EEO)."""
        return await self._request(
            "POST", f"/api/feedback/{campaign_id}/ingest", json={"observations": observations}
        )

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

    async def download_conversion_preview_pdf(self, campaign_id: str) -> Any:
        """Download the compiled LaTeX conversion preview PDF (dark-engine audit
        item 19; engine ``GET /api/conversion/{campaign_id}/preview/download``),
        mirroring the ``download_variant_pdf`` binary-passthrough convention: the
        raw ``httpx.Response`` is returned rather than JSON-decoded."""
        return await self._request(
            "GET",
            f"/api/conversion/{campaign_id}/preview/download",
            expect_json=False,
        )

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

    async def feedback_history(self, campaign_id: str) -> Any:
        """Read back what the user has told the assistant for one campaign — the
        read side of a surface that was otherwise write-only (dark-engine audit item
        23): decline-with-feedback reasons and résumé/answer revision instructions."""
        return await self._request("GET", f"/api/feedback/{campaign_id}")

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

    async def admin_screenshot_image(self, application_id: str, screenshot_id: str) -> Any:
        """Raw image bytes for one captured screenshot (dark-engine audit #28)."""
        return await self._request(
            "GET",
            f"/api/admin/screenshots/{application_id}/{screenshot_id}/image",
            expect_json=False,  # raw Response — binary image payload
        )

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

    async def admin_workspace_bridge(self) -> Any:
        """Engine <-> workspace callback-channel health (dark-engine audit #71).

        Whether ``APPLICANT_INTERNAL_TOKEN`` is configured and, when it is,
        whether the engine's ping-through to THIS workspace actually succeeds.
        """
        return await self._request("GET", "/api/admin/workspace-bridge")

    async def admin_captcha_status(self) -> Any:
        """Effective captcha strategy + real solve/avoid/handoff telemetry (dark-engine audit #67).

        The configured ``CAPTCHA_STRATEGY``/service/key, whether a solver is
        actually wired (only true for a non-default strategy), and — only when
        one is — its real process-lived attempt/outcome counters. Never a
        fabricated count.
        """
        return await self._request("GET", "/api/admin/captcha-status")

    async def admin_capacity(self) -> Any:
        """Sandbox concurrency snapshot: active vs. waiting applications (dark-engine audit #72).

        Reads the same sandbox-concurrency queue the live scheduler drives
        every tick, so this reflects the current queue, not a stale snapshot.
        """
        return await self._request("GET", "/api/admin/capacity")

    async def admin_embedding_backend(self) -> Any:
        """Which embedding backend powers memory/dedup matching (dark-engine audit #79).

        Plain-language disclosure of the active ``EmbeddingPort`` backend and
        its quality tier — today always the offline hashing-trick backend.
        """
        return await self._request("GET", "/api/admin/embedding-backend")

    async def admin_prefill_diagnostics(self) -> Any:
        """Recent pre-fill silent-degradation diagnostics (dark-engine audit #34).

        A bounded, deduped ring of plain-language operator messages for
        credential/LLM/login failures the pre-fill loop degraded gracefully
        from — surfaced so the failure is visible instead of silently lost.
        Process-global (not campaign-scoped), like ``admin_logs``/``admin_stealth``.
        """
        return await self._request("GET", "/api/admin/prefill-diagnostics")

    async def admin_lessons(self, ats: Optional[str] = None) -> Any:
        """Verbal Reflexion failure lessons the loop has learned (dark-engine audit #44).

        With ``ats`` omitted, every recorded lesson grouped by ATS domain; with
        ``ats`` given, just the lessons for that one domain — the same read the
        engine's pre-fill loop performs before its next fill attempt on it.
        Process-global (not campaign-scoped), like ``admin_prefill_diagnostics``.
        """
        if ats:
            return await self._request("GET", f"/api/admin/lessons/{ats}")
        return await self._request("GET", "/api/admin/lessons")

    async def admin_routines(self) -> Any:
        """Induced per-ATS routines — the self-improvement flywheel's memory of what
        worked (dark-engine audit #45).

        After a successful pre-fill on a given ATS the engine induces a reusable
        routine (the compact op-sequence that worked, keyed by domain) so the next
        application to that ATS is guided rather than re-derived cold. Read-only
        list of every domain the loop has learned a routine for: step count,
        success/failure counts, and net score. Process-global (not campaign-scoped),
        like ``admin_lessons``/``admin_prefill_diagnostics``.
        """
        return await self._request("GET", "/api/admin/routines")

    async def admin_run_retention_sweep(self, days: Optional[int] = None) -> Any:
        """Run the PII-retention sweep now (dark-engine audit #37).

        ``DataLifecycleService.prune_pii_older_than`` (#363) was previously
        reachable only from the dormant scheduler tick. This runs it
        synchronously and returns the real per-store pruned counts. With
        ``days`` omitted, the engine uses the currently persisted Settings >
        Automation retention window (falling back to its env default);
        passing ``days`` overrides it for this one run only and is not saved.
        """
        params = {"days": days} if days is not None else None
        return await self._request("POST", "/api/admin/retention/prune", params=params)

    # -- ACE playbook deltas (dark-engine audit item 46) ---------------------
    # A curated, per-ATS set of strategy bullets kept current via structured
    # add/revise/retire deltas (PlaybookService.apply_deltas) rather than a
    # wholesale rewrite — distinct from the free-text saved-playbook skills
    # above (chat's save_playbook/update_playbook). Campaign-scoped, persisted
    # on the campaign's learning_state.

    async def playbook(self, campaign_id: str, ats: str) -> Any:
        """One ATS's curated playbook: entries + the applied-delta audit trail."""
        return await self._request(
            "GET", f"/api/agent-memory/playbooks/{ats}", params={"campaign_id": campaign_id}
        )

    async def apply_playbook_deltas(self, campaign_id: str, ats: str, deltas: list[dict]) -> Any:
        """Apply structured add/revise/retire deltas to one ATS's playbook."""
        return await self._request(
            "POST",
            f"/api/agent-memory/playbooks/{ats}/apply-deltas",
            json={"campaign_id": campaign_id, "deltas": deltas},
        )

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

    async def post_submission_attention(self, campaign_id: str) -> Any:
        """Ghosted applications + drafted (never auto-sent) follow-ups awaiting
        review for one campaign (dark-engine audit B2 items 8/9/60) -- the
        scheduler's daily ghosting-detection + follow-up-drafting sweep
        (``PostSubmissionService.run_post_submission_sweep``) materializes both
        as pending actions; this reads that SAME substrate back, filtered to
        just these two kinds."""
        return await self._request("GET", f"/api/post-submission/{campaign_id}/attention")

    async def follow_up_approve(
        self,
        application_id: str,
        *,
        subject: str | None = None,
        body: str | None = None,
        delay_hours: float | None = None,
    ) -> Any:
        """Approve + schedule a drafted follow-up for sending (dark-engine
        audit B2 item 7) -- the ONLY caller of the engine's
        ``PostSubmissionService.schedule_follow_up`` anywhere in the product.
        ``subject``/``body`` (optional) let the owner edit the draft before
        approving; omitted fields are sent as absent so the engine keeps
        exactly what was drafted."""
        payload: dict = {}
        if subject is not None:
            payload["subject"] = subject
        if body is not None:
            payload["body"] = body
        if delay_hours is not None:
            payload["delay_hours"] = delay_hours
        return await self._request(
            "POST",
            f"/api/post-submission/applications/{application_id}/follow-up/approve",
            json=payload,
        )

    async def tracker_record_outcome(
        self, application_id: str, outcome_type: str, reason: str | None = None
    ) -> Any:
        """Manually record an outcome (interview/offer/rejected/ghosted/...).

        ``reason`` (dark-engine audit item 11) is an optional free-text note --
        meaningful for ``outcome_type == "rejected"`` -- persisted by the engine
        as a ``RejectionSignal`` audit-trail row alongside the real §7
        transition. Omitted entirely from the request body when not provided,
        so the engine's default (``None``) behavior is unaffected.
        """
        payload: dict = {"outcome_type": outcome_type}
        if reason:
            payload["reason"] = reason
        return await self._request(
            "POST",
            f"/api/post-submission/applications/{application_id}/outcome",
            json=payload,
        )

    async def tracker_archive_application(self, application_id: str) -> Any:
        """Close out a dead application (dark-engine audit item 13)."""
        return await self._request(
            "POST", f"/api/post-submission/applications/{application_id}/archive"
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

    async def tracker_application_history(self, campaign_id: str, limit: int = 200) -> Any:
        """Per-application history detail (status, work mode, screenshot count,
        recorded outcomes) for the owner-facing Tracker's "View details"
        disclosure (dark-engine audit #25). Hits the EXACT SAME engine read the
        admin Debug modal's drill-down already uses (``admin_application_
        history`` / ``GET /api/admin/history/{campaign_id}``) — this is just an
        owner-scoped name/route for the same data, reached without the admin
        gate. Returns every application in the campaign; the caller narrows to
        the one row it needs."""
        return await self._request(
            "GET", f"/api/admin/history/{campaign_id}", params={"limit": limit}
        )

    # -- paused/stuck applications (engine routers/admin.py, dark-engine audit
    #    #62) ------------------------------------------------------------------
    # After repeated failed resume attempts the engine loop stops re-driving an
    # application and fires one deduped notification; these expose the give-up
    # list itself + a way to clear it (previously only a full process restart
    # could unstick an application, and nothing could even list which ones were
    # stuck).

    async def admin_stuck_applications(self, campaign_id: str) -> Any:
        """Applications the engine loop has given up re-driving, for one campaign."""
        return await self._request("GET", f"/api/admin/stuck-applications/{campaign_id}")

    async def admin_retry_stuck_application(self, application_id: str) -> Any:
        """Clear one application's give-up flag so the loop re-drives it next tick."""
        return await self._request(
            "POST", f"/api/admin/stuck-applications/{application_id}/retry"
        )

    # dark-engine audit #78: the resume backoff (last-resume + fixed 300s window)
    # gates how often the loop re-drives a blocked application -- until now nothing
    # could tell an owner WHEN the loop would next check on one after they cleared
    # a blocker (answered a question, supplied a missing detail, approved a
    # redline).
    async def admin_resume_status(self, application_id: str) -> Any:
        """Countdown to the loop's next resume attempt for one application, or
        ``{"status": "not_blocked"}`` when it isn't currently backed off."""
        return await self._request("GET", f"/api/admin/resume-status/{application_id}")

    # dark-engine audit #76: the capped deep-research escalation folds a company
    # report into an application's materials, but which report (if any) informed
    # them lived only in the orchestrator's checkpoint until now.
    async def admin_research_provenance(self, application_id: str) -> Any:
        """Which company research (if any) informed one application's materials."""
        return await self._request("GET", f"/api/admin/research-provenance/{application_id}")

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

    async def emergency_handoff(self, application_id: str) -> Any:
        """The emergency copy/paste handoff values for an application (FR-PREFILL-7):
        what the agent would have filled in, for the user to paste into their own
        browser and finish by hand after a hard fill failure (or a near-empty
        "wrong ATS" fill, #177)."""
        return await self._request(
            "GET", f"/api/remote/applications/{application_id}/emergency-handoff"
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

    async def vault_rotate_key(self) -> Any:
        """Rotate the vault's master encryption key — mints a fresh key and
        re-seals every stored credential under it (no secrets returned)."""
        return await self._request("POST", "/api/credentials/rotate-key")

    # -- manual deep-research trigger (engine routers/research.py) ----------
    # The agent auto-escalates to research already; these expose the engine's
    # SAME capped/deduped/cached path as an explicit, user-initiated run + a
    # budget read. ``run`` returns the structured report (200 with
    # ``unavailable: true`` + ``reason`` when the channel is off / budget is
    # exhausted — a degraded state, not an error).

    async def research_run(self, campaign_id: str, body: dict) -> Any:
        """Run (or reuse) deep research for a campaign — the manual trigger."""
        return await self._request("POST", f"/api/research/{campaign_id}/run", json=body)

    async def research_cached(self, campaign_id: str, query: str) -> Any:
        """Read an already-cached report for free (dark-engine audit item 38) —
        no fresh run, no budget spent. Raises a 404 :class:`EngineError` when
        nothing is cached yet for this exact (campaign, query)."""
        return await self._request(
            "GET", f"/api/research/{campaign_id}/cached", params={"query": query}
        )

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

    # -- blocked applications (engine routers/admin.py, dark-engine audit #61) -
    # G07's pre-submit safety checks (scam/ghost-job, duplicate cooldown,
    # per-company volume cap, eligibility/work-authorization) run every tick
    # against every APPROVED application; a block previously left the posting
    # APPROVED forever with only a log line -- these expose the block list
    # itself (reason + how many times it has recurred) plus an override so an
    # owner can decide to proceed anyway (mirrors the stuck-applications pair,
    # #62, above).

    async def admin_blocked_applications(self, campaign_id: str) -> Any:
        """Applications the pre-submit safety gate has stopped on, for one campaign."""
        return await self._request("GET", f"/api/admin/blocked-applications/{campaign_id}")

    async def admin_override_blocked_application(self, application_id: str) -> Any:
        """Proceed with one blocked application anyway, on the owner's decision."""
        return await self._request(
            "POST", f"/api/admin/blocked-applications/{application_id}/override"
        )

    # -- capability disclosure (engine routers/mcp.py, dark-engine audit item
    #    24) -------------------------------------------------------------------
    # The engine's native, dependency-free MCP tool surface (``GET /mcp/tools``)
    # advertises the exact read-only tools the agent/external MCP clients can
    # call (list_campaigns / get_attributes / get_applications /
    # get_pending_actions / health) -- but nothing in the front door ever
    # showed the owner what the assistant can actually do. This is a plain,
    # read-only proxy of that SAME list (mirrors the ``tools/list`` JSON-RPC
    # shape the engine already returns) -- no new engine logic, no fabricated
    # tools, and consequential actions (final submit) are deliberately absent
    # from the engine's own list, so they can never appear here either.

    async def mcp_tools_list(self) -> Any:
        """The engine's advertised MCP tool surface: ``{"tools": [{"name",
        "description", "inputSchema"}, ...]}``. Gated at the engine layer behind
        ``require_llm_configured`` (409 until the LLM is connected) -- forwarded
        honestly as a GATED state by the caller, never silently emptied."""
        return await self._request("GET", "/mcp/tools")


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
