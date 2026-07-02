# routes/applicant_tracker_routes.py
"""Post-submission tracker ↔ engine bridge (design-audit Top-25 #4).

``PostSubmissionService`` already runs the full post-submission lifecycle end to
end as a real, tested state machine (``submitted -> awaiting-response -> rejected
/ ghosted / following-up -> archived``, per-application) — automated
rejection-signal detection, the ghosting-SLA sweep, and follow-up scheduling all
already work. It had ZERO router/front-door callers: nothing let an owner see
where their applications stand, or tell the assistant what actually happened
(an interview invite, an offer, a rejection the automated detectors never
caught). This proxy SURFACES the new engine router
(``/api/post-submission/*``) as the front-door "Tracker" board — a thin,
auth-protected, owner-scoped proxy over
:class:`src.applicant_engine.ApplicantEngineClient`. It adds no engine logic; the
engine owns the state machine and the outcome catalogue.

Owner-scoping mirrors the sibling proxies:

* the READ (the board) is NOT gated behind one active campaign — like
  ``applicant_results_routes.py`` / ``applicant_activity_routes.py``, it fans out
  over the owner's OWN ``list_campaigns()`` result and aggregates every
  campaign's tracker rows (a job search can span more than one active campaign,
  unlike Results/Activity's "first campaign wins" — there's no reason to hide a
  second campaign's applications from the owner's own tracker);
* the WRITE (manually recording what happened) additionally validates that the
  caller-supplied ``application_id`` actually belongs to one of the rows THIS
  request's own campaign fan-out just returned (mirrors
  ``applicant_campaigns_routes._owner_campaign_ids`` / CLAUDE.md: "the fabrication
  guard derives its own ground truth" — never trust a caller-supplied id to opt a
  safety check in). A caller cannot record an outcome against another owner's
  application; the engine itself has no owner concept (single-tenant per
  deployment), so this check is the ONLY scoping boundary and it is enforced here,
  server-side, not merely by omitting a picker from the UI.

Every engine failure degrades soft: an unreachable engine returns
``engine_available: false`` with a well-formed empty body; a setup gate returns
``gated: true`` with the engine's own message; no campaign / no applications yet
returns ``has_data: false``.

Endpoints (all under ``/api/applicant/tracker``):

* ``GET  /api/applicant/tracker`` — the owner's tracker-board rows, aggregated
  across every one of their campaigns, newest-submitted first.
* ``POST /api/applicant/tracker/applications/{application_id}/outcome`` — record
  what happened (interview / offer / rejected / ghosted / ...).
* ``POST /api/applicant/tracker/applications/{application_id}/scan-email`` —
  the SAFE version of "close the loop": the owner pastes one email's
  subject/body against a specific application THEY chose (never an
  automatic inbox-to-application match, which risks recording an outcome
  against the wrong application — see ``post_submission.py``'s
  ``scan_email``); the engine's detectors classify it and record whatever
  confidently matched. Owner-scoped with the EXACT same
  ``_owner_application_ids`` guard as the outcome write below.
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from src.applicant_engine import ApplicantEngineClient, EngineError, soft_degrade
from src.auth_helpers import require_user

logger = logging.getLogger(__name__)


# --- helpers ----------------------------------------------------------------


def _require_user(request: Request) -> str:
    """Require an authenticated owner (the global gate also enforces this)."""
    return require_user(request)


def _campaign_label(campaign: dict) -> str:
    """Best human label for a campaign dict from the engine."""
    return str(campaign.get("name") or campaign.get("id") or "")


class RecordOutcomeIn(BaseModel):
    outcome_type: str


class ScanEmailIn(BaseModel):
    subject: str = ""
    body: str = ""


async def _owner_tracker_rows(engine: ApplicantEngineClient) -> "list[dict] | dict":
    """Every tracker row across the owner's OWN campaigns, or a soft-degrade dict.

    Fans out ``tracker_board(campaign_id)`` over ``list_campaigns()`` — this
    request's own campaign list, never a caller-supplied id — and tags each row
    with the campaign it came from. On success returns a ``list`` (possibly
    empty). On an :class:`EngineError` resolving the campaign list itself,
    returns the :func:`soft_degrade` dict; callers detect the failure with
    ``isinstance(result, list)``. A per-campaign board fetch failure is skipped
    (logged, not fatal) so one inaccessible campaign never blanks the whole
    board — mirrors ``applicant_campaigns_routes.toggle_source``'s per-call
    degrade.
    """
    try:
        campaigns = await engine.list_campaigns()
    except EngineError as exc:
        logger.debug("tracker: campaigns read failed (status=%s): %s", exc.status, exc)
        return soft_degrade(exc, {"has_data": False})
    if not isinstance(campaigns, list):
        return []
    rows: list[dict] = []
    for campaign in campaigns:
        if not isinstance(campaign, dict):
            continue
        cid = campaign.get("id")
        if not cid:
            continue
        try:
            board = await engine.tracker_board(str(cid))
        except EngineError as exc:
            logger.debug("tracker: board read failed for %s: %s", cid, exc)
            continue
        items = board.get("applications") if isinstance(board, dict) else None
        for row in items or []:
            if not isinstance(row, dict):
                continue
            r = dict(row)
            r.setdefault("campaign_id", str(cid))
            r["campaign_name"] = _campaign_label(campaign)
            rows.append(r)
    return rows


async def _owner_application_ids(engine: ApplicantEngineClient) -> Optional[set]:
    """The set of application ids that actually belong to THIS owner, or ``None``
    when the campaign list itself could not be resolved (engine unreachable)."""
    rows = await _owner_tracker_rows(engine)
    if not isinstance(rows, list):
        return None
    return {str(r["application_id"]) for r in rows if r.get("application_id")}


def _sort_key(row: dict) -> str:
    return str(row.get("submitted_at") or row.get("created_at") or "")


def setup_applicant_tracker_routes() -> APIRouter:
    router = APIRouter(prefix="/api/applicant/tracker", tags=["applicant-tracker"])

    @router.get("")
    async def tracker(request: Request) -> dict:
        """The owner's tracker board: every application in (or past) the
        terminal-submit states, aggregated across all of their campaigns,
        newest-submitted first. Degrades soft: an unreachable engine returns
        ``engine_available: false``; a setup gate returns ``gated: true``; no
        campaign or no rows yet returns ``has_data: false`` with an empty,
        well-formed ``applications`` list.
        """
        _require_user(request)
        async with ApplicantEngineClient() as engine:
            rows = await _owner_tracker_rows(engine)
            if not isinstance(rows, list):
                return {**rows, "applications": []}
        rows.sort(key=_sort_key, reverse=True)
        return {
            "engine_available": True,
            "has_data": bool(rows),
            "applications": rows,
        }

    @router.post("/applications/{application_id}/outcome", status_code=201)
    async def record_outcome(
        request: Request, application_id: str, body: RecordOutcomeIn
    ) -> dict:
        """Manually record an outcome the owner reports for one of THEIR OWN
        applications (interview invite / offer / rejected / ghosted / ...).

        ``application_id`` is validated against this request's own
        ``_owner_application_ids`` fan-out BEFORE the write is forwarded — a
        caller cannot record an outcome against an application that never
        appeared in their own tracker board.
        """
        _require_user(request)
        async with ApplicantEngineClient() as engine:
            owned = await _owner_application_ids(engine)
            if owned is None:
                raise HTTPException(status_code=503, detail="The engine is unavailable.")
            if application_id not in owned:
                raise HTTPException(status_code=404, detail="No such application.")
            try:
                result = await engine.tracker_record_outcome(
                    application_id, body.outcome_type
                )
            except EngineError as exc:
                logger.debug(
                    "tracker: record_outcome failed for %s: %s", application_id, exc
                )
                raise HTTPException(
                    status_code=exc.status or 502, detail=str(exc)
                ) from exc
        return result if isinstance(result, dict) else {}

    @router.post("/applications/{application_id}/scan-email")
    async def scan_email(
        request: Request, application_id: str, body: ScanEmailIn
    ) -> dict:
        """Scan one owner-pasted email against a SPECIFIC application the owner
        themselves picked (this row's "Check an email" affordance) -- the safe
        version of closing the loop: zero ambiguity about which application the
        email applies to, since the owner is the one who chose it.

        ``application_id`` is validated against this request's own
        ``_owner_application_ids`` fan-out BEFORE the scan is forwarded -- the
        exact same owner-isolation guard ``record_outcome`` uses above. A
        caller cannot scan an email against an application that never appeared
        in their own tracker board.
        """
        _require_user(request)
        async with ApplicantEngineClient() as engine:
            owned = await _owner_application_ids(engine)
            if owned is None:
                raise HTTPException(status_code=503, detail="The engine is unavailable.")
            if application_id not in owned:
                raise HTTPException(status_code=404, detail="No such application.")
            try:
                result = await engine.tracker_scan_email(
                    application_id, body.subject, body.body
                )
            except EngineError as exc:
                logger.debug(
                    "tracker: scan_email failed for %s: %s", application_id, exc
                )
                raise HTTPException(
                    status_code=exc.status or 502, detail=str(exc)
                ) from exc
        return result if isinstance(result, dict) else {}

    return router
