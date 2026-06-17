# routes/applicant_internal_routes.py
"""Stage 2.5 ENGINE -> WORKSPACE callback channel.

Today the Applicant bridge is one-directional: the front-door **workspace UI**
calls *into* the **engine** (``src/applicant_engine.py``, ``ENGINE_URL``). Stage
2.5 needs the *reverse* direction — the engine (the internal ``api`` container)
must be able to call BACK into the workspace ``applicant-ui`` app to read things
that only the front-door app knows: auto-detected interview calendar events
(lane A), deep-research runs (lane B), and Cookbook-served local models (lane C).

This module is the **shared channel + contract** for that reverse direction.
Three later lanes fill in the typed endpoints; this file only provides the
namespaced router (mounted at ``/api/applicant/internal/*``) plus a working
``ping`` and documented placeholders so the contract is concrete.

## Trust model (READ BEFORE EXTENDING)

The boundary is a **shared secret**, not the network alone. Unlike the existing
in-process loopback internal-tool path (``core.middleware.INTERNAL_TOOL_*`` in
``app.py``'s ``AuthMiddleware``), the engine calls the workspace from a *sibling
container on the private docker network*, so it is NOT loopback. This prefix is
therefore honored ONLY when:

1. ``APPLICANT_INTERNAL_TOKEN`` is configured (a strong secret shared by both
   containers via ``docker-compose.prod.yml`` + ``scripts/install.sh``). If it
   is unset, the entire prefix is DISABLED (every call -> 403). No token, no
   channel — there is no "open by default" fallback.
2. The request carries ``X-Applicant-Internal-Token`` matching that secret,
   compared with :func:`secrets.compare_digest` (constant time — no early-exit
   timing leak on the secret).

The gate lives in ``app.py``'s ``AuthMiddleware`` (a small, clearly-commented
branch keyed on this prefix) so an un-tokened request never reaches a handler.
This module ALSO re-checks the token defensively (defense in depth, and so the
router is safe to mount on a bare app in tests / if auth is disabled).

Every honored request is **owner-scoped**: the engine sets ``X-Applicant-Owner``
to the user the work is for, mirroring the impersonation attribution the loopback
internal-tool path already uses. Lanes MUST scope their reads/writes to
:func:`internal_owner` so one user's engine run can never read another user's
calendar / research / models.

## Lane contract (each lane implements its own placeholder below)

| Lane | Endpoint                                   | Returns |
|------|--------------------------------------------|---------|
| A    | ``GET  /api/applicant/internal/calendar/interviews`` | auto-detected interview events for the owner |
| B    | ``POST /api/applicant/internal/research``  | deep-research run for the owner |
| C    | ``GET  /api/applicant/internal/local-models`` | Cookbook-served local models |

See ``workspace/APPLICANT_INTEGRATION.md`` ("Stage 2.5 callback channel") for the
full contract + file-ownership map so the three lanes do not collide.
"""

from __future__ import annotations

import logging
import os
import secrets

from fastapi import APIRouter, HTTPException, Request

logger = logging.getLogger(__name__)

#: Header the engine sets to prove it holds the shared secret.
INTERNAL_TOKEN_HEADER = "X-Applicant-Internal-Token"
#: Header the engine sets to attribute the call to a specific workspace user.
INTERNAL_OWNER_HEADER = "X-Applicant-Owner"
#: Route prefix for the whole reverse channel. The AuthMiddleware branch in
#: app.py keys on this so an un-tokened request never reaches a handler.
INTERNAL_PREFIX = "/api/applicant/internal"


def internal_token() -> str:
    """The configured shared secret, or "" when the channel is DISABLED.

    Read live (not import-time) so tests can set/clear it via monkeypatch and so
    a deploy that injects the env after import still works.
    """
    return (os.environ.get("APPLICANT_INTERNAL_TOKEN") or "").strip()


def internal_channel_enabled() -> bool:
    """True only when a non-empty shared secret is configured."""
    return bool(internal_token())


