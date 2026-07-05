# routes/applicant_research_routes.py
"""Manual deep-research trigger ↔ engine bridge.

The autonomous agent already auto-escalates to deep research on a knowledge gap
(capped/deduped/cached in the engine's ``ResearchService``). This proxy exposes
the engine's *manual* counterpart to the front-door so a job-search user can kick
a research run themselves — e.g. "research this company/role" from a daily-updates
row — and read the structured report back.

This is a thin, auth-protected, owner-scoped proxy over
:class:`src.applicant_engine.ApplicantEngineClient`. The browser never reaches the
engine directly. It mirrors the other ``applicant_*`` proxies: business logic and
the per-campaign budget live in the engine; this layer only forwards and maps
failures to clean HTTP responses.

Endpoints (mount prefix ``/api/applicant/research``):

* ``POST /{campaign_id}/run``    — run (or reuse) deep research for a campaign.
* ``GET  /{campaign_id}/cached`` — read an already-cached report for free
  (dark-engine audit item 38), without burning a research run, or a 404 when
  nothing is cached yet for that (campaign, query).
* ``GET  /{campaign_id}/budget`` — read the campaign's research budget + channel
  availability.

Engine contract (``src/applicant/app/routers/research.py``):

* The run returns a 200 with the structured report (``summary`` / ``key_findings``
  / ``sources`` + ``budget_remaining``). When the research channel is off or the
  per-campaign budget is exhausted it STILL returns 200, with ``unavailable: true``
  and a ``reason`` — a degraded state, not a server error. We pass that straight
  through so the UI can show a graceful "research isn't set up / budget used" note.
* An empty query is a 422 on the engine; we forward that status + detail.
* The cached-read is a plain 404 (not the run's degraded 200) when nothing is
  cached — the UI treats that as "fall back to a fresh run", not an error state.
* A transport failure (engine down / timeout) is normalised to a 503 here so the
  surface degrades gracefully instead of throwing.
"""

from __future__ import annotations

import logging

import httpx
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from src.applicant_engine import ApplicantEngineClient, EngineError
from src.auth_helpers import require_user

logger = logging.getLogger(__name__)

# A deep-research run is heavy: the engine's ``ResearchService`` calls back into
# the workspace's OWN multi-source researcher (search + LLM synthesis), which can
# legitimately run for minutes -- the caller's ``max_time`` (engine-side clamped
# to 30-600s, `applicant_internal_routes.py`'s ``_RESEARCH_MIN/MAX_MAX_TIME`)
# bounds that budget. The client's default 30s read timeout (lens 04 #10) 502'd
# every run that took longer than a trivial cache hit. Give this ONE call (not
# the client's other, cheap reads) a read window sized off the caller's own
# ``max_time`` -- generous default when omitted, always at least the engine-side
# floor plus buffer, capped so a misbehaving request can't hold the connection
# open forever -- mirroring how ``applicant_documents_routes.py``'s redline
# ``_TURN_TIMEOUT`` overrides the client's timeout for its own heavy write.
_RESEARCH_RUN_MIN_TIMEOUT = 60.0
_RESEARCH_RUN_DEFAULT_TIMEOUT = 210.0
_RESEARCH_RUN_MAX_TIMEOUT = 630.0
_RESEARCH_RUN_BUFFER = 30.0


def _research_run_timeout(max_time: int | None) -> httpx.Timeout:
    """Read-timeout for the research ``run`` proxy call, overridable by the
    caller's own ``max_time`` (falls back to a generous default when omitted)."""
    read = _RESEARCH_RUN_DEFAULT_TIMEOUT if not max_time else float(max_time) + _RESEARCH_RUN_BUFFER
    read = max(_RESEARCH_RUN_MIN_TIMEOUT, min(read, _RESEARCH_RUN_MAX_TIMEOUT))
    return httpx.Timeout(connect=3.0, read=read, write=10.0, pool=3.0)


# --- request body -----------------------------------------------------------


