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

Cross-account isolation, write endpoints (DISC-15b): the id-ownership fan-out
above is only IDOR protection against foreign ids -- since the fan-out itself
has no owner concept to filter on, it was trivially satisfied for ANY
authenticated workspace account, so a second account could still resolve and
mutate the real owner's applications. Every mutator (``outcome``, ``archive``,
``mark-submitted``, ``detect-submission``, ``scan-email``, ``retry``,
``override-block``) is now additionally gated by ``_require_owner`` (the
shared ``require_engine_owner``), the same gate the read endpoints already use.

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
* ``GET  /api/applicant/tracker/applications/{application_id}/history`` — the
  per-application drill-down detail (status, work mode, screenshot count, the
  outcome timeline) for one of the owner's own applications. This is the SAME
  read the admin-only Debug modal's drill-down already surfaces (``GET
  /api/admin/history/{campaign_id}``, dark-engine audit #25) — reached here
  through an owner-scoped route instead of an admin gate, backing the
  Tracker's own "View details" disclosure. Derives the campaign id from THIS
  request's own tracker-board fan-out, same as ``interview_prep`` below.
* ``GET  /api/applicant/tracker/stuck`` — applications the engine loop has
  given up re-driving after repeated resume failures (dark-engine audit #62),
  aggregated across the owner's own campaigns, worst-first. A SEPARATE
  fan-out from the tracker board above: a stuck application is parked in a
  pre-submission working state (blocked / awaiting a step / in review), not a
  submitted one, so it would never appear in ``tracker_board``.
* ``POST /api/applicant/tracker/applications/{application_id}/retry`` —
  clear a given-up application's flag so the engine re-drives it on its next
  tick (previously the ONLY way to unstick one was a full engine process
  restart). ``application_id`` is validated against THIS request's own
  ``/stuck`` fan-out before the write is forwarded — the same
  never-trust-a-caller-supplied-id guard the outcome/scan-email writes use.
* ``POST /api/applicant/tracker/applications/{application_id}/archive`` —
  close out a dead application (dark-engine audit #13): the engine's
  ``PostSubmissionService.archive`` had zero callers before this proxy.
  Owner-scoped against the SAME ``_owner_application_ids`` tracker-board
  fan-out ``outcome``/``scan-email`` use.
* ``GET  /api/applicant/tracker/pending-confirmation`` — applications
  awaiting an owner "did this actually get submitted?" tap (dark-engine
  audit #14): the engine's one-tap mark-submitted/detect endpoints existed
  but were reachable only behind an admin gate. A SEPARATE fan-out from the
  tracker board (these applications haven't reached a tracker-board §7
  state yet — they're parked at the final-approval gate or an emergency
  hand-off).
* ``POST /api/applicant/tracker/applications/{application_id}/mark-submitted``
  / ``.../detect-submission`` — the owner-scoped lane for the engine's
  one-tap "mark submitted" / "try auto-detect" pair, validated against THIS
  request's own ``/pending-confirmation`` fan-out before the write is
  forwarded.
* ``GET  /api/applicant/tracker/applications/{application_id}/resume-status``
  — countdown to the engine's next resume attempt for a blocked (pre-submission)
  application (dark-engine audit #78): a plain, side-effect-free read, so unlike
  the writes above it is not gated behind a fan-out (mirrors the documents
  proxy's ``jd_match``).
* ``GET  /api/applicant/tracker/blocked`` — applications the engine's pre-submit
  safety gate has stopped on (dark-engine audit #61: scam/ghost-job, duplicate
  cooldown, per-company volume cap, eligibility/work-authorization), aggregated
  across the owner's own campaigns, most-recently-blocked first. A SEPARATE
  fan-out from the tracker board and ``/stuck`` above: a blocked application is
  still sitting APPROVED (never even started the pipeline), so it appears in
  neither.
* ``POST /api/applicant/tracker/applications/{application_id}/override-block``
  — let the owner proceed with one blocked application anyway, after reading
  why it was stopped (#61's "Proceed anyway"). ``application_id`` is validated
  against THIS request's own ``/blocked`` fan-out before the write is
  forwarded — the same never-trust-a-caller-supplied-id guard the other writes
  use. Never bypasses review-before-submit: the engine still requires the
  normal redline approval before any final submission.
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from src.applicant_engine import ApplicantEngineClient, EngineError, soft_degrade
from src.auth_helpers import require_engine_owner

logger = logging.getLogger(__name__)


# --- helpers ----------------------------------------------------------------


def _require_owner(request: Request) -> str:
    """Require the engine-owner account (DISC-15 / DISC-15b) for every
    endpoint below, both read and write.

    The engine has no owner concept at all (single-tenant per deployment), so
    the tracker board / stuck / blocked / pending-confirmation reads and their
    per-application drill-downs must be gated by
    ``src.auth_helpers.require_engine_owner`` rather than the plain
    auth-only ``require_user`` — otherwise any other authenticated workspace
    account (not just the real deployment owner) could read the owner's
    application-tracking data. Mirrors the fix already applied to the
    notification inbox / pending-actions feed in
    ``applicant_portal_routes.py``.

    The 7 mutators (``outcome``, ``archive``, ``mark-submitted``,
    ``detect-submission``, ``scan-email``, ``retry``, ``override-block``) use
    this SAME gate (DISC-15b): their own ``application_id`` fan-out check is
    only IDOR protection against foreign ids and, on a single-tenant engine,
    was trivially satisfied for ANY authenticated account -- this gate is the
    one that actually keeps a second workspace account from mutating the real
    owner's applications.
    """
    return require_engine_owner(request)


def _campaign_label(campaign: dict) -> str:
    """Best human label for a campaign dict from the engine."""
    return str(campaign.get("name") or campaign.get("id") or "")


class RecordOutcomeIn(BaseModel):
    outcome_type: str
    #: Optional free-text reason (dark-engine audit item 11) -- meaningful for
    #: outcome_type == "rejected"; forwarded to the engine's RejectionSignal
    #: audit trail alongside the real status transition.
    reason: Optional[str] = None


class ScanEmailIn(BaseModel):
    subject: str = ""
    body: str = ""


class MarkSubmittedIn(BaseModel):
    attributes_used: Optional[dict] = None


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


async def _owner_stuck_rows(engine: ApplicantEngineClient) -> "list[dict] | dict":
    """Every given-up application across the owner's OWN campaigns (#62), or a
    :func:`soft_degrade` dict.

    Mirrors ``_owner_tracker_rows`` exactly (fan out over this request's own
    ``list_campaigns()``, never a caller-supplied campaign id) but hits the
    engine's stuck-applications read instead of the tracker board, since a
    given-up application is still mid-pipeline and would never show up on the
    (submitted-only) tracker board. A per-campaign read failure is skipped
    (logged, not fatal) so one inaccessible campaign never blanks the panel.
    """
    try:
        campaigns = await engine.list_campaigns()
    except EngineError as exc:
        logger.debug("tracker: stuck campaigns read failed (status=%s): %s", exc.status, exc)
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
            payload = await engine.admin_stuck_applications(str(cid))
        except EngineError as exc:
            logger.debug("tracker: stuck read failed for %s: %s", cid, exc)
            continue
        items = payload.get("applications") if isinstance(payload, dict) else None
        for row in items or []:
            if not isinstance(row, dict):
                continue
            r = dict(row)
            r.setdefault("campaign_id", str(cid))
            r["campaign_name"] = _campaign_label(campaign)
            rows.append(r)
    return rows


async def _owner_stuck_application_ids(engine: ApplicantEngineClient) -> Optional[set]:
    """The set of given-up application ids that belong to THIS owner, or
    ``None`` when the campaign list itself could not be resolved."""
    rows = await _owner_stuck_rows(engine)
    if not isinstance(rows, list):
        return None
    return {str(r["application_id"]) for r in rows if r.get("application_id")}


async def _owner_blocked_rows(engine: ApplicantEngineClient) -> "list[dict] | dict":
    """Every pre-submit-safety-blocked application across the owner's OWN
    campaigns (#61), or a :func:`soft_degrade` dict.

    Mirrors ``_owner_stuck_rows`` exactly (fan out over this request's own
    ``list_campaigns()``, never a caller-supplied campaign id) but hits the
    engine's blocked-applications read instead, since a blocked application is
    still sitting APPROVED (never started the pipeline) and would never show up
    on the tracker board OR the stuck list. A per-campaign read failure is
    skipped (logged, not fatal) so one inaccessible campaign never blanks the
    panel.
    """
    try:
        campaigns = await engine.list_campaigns()
    except EngineError as exc:
        logger.debug("tracker: blocked campaigns read failed (status=%s): %s", exc.status, exc)
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
            payload = await engine.admin_blocked_applications(str(cid))
        except EngineError as exc:
            logger.debug("tracker: blocked read failed for %s: %s", cid, exc)
            continue
        items = payload.get("applications") if isinstance(payload, dict) else None
        for row in items or []:
            if not isinstance(row, dict):
                continue
            r = dict(row)
            r.setdefault("campaign_id", str(cid))
            r["campaign_name"] = _campaign_label(campaign)
            rows.append(r)
    return rows


async def _owner_blocked_application_ids(engine: ApplicantEngineClient) -> Optional[set]:
    """The set of blocked application ids that belong to THIS owner, or
    ``None`` when the campaign list itself could not be resolved."""
    rows = await _owner_blocked_rows(engine)
    if not isinstance(rows, list):
        return None
    return {str(r["application_id"]) for r in rows if r.get("application_id")}


#: §7 states an application sits in when it is waiting on the owner to
#: confirm what actually happened -- awaiting the live-session final-approval
#: decision, or parked at the emergency copy/paste hand-off (dark-engine audit
#: item 14). These are intentionally NOT in the tracker board's own
#: TRACKER_STATES (nothing has been submitted yet from the engine's point of
#: view), so they need their own small fan-out, reusing the SAME
#: ``tracker_application_history`` read the "View details" drill-down already
#: calls (it returns every application in a campaign, not just tracker rows).
_PENDING_CONFIRMATION_STATUSES = frozenset({"AWAITING_FINAL_APPROVAL", "EMERGENCY_DATA_HANDOFF"})


async def _owner_pending_confirmation_rows(engine: ApplicantEngineClient) -> "list[dict] | dict":
    """Applications awaiting an owner "did this actually get submitted?" tap,
    aggregated across the owner's OWN campaigns, or a :func:`soft_degrade`
    dict.

    Mirrors ``_owner_tracker_rows`` (fan out over THIS request's own
    ``list_campaigns()``, never a caller-supplied id) but reads the engine's
    per-application history (the same read ``application_history`` already
    proxies for "View details") and narrows to the two states where
    auto-detection may not have caught a manual/hand-off submission -- the
    one-tap "mark as submitted" / "try auto-detect" affordances only ever
    apply here.
    """
    try:
        campaigns = await engine.list_campaigns()
    except EngineError as exc:
        logger.debug("tracker: pending-confirmation campaigns read failed (status=%s): %s", exc.status, exc)
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
            history = await engine.tracker_application_history(str(cid))
        except EngineError as exc:
            logger.debug("tracker: pending-confirmation history read failed for %s: %s", cid, exc)
            continue
        items = history.get("applications") if isinstance(history, dict) else None
        for row in items or []:
            if not isinstance(row, dict):
                continue
            if str(row.get("status") or "") not in _PENDING_CONFIRMATION_STATUSES:
                continue
            r = dict(row)
            r.setdefault("campaign_id", str(cid))
            r["campaign_name"] = _campaign_label(campaign)
            rows.append(r)
    return rows


async def _owner_pending_confirmation_application_ids(
    engine: ApplicantEngineClient,
) -> Optional[set]:
    """The set of pending-confirmation application ids that belong to THIS
    owner, or ``None`` when the campaign list itself could not be resolved."""
    rows = await _owner_pending_confirmation_rows(engine)
    if not isinstance(rows, list):
        return None
    return {str(r["application_id"]) for r in rows if r.get("application_id")}


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

        Owner-scoped (DISC-15): gated by ``_require_owner`` (the shared
        ``require_engine_owner``), not a plain auth-only check -- the
        engine's tracker board is single-tenant, so any other workspace
        account must not be able to read the real owner's board.
        """
        _require_owner(request)
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
        _require_owner(request)
        async with ApplicantEngineClient() as engine:
            owned = await _owner_application_ids(engine)
            if owned is None:
                raise HTTPException(status_code=503, detail="The engine is unavailable.")
            if application_id not in owned:
                raise HTTPException(status_code=404, detail="No such application.")
            try:
                result = await engine.tracker_record_outcome(
                    application_id, body.outcome_type, reason=body.reason
                )
            except EngineError as exc:
                logger.debug(
                    "tracker: record_outcome failed for %s: %s", application_id, exc
                )
                raise HTTPException(
                    status_code=exc.status or 502, detail=str(exc)
                ) from exc
        return result if isinstance(result, dict) else {}

    @router.post("/applications/{application_id}/archive")
    async def archive(request: Request, application_id: str) -> dict:
        """Close out a dead application on the owner's OWN tracker board
        (dark-engine audit item 13) -- ``PostSubmissionService.archive`` had
        zero callers before this proxy.

        ``application_id`` is validated against this request's own
        ``_owner_application_ids`` fan-out BEFORE the write is forwarded --
        the exact same owner-isolation guard ``record_outcome``/``scan_email``
        use above. The engine independently re-checks the §7 transition is
        legal (409 when it isn't, e.g. still sitting in the just-submitted
        "applied" bucket) -- this route only decides WHOSE application it is.
        """
        _require_owner(request)
        async with ApplicantEngineClient() as engine:
            owned = await _owner_application_ids(engine)
            if owned is None:
                raise HTTPException(status_code=503, detail="The engine is unavailable.")
            if application_id not in owned:
                raise HTTPException(status_code=404, detail="No such application.")
            try:
                result = await engine.tracker_archive_application(application_id)
            except EngineError as exc:
                logger.debug(
                    "tracker: archive failed for %s: %s", application_id, exc
                )
                raise HTTPException(
                    status_code=exc.status or 502, detail=str(exc)
                ) from exc
        return result if isinstance(result, dict) else {}

    @router.get("/pending-confirmation")
    async def pending_confirmation(request: Request) -> dict:
        """Applications awaiting an owner "did this get submitted?" tap
        (dark-engine audit item 14), aggregated across all of the owner's
        campaigns. Degrades soft exactly like the board above: an
        unreachable engine returns ``engine_available: false``; a setup gate
        returns ``gated: true``; nothing pending returns ``has_data: false``
        with an empty, well-formed ``applications`` list.

        Owner-scoped (DISC-15): same gate as ``tracker`` above.
        """
        _require_owner(request)
        async with ApplicantEngineClient() as engine:
            rows = await _owner_pending_confirmation_rows(engine)
            if not isinstance(rows, list):
                return {**rows, "applications": []}
        return {
            "engine_available": True,
            "has_data": bool(rows),
            "applications": rows,
        }

    @router.post("/applications/{application_id}/mark-submitted")
    async def mark_submitted(
        request: Request, application_id: str, body: MarkSubmittedIn | None = None
    ) -> dict:
        """One-tap "I submitted this myself" for one of the owner's OWN
        applications, when auto-detection couldn't confirm it (dark-engine
        audit item 14) -- the engine's ``mark-submitted`` one-tap path
        existed but was reachable only behind an admin gate
        (``applicant_admin_routes.py``); this is the owner-scoped lane.

        ``application_id`` is validated against this request's own
        ``_owner_pending_confirmation_application_ids`` fan-out BEFORE the
        write is forwarded -- never trust a caller-supplied id.
        """
        _require_owner(request)
        async with ApplicantEngineClient() as engine:
            owned = await _owner_pending_confirmation_application_ids(engine)
            if owned is None:
                raise HTTPException(status_code=503, detail="The engine is unavailable.")
            if application_id not in owned:
                raise HTTPException(status_code=404, detail="No such application.")
            payload = {"attributes_used": body.attributes_used} if body else {}
            try:
                result = await engine.outcome_mark_submitted(application_id, payload)
            except EngineError as exc:
                logger.debug(
                    "tracker: mark_submitted failed for %s: %s", application_id, exc
                )
                raise HTTPException(
                    status_code=exc.status or 502, detail=str(exc)
                ) from exc
        return result if isinstance(result, dict) else {}

    @router.post("/applications/{application_id}/detect-submission")
    async def detect_submission(request: Request, application_id: str) -> dict:
        """Ask the engine to auto-detect a final submission in the live
        session for one of the owner's OWN applications (dark-engine audit
        item 14) -- the sibling of ``mark_submitted`` above for when the
        owner isn't sure and wants the engine to check the confirmation page
        itself first.

        ``application_id`` is validated against this request's own
        ``_owner_pending_confirmation_application_ids`` fan-out BEFORE the
        request is forwarded -- never trust a caller-supplied id.
        """
        _require_owner(request)
        async with ApplicantEngineClient() as engine:
            owned = await _owner_pending_confirmation_application_ids(engine)
            if owned is None:
                raise HTTPException(status_code=503, detail="The engine is unavailable.")
            if application_id not in owned:
                raise HTTPException(status_code=404, detail="No such application.")
            try:
                result = await engine.outcome_detect(application_id)
            except EngineError as exc:
                logger.debug(
                    "tracker: detect_submission failed for %s: %s", application_id, exc
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
        _require_owner(request)
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

    @router.get("/applications/{application_id}/interview-prep")
    async def interview_prep(request: Request, application_id: str) -> dict:
        """A plain-language interview-prep brief for ONE OF THE OWNER'S OWN
        applications (product-gaps backlog #30; engine ``GET /api/documents/
        interview-prep/{campaign_id}/{application_id}``).

        ``application_id`` is validated against this request's own tracker-board
        fan-out BEFORE the read is forwarded -- the exact same owner-isolation
        guard ``record_outcome``/``scan_email`` use above (never trust a
        caller-supplied id). The engine independently enforces the
        ``interview_invited`` gate itself from its own outcome trail (never a
        caller-supplied flag) -- this route only decides WHOSE application it is,
        the SAME company-research-backed brief either way.

        Owner-scoped (DISC-15): additionally gated by ``_require_owner`` --
        this route derives its own tracker-board fan-out from THIS request's
        engine-owner identity, so it must not be reachable by any other
        workspace account either.
        """
        _require_owner(request)
        async with ApplicantEngineClient() as engine:
            rows = await _owner_tracker_rows(engine)
            if not isinstance(rows, list):
                return {**rows, "generated": False}
            row = next(
                (r for r in rows if str(r.get("application_id")) == application_id), None
            )
            if row is None:
                raise HTTPException(status_code=404, detail="No such application.")
            campaign_id = str(row.get("campaign_id") or "")
            try:
                data = await engine.interview_prep(campaign_id, application_id)
            except EngineError as exc:
                logger.debug(
                    "tracker: interview_prep failed for %s: %s", application_id, exc
                )
                raise HTTPException(
                    status_code=exc.status or 502, detail=str(exc)
                ) from exc
        return data if isinstance(data, dict) else {"generated": False}

    @router.get("/applications/{application_id}/history")
    async def application_history(request: Request, application_id: str) -> dict:
        """Per-application drill-down detail for ONE OF THE OWNER'S OWN
        applications (dark-engine audit #25): status, work mode, screenshot
        count, and the recorded outcome timeline. This is the SAME engine read
        the admin-only Debug modal's drill-down already surfaces
        (``GET /api/admin/history/{campaign_id}``) -- reached here through an
        owner-scoped route instead of an admin gate, for the Tracker's own
        "View details" disclosure.

        ``application_id`` is validated against this request's own tracker-board
        fan-out BEFORE the read is forwarded -- the exact same owner-isolation
        guard ``record_outcome``/``scan_email``/``interview_prep`` use above
        (never trust a caller-supplied id). The campaign id used for the engine
        call is this same fan-out's own row, never a caller-supplied one.

        Owner-scoped (DISC-15): additionally gated by ``_require_owner`` --
        same reasoning as ``interview_prep`` above.
        """
        _require_owner(request)
        async with ApplicantEngineClient() as engine:
            rows = await _owner_tracker_rows(engine)
            if not isinstance(rows, list):
                return {**rows, "found": False}
            row = next(
                (r for r in rows if str(r.get("application_id")) == application_id), None
            )
            if row is None:
                raise HTTPException(status_code=404, detail="No such application.")
            campaign_id = str(row.get("campaign_id") or "")
            try:
                data = await engine.tracker_application_history(campaign_id)
            except EngineError as exc:
                logger.debug(
                    "tracker: application_history failed for %s: %s", application_id, exc
                )
                raise HTTPException(
                    status_code=exc.status or 502, detail=str(exc)
                ) from exc
        applications = data.get("applications") if isinstance(data, dict) else None
        detail = next(
            (a for a in (applications or []) if str(a.get("application_id")) == application_id),
            None,
        )
        if detail is None:
            raise HTTPException(
                status_code=404, detail="No history found for that application."
            )
        return {"found": True, **detail}

    @router.get("/stuck")
    async def stuck(request: Request) -> dict:
        """Applications the engine has paused after repeated failed resume
        attempts (dark-engine audit #62), aggregated across all of the owner's
        campaigns, worst failure-count first. Degrades soft exactly like the
        board above: an unreachable engine returns ``engine_available: false``;
        a setup gate returns ``gated: true``; no stuck applications returns
        ``has_data: false`` with an empty, well-formed ``applications`` list.

        Owner-scoped (DISC-15): same gate as ``tracker`` above.
        """
        _require_owner(request)
        async with ApplicantEngineClient() as engine:
            rows = await _owner_stuck_rows(engine)
            if not isinstance(rows, list):
                return {**rows, "applications": []}
        rows.sort(key=lambda r: r.get("failures") or 0, reverse=True)
        return {
            "engine_available": True,
            "has_data": bool(rows),
            "applications": rows,
        }

    @router.post("/applications/{application_id}/retry")
    async def retry_stuck(request: Request, application_id: str) -> dict:
        """Clear a given-up application's flag so the engine re-drives it on
        its very next tick (#62's "Retry now").

        ``application_id`` is validated against this request's own
        ``_owner_stuck_application_ids`` fan-out BEFORE the write is forwarded
        -- the same never-trust-a-caller-supplied-id guard ``record_outcome``/
        ``scan_email`` use above. A caller cannot retry an application that
        never appeared in their own stuck-applications panel.
        """
        _require_owner(request)
        async with ApplicantEngineClient() as engine:
            owned = await _owner_stuck_application_ids(engine)
            if owned is None:
                raise HTTPException(status_code=503, detail="The engine is unavailable.")
            if application_id not in owned:
                raise HTTPException(status_code=404, detail="No such application.")
            try:
                result = await engine.admin_retry_stuck_application(application_id)
            except EngineError as exc:
                logger.debug(
                    "tracker: retry_stuck failed for %s: %s", application_id, exc
                )
                raise HTTPException(
                    status_code=exc.status or 502, detail=str(exc)
                ) from exc
        return result if isinstance(result, dict) else {}

    @router.get("/applications/{application_id}/resume-status")
    async def resume_status(request: Request, application_id: str) -> dict:
        """Countdown to the engine's next resume attempt for one blocked
        application (dark-engine audit #78; engine ``GET
        /api/admin/resume-status/{id}``).

        A blocked (pre-submission) application is re-driven at most every ~300s
        via the engine's resume backoff, so right after the owner clears a
        blocker (answers a question, supplies a missing detail, approves a
        redline) this tells them honestly WHEN the engine will actually pick it
        back up, instead of the up-to-5-minute silence the fixed backoff
        otherwise leaves. A plain read with no side effects -- same auth tier as
        ``applicant_documents_routes.jd_match``/``application_documents`` (the
        engine has no owner concept of its own, single-tenant per deployment, so
        a by-id read for the owner's OWN materials/status is not gated behind an
        extra fan-out); the Portal calls this right after resolving a blocker to
        phrase its confirmation honestly. Degrades to ``{"status":
        "not_blocked"}`` on an engine error rather than blocking the toast.

        Owner-scoped (DISC-15): still gated by ``_require_owner`` (the
        workspace-account gate, orthogonal to the application-id fan-out
        question above) -- any other workspace account must not be able to
        read the deployment owner's resume-backoff countdown either.
        """
        _require_owner(request)
        try:
            async with ApplicantEngineClient() as engine:
                result = await engine.admin_resume_status(application_id)
        except EngineError as exc:
            logger.debug("tracker: resume_status failed for %s: %s", application_id, exc)
            return {"application_id": application_id, "status": "not_blocked"}
        return result if isinstance(result, dict) else {"application_id": application_id, "status": "not_blocked"}

    @router.get("/blocked")
    async def blocked(request: Request) -> dict:
        """Applications the engine's pre-submit safety gate has stopped on
        (dark-engine audit #61: scam/ghost-job, duplicate cooldown, per-company
        volume cap, eligibility/work-authorization), aggregated across all of
        the owner's campaigns, most-recently-blocked first. Degrades soft
        exactly like ``/stuck`` above: an unreachable engine returns
        ``engine_available: false``; a setup gate returns ``gated: true``; no
        blocked applications returns ``has_data: false`` with an empty,
        well-formed ``applications`` list.

        Owner-scoped (DISC-15): same gate as ``tracker``/``stuck`` above.
        """
        _require_owner(request)
        async with ApplicantEngineClient() as engine:
            rows = await _owner_blocked_rows(engine)
            if not isinstance(rows, list):
                return {**rows, "applications": []}
        rows.sort(key=lambda r: r.get("last_blocked_at") or "", reverse=True)
        return {
            "engine_available": True,
            "has_data": bool(rows),
            "applications": rows,
        }

    @router.post("/applications/{application_id}/override-block")
    async def override_block(request: Request, application_id: str) -> dict:
        """Proceed with one blocked application anyway, on the owner's own
        decision after reading why it was stopped (#61's "Proceed anyway").

        ``application_id`` is validated against this request's own
        ``_owner_blocked_application_ids`` fan-out BEFORE the write is
        forwarded -- the same never-trust-a-caller-supplied-id guard
        ``retry_stuck``/``record_outcome`` use above. A caller cannot override
        an application that never appeared in their own blocked-applications
        panel. This never bypasses review-before-submit: it only lets the
        engine start prefill/materials generation on its next tick, the same
        redline approval still gates the actual final submission.
        """
        _require_owner(request)
        async with ApplicantEngineClient() as engine:
            owned = await _owner_blocked_application_ids(engine)
            if owned is None:
                raise HTTPException(status_code=503, detail="The engine is unavailable.")
            if application_id not in owned:
                raise HTTPException(status_code=404, detail="No such blocked application.")
            try:
                result = await engine.admin_override_blocked_application(application_id)
            except EngineError as exc:
                logger.debug(
                    "tracker: override_block failed for %s: %s", application_id, exc
                )
                raise HTTPException(
                    status_code=exc.status or 502, detail=str(exc)
                ) from exc
        return result if isinstance(result, dict) else {}

    return router