def verify_internal_token(request: Request) -> None:
    """Defense-in-depth gate re-checked inside every handler.

    Raises 403 when the channel is disabled (no secret) or the presented
    ``X-Applicant-Internal-Token`` does not match (constant-time). The
    AuthMiddleware branch in app.py performs the same check earlier; this keeps
    handlers safe when mounted on a bare app (tests) or with auth disabled.
    """
    secret = internal_token()
    if not secret:
        # Channel disabled: never reveal whether a token would have matched.
        raise HTTPException(status_code=403, detail="Internal channel disabled")
    presented = request.headers.get(INTERNAL_TOKEN_HEADER) or ""
    if not secrets.compare_digest(presented, secret):
        raise HTTPException(status_code=403, detail="Invalid internal token")


def internal_owner(request: Request) -> str:
    """The owner the engine attributed this call to (``X-Applicant-Owner``).

    May be "" when the engine did not attribute the call (single-user / system
    work). Lanes MUST use this to scope their reads/writes — never trust an owner
    embedded in the body.
    """
    return (request.headers.get(INTERNAL_OWNER_HEADER) or "").strip()


# --- Lane B (research) bounds + helpers ----------------------------------
#: Default / floor / ceiling for the synchronous research run's max_time (sec).
_RESEARCH_DEFAULT_MAX_TIME = 180
_RESEARCH_MIN_MAX_TIME = 30
_RESEARCH_MAX_MAX_TIME = 600
#: Bound the returned report so the engine never gets an unbounded payload.
_RESEARCH_MAX_REPORT_CHARS = 60_000
_RESEARCH_MAX_SOURCES = 50
_RESEARCH_MAX_KEY_FINDINGS = 12


def _research_handler(request: Request):
    """The workspace's native deep-research handler, or None when unavailable.

    Prefers ``app.state.research_handler`` (wired in app.py). Tests inject a fake
    handler the same way, so the route is hermetic without booting the app.
    """
    return getattr(getattr(request.app, "state", None), "research_handler", None)


def _resolve_research_endpoint_safe():
    """Resolve (url, model, headers) for research via the same chain as the
    panel route, or None when nothing is configured. Never raises."""
    try:
        from src.endpoint_resolver import resolve_endpoint
    except Exception:
        return None
    for tier in ("research", "utility", "default", "chat"):
        try:
            url, model, headers = resolve_endpoint(tier)
        except Exception:
            continue
        if url:
            return url, model, headers
    return None


def _research_key_findings(findings) -> list:
    """Distill per-source findings into a short list of key points."""
    out: list = []
    for f in findings or []:
        if not isinstance(f, dict):
            continue
        point = (f.get("summary") or f.get("evidence") or "").strip()
        if not point:
            continue
        out.append(point[:500])
        if len(out) >= _RESEARCH_MAX_KEY_FINDINGS:
            break
    return out