class ResearchRunIn(BaseModel):
    """Mirror of the engine's ``ResearchRequestIn`` (kept thin)."""

    query: str
    company: str | None = None
    role: str | None = None
    context: str | None = None
    max_time: int | None = None
    #: Re-run even when a cached report exists (still charged against the cap).
    force: bool = False


# --- helpers ----------------------------------------------------------------


def _require_user(request: Request) -> str:
    """Require an authenticated owner (the global gate also enforces this)."""
    return require_user(request)


def _engine_http_error(exc: EngineError) -> HTTPException:
    """Translate a typed :class:`EngineError` into an HTTPException for a *write*.

    A transport-level failure (no ``status``) means the engine is unreachable →
    503. 4xx responses are forwarded (client-correctable: 422 empty-query, 404
    unknown campaign). 5xx responses are scrubbed — raw detail may contain
    internal stack traces or state; logged server-side only.
    """
    if exc.status is None:
        return HTTPException(
            status_code=503,
            detail="The Applicant engine is unavailable right now. Please try again shortly.",
        )
    if exc.status >= 500:
        logger.warning("engine 5xx (research): status=%s detail=%s", exc.status, exc.detail or exc.message)
        return HTTPException(status_code=502, detail="The Applicant engine returned an error.")
    detail = exc.detail if exc.detail not in (None, "") else exc.message
    return HTTPException(status_code=exc.status, detail=detail)


def setup_applicant_research_routes() -> APIRouter:
    router = APIRouter(prefix="/api/applicant/research", tags=["applicant-research"])

    @router.post("/{campaign_id}/run")
    async def run_research(campaign_id: str, body: ResearchRunIn, request: Request) -> dict:
        """Run (or reuse) deep research for a campaign — the manual trigger.

        Forwards the engine's report verbatim, including the 200 + ``unavailable``
        degraded payload (channel off / budget exhausted), so the UI can show a
        graceful state instead of an error. An empty query is rejected up front so
        the user is never bounced with a confusing 422 round-trip.
        """
        _require_user(request)
        if not (body.query or "").strip():
            raise HTTPException(status_code=422, detail="query must not be empty")
        payload = {
            "query": body.query,
            "company": body.company,
            "role": body.role,
            "context": body.context,
            "max_time": body.max_time,
            "force": body.force,
        }
        async with ApplicantEngineClient(timeout=_research_run_timeout(body.max_time)) as engine:
            try:
                result = await engine.research_run(campaign_id, payload)
            except EngineError as exc:
                raise _engine_http_error(exc) from exc
        return result if isinstance(result, dict) else {}

    @router.get("/{campaign_id}/cached")
    async def cached_research(campaign_id: str, query: str, request: Request) -> dict:
        """Read an already-cached report for free — no fresh run, no budget spent.

        Lets the UI check for a report it already paid for before deciding to
        kick a fresh (budget-charged) run. A plain 404 when nothing is cached
        yet for this exact (campaign, query) is forwarded as-is; the caller
        falls back to ``POST .../run``.
        """
        _require_user(request)
        if not (query or "").strip():
            raise HTTPException(status_code=422, detail="query must not be empty")
        async with ApplicantEngineClient() as engine:
            try:
                result = await engine.research_cached(campaign_id, query)
            except EngineError as exc:
                raise _engine_http_error(exc) from exc
        return result if isinstance(result, dict) else {}

    @router.get("/{campaign_id}/budget")
    async def research_budget(campaign_id: str, request: Request) -> dict:
        """Read the campaign's research budget + channel availability.

        Soft-degrades: an unreachable engine returns a well-formed payload with
        ``engine_available: false`` so the UI can show a "research isn't set up"
        state rather than 5xx.
        """
        _require_user(request)
        async with ApplicantEngineClient() as engine:
            try:
                data = await engine.research_budget(campaign_id)
            except EngineError as exc:
                logger.debug("research_budget: engine unavailable: %s", exc)
                return {
                    "engine_available": False,
                    "campaign_id": campaign_id,
                    "available": False,
                    "calls_made": 0,
                    "budget_remaining": 0,
                }
        out = data if isinstance(data, dict) else {}
        out.setdefault("campaign_id", campaign_id)
        out["engine_available"] = True
        return out

    return router
