# routes/applicant_followups_routes.py
"""Post-submission "attention" feed proxy (dark-engine audit B2 items 8/9/60).

The scheduler now runs a daily per-campaign sweep
(``Scheduler._run_post_submission_sweep`` -> ``PostSubmissionService.
run_post_submission_sweep``) that (1) flags any application silent past the
ghosting SLA and (2) drafts a review-only, NEVER-auto-sent follow-up message for
an application still awaiting response past the follow-up-due window. Both are
materialized as ``PendingAction`` rows through the SAME substrate the Portal
already renders generically (CLAUDE.md principle #3 — reuse the Portal, no new
UI) — a ghosted application or a drafted follow-up already shows up there and
can be resolved through the existing pending-actions resolve path.

This is a thin, ADDITIVE owner-scoped READ over the engine's new
``GET /api/post-submission/{campaign_id}/attention`` endpoint so the same state
is independently queryable per campaign (e.g. for a future dedicated Tracker
panel — deferred; see ``docs/design/audits/exhaustive2/08_engine_dark_matrix.md``
§B2 items 7/10 for the still-out-of-scope send-queue/rejection-scan wiring).
It adds no engine logic; the engine owns the sweep + the pending-action
materialization. Mirrors ``applicant_tracker_routes.py``'s owner-isolation
pattern: ``campaign_id`` is validated against THIS request's own
``list_campaigns()`` fan-out before the read is forwarded — never trust a
caller-supplied campaign id.

Endpoint (one prefix, ``/api/applicant/followups``):

* ``GET /api/applicant/followups/{campaign_id}`` — the ``ghosted`` +
  ``followups_due`` pending-action rows for one of the owner's OWN campaigns.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Request

from src.applicant_engine import ApplicantEngineClient, EngineError, soft_degrade
from src.auth_helpers import require_user

logger = logging.getLogger(__name__)


def _require_user(request: Request) -> str:
    """Require an authenticated owner (the global gate also enforces this)."""
    return require_user(request)


def _empty(campaign_id: str) -> dict:
    """The well-formed empty body every soft-degrade / not-found path returns."""
    return {"campaign_id": campaign_id, "ghosted": [], "followups_due": []}


def setup_applicant_followups_routes() -> APIRouter:
    router = APIRouter(prefix="/api/applicant/followups", tags=["applicant-followups"])

    @router.get("/{campaign_id}")
    async def attention(request: Request, campaign_id: str) -> dict:
        """Ghosted applications + drafted follow-ups awaiting review for ONE OF
        THE OWNER'S OWN campaigns (dark-engine audit B2 items 8/9/60).

        ``campaign_id`` is validated against this request's own
        ``list_campaigns()`` fan-out BEFORE the read is forwarded — the same
        never-trust-a-caller-supplied-id guard ``applicant_tracker_routes.py``
        uses. Degrades soft: an unreachable engine returns ``engine_available:
        false``; a setup gate returns ``gated: true``; a campaign that doesn't
        belong to this owner 404s.
        """
        _require_user(request)
        empty = _empty(campaign_id)
        async with ApplicantEngineClient() as engine:
            try:
                campaigns = await engine.list_campaigns()
            except EngineError as exc:
                logger.debug("followups: campaigns read failed: %s", exc)
                return soft_degrade(exc, empty)
            owned = {
                str(c.get("id"))
                for c in campaigns
                if isinstance(c, dict) and c.get("id")
            } if isinstance(campaigns, list) else set()
            if campaign_id not in owned:
                raise HTTPException(status_code=404, detail="No such campaign.")
            try:
                data = await engine.post_submission_attention(campaign_id)
            except EngineError as exc:
                logger.debug(
                    "followups: attention read failed for %s: %s", campaign_id, exc
                )
                return soft_degrade(exc, empty)
        if not isinstance(data, dict):
            return {**empty, "engine_available": True}
        return {
            "engine_available": True,
            "campaign_id": campaign_id,
            "ghosted": data.get("ghosted") if isinstance(data.get("ghosted"), list) else [],
            "followups_due": (
                data.get("followups_due") if isinstance(data.get("followups_due"), list) else []
            ),
        }

    return router
