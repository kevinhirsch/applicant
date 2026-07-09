"""Health/capability-report router (P1-3, issue #655: "Honest health panel").

Exposes the boot-time capability self-report (``app/capability_report.py``,
#188) over HTTP so the front-door can surface it to the owner instead of it
only ever reaching a container log. Deliberately UNGATED — registered
alongside ``setup``/``model_endpoints``/``ui`` (the pre-gate group in
``routers/__init__.py``) rather than behind ``require_llm_configured``: the
whole point is to tell an owner WHY automated work hasn't started (e.g. no
browser binary, no reachable Postgres), which must be visible even before an
LLM is connected. Read-only and side-effect-free — it re-runs the same
``shutil.which()``/connection-object checks ``/healthz`` already performs at
every request, nothing more.
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends

from applicant.app.capability_report import api_capability_report
from applicant.app.container import Container
from applicant.app.deps import get_container
from applicant.version import __version__

router = APIRouter(prefix="/api/health", tags=["health"])


@router.get("/capabilities")
def capabilities(container: Container = Depends(get_container)) -> dict:
    """The honest health panel: postgres / résumé renderer / browser /
    orchestrator, each real-vs-stub with a plain-language label and
    actionable fix copy when degraded (never a bare red dot).

    Mirrors the exact detection ``/healthz`` and the startup log already run
    (``applicant.observability.capabilities.capability_status``) — this adds
    no new probing, only the operator-facing shape (`` api_capability_report``
    layers in labels/fix-copy/load_bearing over the shared #188 report).

    Also carries the running engine's ``version`` (P3-5, release engineering)
    — the same :data:`applicant.version.__version__` the FastAPI app itself
    advertises — so the front-door health panel can surface a real running
    version instead of the engine being the only place it's ever visible
    (reachability principle: a fact that only ever reaches a container log or
    an internal-only ``/healthz`` isn't "done").
    """
    report = api_capability_report(
        browser_real=getattr(container.settings, "browser_real", False),
        postgres_engine=getattr(container, "engine", None),
    )
    return {
        **report,
        # Explicit keys go AFTER the spread so they always win — a future
        # ``version``/``generated_at`` key in the report can never silently
        # shadow the real engine version or the freshly-stamped timestamp.
        "generated_at": datetime.now(UTC).isoformat(),
        "version": __version__,
    }
