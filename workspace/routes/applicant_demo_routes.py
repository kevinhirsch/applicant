# routes/applicant_demo_routes.py
"""Seeded-demo banner + one-click "Clear demo data" proxy (P0-2, OWNER-scoped).

When the engine runs under ``DEMO_MODE=1`` an operator can load a coherent
synthetic dataset (5+ applications across every stage, a scored digest, a
tailored résumé with a real redline, a run history, ~15 activity entries, and a
populated Portal) so every screenshot / demo / fixture comes from consistent,
non-empty data. This front-door proxy is what makes that state *legible and
reversible from the white-labeled UI*: it lets the browser ask "is demo data
loaded?" (to show the persistent "Demo data" banner) and "clear it" (one click,
no residue) without ever reaching the engine directly.

It adds NO engine logic and creates no new engine state — it is a thin,
auth-protected proxy over :class:`src.applicant_engine.ApplicantEngineClient`,
modelled on the sibling ``applicant_snapshot_routes.py``:

* the owner is authenticated with :func:`require_engine_owner` — the engine is
  single-tenant, so the seeded rows belong to the ONE owner this instance was
  set up for; a second workspace account must not be able to read or wipe them
  (CLAUDE.md: gate owner data on reads AND writes);
* every failure degrades soft. The engine's seed router 404s when the engine is
  NOT in ``DEMO_MODE`` — so an :class:`EngineError` (that 404 included) simply
  reads as ``demo_active: false`` and the banner stays hidden. An unreachable
  engine is reported as ``engine_available: false`` with the same safe body.

Endpoints (one prefix, ``/api/applicant/demo``):

* ``GET  /api/applicant/demo/status`` — ``{demo_active, counts}`` for the banner;
* ``POST /api/applicant/demo/clear``  — purge the demo dataset (engine reset).
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Request

from src.applicant_engine import ApplicantEngineClient, EngineError
from src.auth_helpers import require_engine_owner

logger = logging.getLogger(__name__)


def _inactive(*, engine_available: bool = True) -> dict:
    """The safe body every soft-degrade path returns: demo simply not active."""
    return {
        "demo_active": False,
        "engine_available": engine_available,
        "counts": {},
    }


def setup_applicant_demo_routes() -> APIRouter:
    router = APIRouter(prefix="/api/applicant/demo", tags=["applicant-demo"])

    @router.get("/status")
    async def demo_status(request: Request) -> dict:
        """Whether the seeded demo dataset is currently loaded (banner state).

        Degrades soft: the engine's seed router 404s unless it runs under
        ``DEMO_MODE`` — so any :class:`EngineError` (that 404, a gate, or an
        offline engine) reads as ``demo_active: false`` and the banner hides.
        """
        require_engine_owner(request)
        async with ApplicantEngineClient() as engine:
            try:
                data = await engine.demo_status()
            except EngineError as exc:
                # 404 == engine not in DEMO_MODE (the common case); anything else
                # transient/gated — either way there is no demo banner to show.
                available = not (exc.is_timeout or exc.status is None)
                logger.debug("demo/status: soft-degrade (status=%s): %s", exc.status, exc)
                return _inactive(engine_available=available)
        if not isinstance(data, dict):
            return _inactive()
        counts = data.get("counts")
        return {
            "demo_active": bool(data.get("demo_active")),
            "engine_available": True,
            "campaign_id": data.get("campaign_id", ""),
            "counts": counts if isinstance(counts, dict) else {},
        }

    @router.post("/clear")
    async def demo_clear(request: Request) -> dict:
        """One-click clear of the seeded demo dataset (engine purge cascade).

        Owner-scoped WRITE: only the engine owner may wipe the seeded rows.
        Degrades soft — a 404 (engine not in ``DEMO_MODE``) or an offline engine
        returns ``cleared: false`` rather than throwing.
        """
        require_engine_owner(request)
        async with ApplicantEngineClient() as engine:
            try:
                data = await engine.demo_clear()
            except EngineError as exc:
                available = not (exc.is_timeout or exc.status is None)
                logger.debug("demo/clear: soft-degrade (status=%s): %s", exc.status, exc)
                return {"cleared": False, "engine_available": available, "counts": {}}
        counts = data.get("counts") if isinstance(data, dict) else {}
        return {
            "cleared": True,
            "engine_available": True,
            "counts": counts if isinstance(counts, dict) else {},
        }

    return router
