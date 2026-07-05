# routes/applicant_followups_routes.py
"""Post-submission "attention" feed proxy (dark-engine audit B2 items 7/8/9/60).

The scheduler runs a daily per-campaign sweep
(``Scheduler._run_post_submission_sweep`` -> ``PostSubmissionService.
run_post_submission_sweep``) that (1) flags any application silent past the
ghosting SLA and (2) drafts a review-only, NEVER-auto-sent follow-up message for
an application still awaiting response past the follow-up-due window. Both are
materialized as ``PendingAction`` rows through the SAME substrate the Portal
already renders generically (CLAUDE.md principle #3 — reuse the Portal, no new
UI) — a ghosted application or a drafted follow-up already shows up there and
can be DECLINED/dismissed through the existing pending-actions resolve path
(``applicant_portal_routes.py``'s ``POST /actions/{id}/resolve`` — this file
does not duplicate it).

This is a thin, ADDITIVE owner-scoped proxy over the engine's
``/api/post-submission/*`` router. It adds no engine logic; the engine owns
the sweep, the pending-action materialization, and (item 7) the send-queue
state machine. Mirrors ``applicant_tracker_routes.py``'s owner-isolation
pattern: a caller-supplied id is always validated against THIS request's own
engine fan-out before the write is forwarded — never trust a caller-supplied
id to opt a safety check in.

Endpoints (one prefix, ``/api/applicant/followups``):

* ``GET  /api/applicant/followups/{campaign_id}`` — the ``ghosted`` +
  ``followups_due`` pending-action rows for one of the owner's OWN campaigns.
* ``POST /api/applicant/followups/applications/{application_id}/approve`` —
  APPROVE a drafted follow-up for sending (dark-engine audit B2 item 7): the
  owner reviews the ``followup_draft`` pending action surfaced above,
  optionally edits the subject/body, and this schedules it onto the engine's
  send queue (``PostSubmissionService.schedule_follow_up`` via
  ``approve_follow_up_draft`` — the ONLY caller of that method in the whole
  engine, CLAUDE.md: a follow-up is user-facing outbound content and is never
  drafted-and-sent in one autonomous step). ``application_id`` is validated
  against THIS request's own ``followups_due`` fan-out before the write is
  forwarded, so a caller cannot approve a "draft" for an application that was
  never actually surfaced to them.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from src.applicant_engine import ApplicantEngineClient, EngineError, soft_degrade
from src.auth_helpers import require_user

logger = logging.getLogger(__name__)


def _require_user(request: Request) -> str:
    """Require an authenticated owner (the global gate also enforces this)."""
    return require_user(request)


def _empty(campaign_id: str) -> dict:
    """The well-formed empty body every soft-degrade / not-found path returns."""
    return {"campaign_id": campaign_id, "ghosted": [], "followups_due": []}


class ApproveFollowUpIn(BaseModel):
    """Optional owner edits to the drafted follow-up before approving (item 7).

    ``None`` (the default for either field) keeps exactly what was drafted.
    """

    subject: str | None = None
    body: str | None = None
    delay_hours: float | None = None


async def _owner_followup_application_ids(engine: ApplicantEngineClient) -> "set[str] | None":
    """Application ids with an OPEN ``followup_draft`` pending action across
    the owner's OWN campaigns, or ``None`` when the campaign list itself could
    not be resolved (engine unreachable).

    Self-contained here (not reaching into ``applicant_tracker_routes.py``,
    which a sibling change owns this round) but mirrors its
    ``_owner_application_ids``'s never-trust-a-caller-supplied-id guard
    exactly: fan out over THIS request's own ``list_campaigns()``, read each
    campaign's ``attention`` feed (the SAME read ``GET /{campaign_id}`` above
    already proxies), and collect the ``followups_due`` application ids. A
    per-campaign read failure is skipped (logged, not fatal) so one
    inaccessible campaign never blanks the whole set.
    """
    try:
        campaigns = await engine.list_campaigns()
    except EngineError as exc:
        logger.debug("followups: campaigns read failed: %s", exc)
        return None
    if not isinstance(campaigns, list):
        return set()
    ids: set[str] = set()
    for c in campaigns:
        if not isinstance(c, dict) or not c.get("id"):
            continue
        cid = str(c["id"])
        try:
            data = await engine.post_submission_attention(cid)
        except EngineError as exc:
            logger.debug("followups: attention read failed for %s: %s", cid, exc)
            continue
        due = data.get("followups_due") if isinstance(data, dict) else None
        for row in due or []:
            if isinstance(row, dict) and row.get("application_id"):
                ids.add(str(row["application_id"]))
    return ids


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

    @router.post("/applications/{application_id}/approve", status_code=201)
    async def approve_follow_up(
        request: Request, application_id: str, body: ApproveFollowUpIn | None = None
    ) -> dict:
        """Approve + schedule a drafted follow-up for ONE OF THE OWNER'S OWN
        applications (dark-engine audit B2 item 7).

        ``application_id`` is validated against this request's own
        ``_owner_followup_application_ids`` fan-out BEFORE the write is
        forwarded — the same never-trust-a-caller-supplied-id guard
        ``applicant_tracker_routes.py``'s writes use. The engine independently
        re-checks there is still an OPEN ``followup_draft`` for the
        application (404 otherwise, e.g. already approved by a second tap) --
        this route only decides WHOSE application it is. Approving optionally
        edits the subject/body and schedules it onto the engine's send queue;
        the engine (``Scheduler._run_follow_up_send`` ->
        ``PostSubmissionService.send_scheduled_follow_ups``) actually sends it
        once its delay has elapsed — never in this same request.
        """
        _require_user(request)
        b = body or ApproveFollowUpIn()
        async with ApplicantEngineClient() as engine:
            owned = await _owner_followup_application_ids(engine)
            if owned is None:
                raise HTTPException(
                    status_code=503, detail="The Applicant engine is not reachable right now."
                )
            if application_id not in owned:
                raise HTTPException(
                    status_code=404, detail="No open follow-up draft for that application."
                )
            try:
                result = await engine.follow_up_approve(
                    application_id,
                    subject=b.subject,
                    body=b.body,
                    delay_hours=b.delay_hours,
                )
            except EngineError as exc:
                logger.info("followups: approve failed for %s: %s", application_id, exc)
                raise HTTPException(status_code=exc.status or 502, detail=str(exc)) from exc
        return result if isinstance(result, dict) else {}

    return router