def setup_applicant_internal_routes() -> APIRouter:
    router = APIRouter(prefix=INTERNAL_PREFIX, tags=["applicant-internal"])

    @router.get("/ping")
    async def ping(request: Request) -> dict:
        """Liveness + auth probe for the engine's WorkspacePort.

        Working now: the engine calls this from ``HttpWorkspaceClient.ping()`` to
        learn the channel is reachable AND the shared secret matches. Returns the
        attributed owner so the engine can confirm impersonation wiring.
        """
        verify_internal_token(request)
        return {"ok": True, "owner": internal_owner(request) or None}

    # --- Lane placeholders (501 until the owning lane implements them) -------
    # Each lane REPLACES its own stub here (this file is the shared channel) OR,
    # preferably, mounts its own router under the same prefix and registers it in
    # app.py. Keep the path + auth contract identical to what is documented.

    @router.get("/calendar/interviews")
    async def calendar_interviews(request: Request):
        """LANE A placeholder — auto-detected interview calendar events.

        Contract: owner-scoped (``internal_owner``) list of interview events the
        workspace auto-detected from the owner's calendar, shaped as
        ``{"interviews": [...]}``. 501 until lane A lands.
        """
        verify_internal_token(request)
        raise HTTPException(status_code=501, detail="calendar/interviews not implemented (lane A)")

    @router.post("/research")
    async def research(request: Request):
        """LANE B — run the workspace's native deep-research for the owner.

        Synchronous "run and return the report" call for the engine: the engine
        hits this when its autonomous agent (or the user) needs to understand a
        company/role to tailor materials. Owner-scoped via ``internal_owner`` and
        bounded (timeout + report length) so a runaway run can't wedge the
        engine's request.

        Body: ``{"query": str, "company"?: str, "role"?: str, "context"?: str,
        "max_time"?: int}``. The optional fields are folded into the research
        query so the report is tailored to the application.

        Returns a structured report:
        ``{"query", "summary", "key_findings": [...], "sources": [{url,title}],
        "owner", "truncated": bool}``.
        """
        verify_internal_token(request)
        owner = internal_owner(request)

        try:
            body = await request.json()
        except Exception:
            body = {}
        if not isinstance(body, dict):
            body = {}

        query = (body.get("query") or "").strip()
        if not query:
            raise HTTPException(status_code=400, detail="research requires a non-empty 'query'")

        company = (body.get("company") or "").strip()
        role = (body.get("role") or "").strip()
        context = (body.get("context") or "").strip()

        # Bound the run: clamp the caller's max_time into a safe window so a
        # synchronous engine request can never hang on an unbounded research run.
        try:
            max_time = int(body.get("max_time") or _RESEARCH_DEFAULT_MAX_TIME)
        except (TypeError, ValueError):
            max_time = _RESEARCH_DEFAULT_MAX_TIME
        max_time = max(_RESEARCH_MIN_MAX_TIME, min(max_time, _RESEARCH_MAX_MAX_TIME))

        # Fold the optional application context into the research query so the
        # report is tailored to the role/company the engine is applying to.
        tailored = query
        prefix_bits = []
        if company:
            prefix_bits.append(f"company: {company}")
        if role:
            prefix_bits.append(f"role: {role}")
        if prefix_bits:
            tailored = f"{query} ({'; '.join(prefix_bits)})"
        if context:
            tailored = f"{tailored}\n\nAdditional context: {context}"

        handler = _research_handler(request)
        if handler is None:
            # Research backing not wired (e.g. bare app). Degrade, don't 500.
            raise HTTPException(status_code=503, detail="research backing unavailable")

        endpoint = _resolve_research_endpoint_safe()
        if endpoint is None:
            raise HTTPException(
                status_code=503,
                detail="no LLM endpoint configured for research",
            )
        ep_url, ep_model, ep_headers = endpoint

        # Run synchronously, capturing the researcher so we can extract sources.
        entry: dict = {}
        try:
            report = await handler.call_research_service(
                tailored,
                ep_url,
                ep_model,
                max_time=max_time,
                _task_entry=entry,
                llm_headers=ep_headers,
            )
        except Exception as exc:  # never leak the engine a 500 from a flaky run
            logger.warning("internal research run failed: %s", exc)
            raise HTTPException(status_code=502, detail="research run failed") from exc

        report = report or ""
        truncated = False
        if len(report) > _RESEARCH_MAX_REPORT_CHARS:
            report = report[:_RESEARCH_MAX_REPORT_CHARS]
            truncated = True

        # Sources: prefer the researcher's deduplicated findings.
        sources: list = []
        researcher = entry.get("researcher")
        findings = getattr(researcher, "findings", None) if researcher else None
        if findings:
            try:
                sources = handler._extract_sources(findings)
            except Exception:
                sources = []
        sources = sources[:_RESEARCH_MAX_SOURCES]

        return {
            "query": query,
            "summary": report,
            "key_findings": _research_key_findings(findings),
            "sources": sources,
            "owner": owner or None,
            "truncated": truncated,
        }

    @router.get("/local-models")
    async def local_models(request: Request):
        """LANE C placeholder — list Cookbook-served local models.

        Contract: ``{"models": [...]}`` of locally-served models the Cookbook is
        currently exposing. 501 until lane C lands.
        """
        verify_internal_token(request)
        raise HTTPException(status_code=501, detail="local-models not implemented (lane C)")

    return router
