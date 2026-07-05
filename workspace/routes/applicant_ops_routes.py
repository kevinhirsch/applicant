# routes/applicant_ops_routes.py
"""Applicant operations surface ↔ engine bridge (crit-ops lane).

Three operator controls the front-door needs but had no proxy/UI for:

* **Update** — the in-UI one-click update (no SSH/CLI): read the update surface
  status and trigger the guarded one-liner update on the engine.
* **Run controls** — how the job agent runs a campaign: run mode (around-the-clock
  / fixed window / until a target number of viable roles), the daily throughput
  target (clamped to the engine's hard cap), and the latest plain-language
  per-run *intent* sentence + recent run stats.
* **Discovery sources** — turn each job source on/off and read its learned yield
  stats, so the user steers where roles are found.

Every endpoint is a thin, auth-protected proxy over
:class:`src.applicant_engine.ApplicantEngineClient`. The browser never reaches
the engine directly; engine failures are normalised to clean HTTP responses.

Scoping: these are owner/admin controls (they change how automated work runs and
can trigger an update), so they require an admin account (and an authenticated
session in every mode). In single-user / unconfigured mode the lone owner sees
them, matching the rest of the workspace.

This file is ADDITIVE and disjoint from the other ``applicant_*`` proxies: it
mounts its own ``/api/applicant/ops`` prefix and only uses the append-only
engine-client methods this lane added.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from src.applicant_engine import ApplicantEngineClient, EngineError, soft_degrade
from src.auth_helpers import get_current_user

logger = logging.getLogger(__name__)

#: Run modes the engine accepts (mirrors routers/agent_runs.py). Kept here so the
#: proxy can reject a bad value with a clean 400 instead of bouncing off the
#: engine. Plain-language labels live in the UI module.
_RUN_MODES = {"continuous", "fixed_duration", "until_n_viable"}


# --- request bodies ---------------------------------------------------------


class ConfigureRunIn(BaseModel):
    run_mode: str | None = None
    throughput_target: int | None = None
    schedule: dict | None = None


class ToggleSourceIn(BaseModel):
    enabled: bool


class ExplorationBudgetIn(BaseModel):
    exploration_budget: float


# --- helpers ----------------------------------------------------------------

#: Headers that prove a request was forwarded by a proxy/tunnel (cloudflared,
#: nginx, Caddy, Tailscale Funnel, ...). Such a proxy/tunnel connects to this
#: app FROM loopback, so a bare ``client.host in ("127.0.0.1", "::1")`` check
#: would let a remote, unauthenticated caller inherit local trust and reach
#: these operator controls (update / run controls / discovery sources) while
#: auth isn't configured yet. Mirrors ``workspace/app.py``'s
#: ``_is_trusted_loopback`` — the same class of forwarded-loopback spoofing
#: this proxy must also refuse to fail open on.
_PROXY_FWD_HEADERS = (
    "cf-connecting-ip", "cf-ray", "cf-visitor",
    "x-forwarded-for", "x-forwarded-host", "x-real-ip", "forwarded",
)


def _is_trusted_loopback(request: Request) -> bool:
    """True ONLY for a DIRECT loopback connection with no proxy/tunnel
    forwarding headers present. Used to gate the narrow first-run bypass
    below — never treat a tunneled/forwarded request as local just because
    the immediate TCP peer happens to be loopback."""
    client = getattr(request, "client", None)
    host = (getattr(client, "host", "") if client else "") or ""
    if host not in ("127.0.0.1", "::1"):
        return False
    for header in _PROXY_FWD_HEADERS:
        if request.headers.get(header):
            return False
    return True


def _require_admin(request: Request) -> str:
    """Require an authenticated admin (or the lone owner in single-user mode)."""
    owner = get_current_user(request)
    auth_mgr = getattr(request.app.state, "auth_manager", None)
    configured = bool(getattr(auth_mgr, "is_configured", False)) if auth_mgr else False

    if not configured:
        # First-run: allow the lone owner, but only from a DIRECT loopback
        # connection — a remote unauthenticated caller (including one arriving
        # via a tunnel/reverse-proxy that merely connects to us from loopback)
        # must not reach operator controls during setup (#228). Fail closed:
        # any ambiguity about the caller's true origin raises 401 rather than
        # falling through to the bypass.
        if owner:
            return owner
        if _is_trusted_loopback(request):
            return ""
        raise HTTPException(status_code=401, detail="Not authenticated")
    if not owner:
        raise HTTPException(status_code=401, detail="Not authenticated")
    try:
        is_admin = bool(auth_mgr.is_admin(owner))
    except Exception:
        logger.warning("Bare exception in applicant_ops_routes.py")
        is_admin = False
    if not is_admin:
        raise HTTPException(status_code=403, detail="This control is available to admins only.")
    return owner


#: Safe, plain-language fallback per 4xx status family, used whenever the
#: engine's own detail isn't safe to forward verbatim (see
#: :func:`_sanitize_4xx_detail`).
_GENERIC_4XX_MESSAGES = {
    400: "The request was invalid.",
    401: "Not authenticated.",
    403: "You don't have permission for this.",
    404: "That wasn't found.",
    409: "This action can't be completed right now.",
    422: "The submitted data was invalid.",
}
_DEFAULT_4XX_MESSAGE = "The request could not be completed."

#: A forwarded detail longer than this reads as raw internal output (a dump,
#: a page body, a trace) rather than a short, intentional client-facing
#: message — never forward it verbatim.
_MAX_SAFE_DETAIL_LEN = 300

#: Substrings that mark a "detail" string as raw internal output (a stack
#: trace, an HTML error page, a filesystem path) rather than a short,
#: intentional client-facing message.
_UNSAFE_DETAIL_MARKERS = (
    "Traceback (most recent call last)",
    "<html",
    "<!DOCTYPE",
    "site-packages",
    'File "',
)


def _sanitize_4xx_detail(status: int, detail: Any) -> str:
    """Return a safe, plain-language detail for a 4xx forwarded to the client.

    The engine's own ``detail`` is only forwarded verbatim when it is a short,
    plain string that reads like an intentional client-facing message. Anything
    else — a non-string body (e.g. a raw validation-error list/dict when the
    engine's JSON had no ``detail`` key), an empty value, or text shaped like a
    stack trace / HTML error page — is replaced with a generic, safe message
    for the status family instead. This never reveals internal field names,
    tracebacks, or raw response bodies to the client.
    """
    if (
        isinstance(detail, str)
        and detail.strip()
        and len(detail) <= _MAX_SAFE_DETAIL_LEN
        and not any(marker in detail for marker in _UNSAFE_DETAIL_MARKERS)
    ):
        return detail
    return _GENERIC_4XX_MESSAGES.get(status, _DEFAULT_4XX_MESSAGE)


def _engine_http_error(exc: EngineError) -> HTTPException:
    """Translate a typed :class:`EngineError` into an HTTPException for a *write*.

    4xx responses are forwarded (client-correctable) but SANITIZED — only a
    short, plain-language detail is passed through; anything else (a raw
    validation body, HTML, a stack trace) is replaced with a generic message
    for that status (see :func:`_sanitize_4xx_detail`). 5xx responses are
    always scrubbed — raw detail may contain internal stack traces; logged
    server-side only.
    """
    if exc.status is None:
        return HTTPException(
            status_code=503,
            detail="The Applicant engine is unavailable right now. Please try again shortly.",
        )
    if exc.status >= 500:
        logger.warning("engine 5xx (ops): status=%s detail=%s", exc.status, exc.detail or exc.message)
        return HTTPException(status_code=502, detail="The Applicant engine returned an error.")
    if exc.detail not in (None, ""):
        logger.debug("engine 4xx (ops): status=%s detail=%r", exc.status, exc.detail)
    detail = _sanitize_4xx_detail(exc.status, exc.detail)
    return HTTPException(status_code=exc.status, detail=detail)


def setup_applicant_ops_routes() -> APIRouter:
    router = APIRouter(prefix="/api/applicant/ops", tags=["applicant-ops"])

    # -- update -----------------------------------------------------------

    @router.get("/update")
    async def update_status(request: Request) -> dict:
        """Read the update surface status (soft-degrades when the engine is down)."""
        _require_admin(request)
        async with ApplicantEngineClient() as engine:
            try:
                data = await engine.update_status()
            except EngineError as exc:
                logger.debug("update_status: engine unavailable: %s", exc)
                return {"engine_available": False}
        out = data if isinstance(data, dict) else {}
        out["engine_available"] = True
        return out

    @router.post("/update/trigger")
    async def update_trigger(request: Request) -> dict:
        """Trigger the guarded one-click update on the engine.

        Safe by default: the engine only performs a real update when its operator
        has explicitly enabled it; otherwise it reports what *would* run. The
        ``started`` flag + ``message`` are passed straight through so the button
        can show the real outcome.
        """
        _require_admin(request)
        async with ApplicantEngineClient() as engine:
            try:
                result = await engine.update_trigger()
            except EngineError as exc:
                raise _engine_http_error(exc) from exc
        return result or {}

    # -- run controls (agent runs) ----------------------------------------

    @router.get("/runs/{campaign_id}")
    async def list_runs(campaign_id: str, request: Request) -> dict:
        """Recent runs for a campaign (intent sentence, mode, target, stats)."""
        _require_admin(request)
        async with ApplicantEngineClient() as engine:
            try:
                data = await engine.agent_runs_list(campaign_id)
            except EngineError as exc:
                logger.debug("list_runs: engine read failed (status=%s): %s", exc.status, exc)
                return soft_degrade(
                    exc, {"campaign_id": campaign_id, "count": 0, "items": []}
                )
        out = data if isinstance(data, dict) else {"items": data or []}
        out.setdefault("campaign_id", campaign_id)
        out.setdefault("items", [])
        out.setdefault("count", len(out.get("items") or []))
        out["engine_available"] = True
        return out

    @router.get("/runs/{campaign_id}/intent")
    async def run_intent(campaign_id: str, request: Request) -> dict:
        """The latest plain-language per-run intent sentence for a campaign."""
        _require_admin(request)
        async with ApplicantEngineClient() as engine:
            try:
                data = await engine.agent_run_intent(campaign_id)
            except EngineError as exc:
                logger.debug("run_intent: engine unavailable: %s", exc)
                return {"engine_available": False, "campaign_id": campaign_id, "intent": None}
        out = data if isinstance(data, dict) else {"intent": data}
        out.setdefault("campaign_id", campaign_id)
        out["engine_available"] = True
        return out

    @router.put("/runs/{campaign_id}/config")
    async def configure_run(campaign_id: str, body: ConfigureRunIn, request: Request) -> dict:
        """Set the run mode / daily throughput target / schedule for a campaign."""
        _require_admin(request)
        if body.run_mode is not None and body.run_mode not in _RUN_MODES:
            raise HTTPException(
                status_code=400,
                detail="Run mode must be one of: around-the-clock, fixed window, or until target.",
            )
        if body.throughput_target is not None and body.throughput_target < 0:
            raise HTTPException(status_code=400, detail="Daily target cannot be negative.")
        payload = {
            "run_mode": body.run_mode,
            "throughput_target": body.throughput_target,
            "schedule": body.schedule,
        }
        async with ApplicantEngineClient() as engine:
            try:
                result = await engine.agent_run_configure(campaign_id, payload)
            except EngineError as exc:
                raise _engine_http_error(exc) from exc
        return result or {}

    @router.get("/runs/{campaign_id}/status")
    async def run_status(campaign_id: str, request: Request) -> dict:
        """Live agent status: is it running, last/next tick, today's count, intent."""
        _require_admin(request)
        async with ApplicantEngineClient() as engine:
            try:
                data = await engine.agent_run_status(campaign_id)
            except EngineError as exc:
                logger.debug("run_status: engine read failed (status=%s): %s", exc.status, exc)
                return soft_degrade(exc, {"campaign_id": campaign_id})
        out = data if isinstance(data, dict) else {}
        out.setdefault("campaign_id", campaign_id)
        out["engine_available"] = True
        return out

    @router.post("/runs/{campaign_id}/run")
    async def run_now(campaign_id: str, request: Request) -> dict:
        """Run one agent tick immediately (no 60s wait) — the operator 'Run now'."""
        _require_admin(request)
        async with ApplicantEngineClient() as engine:
            try:
                result = await engine.agent_run_now(campaign_id)
            except EngineError as exc:
                raise _engine_http_error(exc) from exc
        return result or {}

    @router.post("/runs/{campaign_id}/pause")
    async def pause_run(campaign_id: str, request: Request) -> dict:
        """Pause this campaign's automated work (no restart needed)."""
        _require_admin(request)
        async with ApplicantEngineClient() as engine:
            try:
                result = await engine.agent_run_pause(campaign_id)
            except EngineError as exc:
                raise _engine_http_error(exc) from exc
        return result or {}

    @router.post("/runs/{campaign_id}/resume")
    async def resume_run(campaign_id: str, request: Request) -> dict:
        """Resume this campaign's automated work."""
        _require_admin(request)
        async with ApplicantEngineClient() as engine:
            try:
                result = await engine.agent_run_resume(campaign_id)
            except EngineError as exc:
                raise _engine_http_error(exc) from exc
        return result or {}

    # -- discovery sources ------------------------------------------------

    @router.get("/discovery/{campaign_id}")
    async def list_sources(campaign_id: str, request: Request) -> dict:
        """List job-discovery sources with on/off state + learned yield stats.

        Also carries the campaign's ``exploration_budget`` (the explore/exploit
        knob, FR-LEARN-6) so the Sources panel can show + edit it alongside the
        per-source toggles. The budget is read from the learning surface on the
        engine's criteria router; if that read fails it is simply omitted (the
        source list still renders).
        """
        _require_admin(request)
        async with ApplicantEngineClient() as engine:
            try:
                data = await engine.discovery_sources_list(campaign_id)
            except EngineError as exc:
                logger.debug("list_sources: engine read failed (status=%s): %s", exc.status, exc)
                return soft_degrade(exc, {"campaign_id": campaign_id, "items": []})
            budget = None
            try:
                sig = await engine._request("GET", f"/api/criteria/{campaign_id}/signature")
                if isinstance(sig, dict):
                    budget = sig.get("exploration_budget")
            except EngineError as exc:
                logger.debug("list_sources: exploration_budget unavailable: %s", exc)
        out = data if isinstance(data, dict) else {"items": data or []}
        out.setdefault("campaign_id", campaign_id)
        out.setdefault("items", [])
        if budget is not None:
            out["exploration_budget"] = budget
        out["engine_available"] = True
        return out

    # NB: this specific route is declared BEFORE the {source_key} catch-all below
    # so "exploration-budget" is not swallowed as a source key.
    @router.put("/discovery/{campaign_id}/exploration-budget")
    async def set_exploration_budget(
        campaign_id: str, body: ExplorationBudgetIn, request: Request
    ) -> dict:
        """Set the explore/exploit budget for a campaign (FR-LEARN-6).

        Routed through the engine's criteria/learning surface, which clamps + persists
        it. A bad value comes back as the engine's own 400.
        """
        _require_admin(request)
        async with ApplicantEngineClient() as engine:
            try:
                result = await engine._request(
                    "PUT",
                    f"/api/criteria/{campaign_id}/exploration-budget",
                    json={"exploration_budget": body.exploration_budget},
                )
            except EngineError as exc:
                raise _engine_http_error(exc) from exc
        return result or {}

    @router.put("/discovery/{campaign_id}/{source_key}")
    async def toggle_source(
        campaign_id: str, source_key: str, body: ToggleSourceIn, request: Request
    ) -> dict:
        """Turn one job-discovery source on or off for a campaign."""
        _require_admin(request)
        async with ApplicantEngineClient() as engine:
            try:
                result = await engine.discovery_source_toggle(
                    campaign_id, source_key, body.enabled
                )
            except EngineError as exc:
                raise _engine_http_error(exc) from exc
        return result or {}

    return router
