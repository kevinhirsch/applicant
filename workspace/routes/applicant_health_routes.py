# routes/applicant_health_routes.py
"""Honest health panel ↔ engine bridge (P1-3, issue #655).

The engine's boot-time capability self-report (postgres, résumé renderer,
browser, orchestrator — real vs stub, #188 + P1-3's ``api_capability_report``)
only ever reached a container log until now. This proxy SURFACES that same
report in the front-door: a thin, auth-protected, owner-gated read over
:class:`src.applicant_engine.ApplicantEngineClient` (the browser never reaches
the engine directly). It adds no engine logic and creates no new engine
state — every capability, status, label and fix string rendered here is
exactly what the engine's own report returned.

Owner-gated (not merely ``require_user``): this reveals deploy-internal state
(database reachability, browser/renderer binaries) that only the instance's
real owner should see in a multi-account workspace — mirrors every other
engine-backed proxy that surfaces the single-tenant engine's own state
(``applicant_activity_routes.py`` / ``applicant_results_routes.py`` /
``require_engine_owner``'s own docstring).

Degrades soft, honestly, per the H-series invariants (an absence of a check
must never render as a check):

* the engine is genuinely unreachable → ``engine_available: false`` with a
  well-formed EMPTY capability list — the front-end renders ONE designed
  "can't reach the assistant" banner for this, never blank/broken sections;
* a gate (there is none on this engine endpoint today, but the shared
  ``soft_degrade`` helper is reused for consistency with every sibling proxy,
  and so a future engine-side gate degrades the same honest way here too)
  → ``gated: true`` with the engine's own plain-language message.

Endpoint (one route, no campaign scoping — capability status is
deploy-global, not per-campaign):

* ``GET /api/applicant/health/capabilities`` — the panel payload: each
  capability's ``name``/``label``/``status``/``detail``/``load_bearing``/
  ``fix``, plus ``degraded``/``load_bearing_degraded``/``all_real`` rollups
  the front-end uses to decide whether to show the Today banner.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Request

from src.applicant_engine import (
    ApplicantEngineClient,
    EngineError,
    shared_engine_http_client,
    soft_degrade,
)
from src.auth_helpers import require_engine_owner

logger = logging.getLogger(__name__)


def _clean_capabilities(raw: object) -> list[dict]:
    """Normalise the engine's ``capabilities`` list, dropping anything
    malformed. Never invents a capability the engine didn't actually report."""
    caps = raw if isinstance(raw, list) else []
    out: list[dict] = []
    for c in caps:
        if not isinstance(c, dict):
            continue
        name = str(c.get("name") or "").strip()
        if not name:
            continue
        out.append(
            {
                "name": name,
                "label": str(c.get("label") or name).strip(),
                "status": str(c.get("status") or "").strip(),
                "detail": str(c.get("detail") or "").strip(),
                "load_bearing": bool(c.get("load_bearing")),
                "fix": str(c.get("fix") or "").strip(),
            }
        )
    return out


def _clean_names(raw: object) -> list[str]:
    return [str(n) for n in raw if isinstance(n, (str, int))] if isinstance(raw, list) else []


def setup_applicant_health_routes() -> APIRouter:
    router = APIRouter(prefix="/api/applicant/health", tags=["applicant-health"])

    @router.get("/capabilities")
    async def capabilities(request: Request) -> dict:
        """The honest health panel: postgres / résumé renderer / browser /
        orchestrator, real-vs-stub with actionable fix copy. Owner-gated read
        (``require_engine_owner``). Degrades soft: an unreachable engine
        returns ``engine_available: false`` with a well-formed empty list — a
        single designed banner, never blank sections."""
        require_engine_owner(request)
        empty = {
            "capabilities": [],
            "degraded": [],
            "load_bearing_degraded": [],
            "all_real": True,
        }
        async with ApplicantEngineClient(client=shared_engine_http_client(request)) as engine:
            try:
                data = await engine.health_capabilities()
            except EngineError as exc:
                logger.warning(
                    "health/capabilities: engine read failed (status=%s): %s", exc.status, exc
                )
                return soft_degrade(exc, empty)

        payload = data if isinstance(data, dict) else {}
        return {
            "engine_available": True,
            "generated_at": payload.get("generated_at") or "",
            # Running engine version (P3-5, release engineering) — proxied
            # verbatim, never invented, so the panel can show a real version
            # instead of the engine being the only reachable place it shows up.
            "version": str(payload.get("version") or ""),
            "capabilities": _clean_capabilities(payload.get("capabilities")),
            "degraded": _clean_names(payload.get("degraded")),
            "load_bearing_degraded": _clean_names(payload.get("load_bearing_degraded")),
            "all_real": bool(payload.get("all_real", True)),
        }

    return router
