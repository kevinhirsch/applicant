"""Post-submission tracker router (G16/#190; design-audit Top-25 #4).

``PostSubmissionService`` already runs the full post-submission lifecycle end to
end -- automated rejection-signal detection (``process_rejection_signal`` /
``scan_email_for_rejection``), the ghosting-SLA sweep (``check_ghosting``), and
follow-up scheduling all already work as a real, tested state machine
(``submitted -> awaiting-response -> rejected / ghosted / following-up ->
archived``, per-application). What was genuinely missing was a router: nothing
let the front-door read the board or let the owner record what actually
happened (an interview invite, an offer, a rejection the automated detectors
never caught, or simple silence). This router is that surface -- a read-only
tracker-board query per campaign, plus one owner-triggered write.

``/applications/{id}/scan-email`` (design-audit Top-25 #5) is the newer
addition: it finally gives the long-dead ``scan_email_for_rejection`` (and its
new siblings, ``scan_email_for_interview``/``scan_email_for_offer``) a real
caller. Automatic inbox-to-application matching stays out of scope here (a
mis-attributed email could record a fake outcome against the wrong
application) -- this endpoint just makes the detection capability reachable
for a human, a test, or a future bridge to call with subject/body already
resolved to the right application.

Gated behind the LLM-settings gate (FR-UI-5), like every other driving-port
router (see ``admin.py`` / ``campaigns.py`` / ``outcomes.py``).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from applicant.app.deps import (
    get_pending_actions_service,
    get_post_submission_service,
    get_storage,
    require_llm_configured,
)
from applicant.application.services.post_submission_service import (
    KIND_FOLLOWUP_DRAFT,
    KIND_GHOSTING_FLAG,
)
from applicant.core.entities.outcome_event import OUTCOME_TYPES
from applicant.core.entities.rejection_signal import RejectionSource
from applicant.core.ids import ApplicationId, CampaignId

router = APIRouter(
    prefix="/api/post-submission",
    tags=["post-submission"],
    dependencies=[Depends(require_llm_configured)],
)


class RecordOutcomeIn(BaseModel):
    outcome_type: str
    #: Optional free-text ("they said the role was on hold") -- dark-engine
    #: audit item 11: the owner's strongest negative signal deserves more than
    #: just a type. Only meaningful when ``outcome_type == "rejected"``;
    #: persisted as a ``RejectionSignal`` audit-trail row via the EXISTING
    #: ``process_rejection_signal`` (previously unwired to any router) so the
    #: real state transition still runs through ``record_manual_outcome``
    #: exactly as before -- this never invents a second transition path.
    reason: str | None = None


class ScanEmailIn(BaseModel):
    subject: str = ""
    body: str = ""


@router.get("")
def index() -> dict:
    return {"surface": "post-submission", "status": "live"}


@router.get("/{campaign_id}")
def tracker_board(
    campaign_id: str, svc=Depends(get_post_submission_service)
) -> dict:
    """The tracker-board rows for one campaign, newest first.

    Each row is one application in (or past) the terminal-submit states:
    ``status`` for its bucket (applied / awaiting response / following up /
    rejected / ghosted / archived) plus any recorded positive ``signals``
    (interview invite / offer) layered on top, since those have no dedicated
    §7 state of their own (see ``PostSubmissionService.list_tracker_rows``).
    """
    rows = svc.list_tracker_rows(CampaignId(campaign_id))
    return {"campaign_id": campaign_id, "applications": rows}


@router.get("/{campaign_id}/attention")
def attention(
    campaign_id: str, pending=Depends(get_pending_actions_service)
) -> dict:
    """Ghosted applications + drafted (never auto-sent) follow-ups awaiting the
    owner's review, for one campaign (dark-engine audit B2 items 8/9/60).

    Reads straight off the SAME pending-actions substrate the Portal already
    renders generically (CLAUDE.md principle #3) -- ``ghosting_flag`` rows come
    from the scheduler's daily ``check_ghosting`` sweep, ``followup_draft`` rows
    from its follow-up-drafting pass (``PostSubmissionService.
    run_post_submission_sweep``, driven by ``Scheduler._run_post_submission_
    sweep``). A pure read: resolving/acting on an item still goes through the
    existing pending-actions resolve path (the Portal), not this endpoint.
    """
    rows = pending.list_pending(CampaignId(campaign_id))

    def _row(a) -> dict:
        return {
            "id": str(a.id),
            "application_id": str(a.application_id) if a.application_id else None,
            "title": a.title,
            "payload": dict(a.payload or {}),
            "created_at": a.created_at.isoformat() if a.created_at else None,
        }

    return {
        "campaign_id": campaign_id,
        "ghosted": [_row(a) for a in rows if a.kind == KIND_GHOSTING_FLAG],
        "followups_due": [_row(a) for a in rows if a.kind == KIND_FOLLOWUP_DRAFT],
    }


@router.post("/applications/{application_id}/outcome", status_code=201)
def record_outcome(
    application_id: str,
    body: RecordOutcomeIn,
    svc=Depends(get_post_submission_service),
) -> dict:
    """Manually record an outcome the owner reports -- the tracker board's
    "record what happened" affordance, and the owner-triggered sibling of the
    automated detection paths (``detect_outcome`` / ``process_rejection_signal``
    / ``check_ghosting``, which only ever record ``OutcomeSource.AUTO``).
    """
    outcome_type = (body.outcome_type or "").strip()
    if outcome_type not in OUTCOME_TYPES:
        raise HTTPException(
            status_code=422, detail=f"Unrecognized outcome type: {outcome_type!r}"
        )
    try:
        event = svc.record_manual_outcome(ApplicationId(application_id), outcome_type)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if event is None:
        raise HTTPException(status_code=404, detail="No such application.")
    reason = (body.reason or "").strip()
    if outcome_type == "rejected" and reason:
        # Layer the free-text reason on as a RejectionSignal audit-trail row
        # (dark-engine audit item 11). confidence is kept BELOW the
        # auto-record threshold (0.8) so this call never re-triggers
        # ``detect_outcome`` -- ``record_manual_outcome`` above already
        # performed the one real REJECTED transition + the one clean
        # OutcomeEvent; this is purely an audit note, never a second
        # transition attempt. Best-effort: the reason is a nice-to-have,
        # never allowed to break the outcome that was just recorded.
        try:
            svc.process_rejection_signal(
                ApplicationId(application_id),
                source=RejectionSource.MANUAL,
                signal_text=reason,
                confidence=0.0,
            )
        except Exception:
            pass
    return {
        "application_id": application_id,
        "outcome_id": str(event.id),
        "type": event.type,
        "source": event.source.value,
    }


@router.post("/applications/{application_id}/archive", status_code=200)
def archive_application(
    application_id: str,
    storage=Depends(get_storage),
    svc=Depends(get_post_submission_service),
) -> dict:
    """Close out a dead application (dark-engine audit item 13).

    ``PostSubmissionService.archive`` already existed with zero callers --
    this is the smallest possible router addition to reach it: one owner
    action, no new state-machine behavior. §7 only allows ARCHIVED from
    AWAITING_RESPONSE/FOLLOWING_UP/REJECTED/GHOSTED (never straight from the
    just-submitted "applied" bucket) -- checked here BEFORE the write so a
    stale UI click gets an honest 409, not a misleading 404 (``svc.archive``
    itself swallows an illegal transition and returns ``None`` for both
    "not found" and "not archivable yet").
    """
    from applicant.core.state_machine import ApplicationState, can_transition

    app = storage.applications.get(ApplicationId(application_id))
    if app is None:
        raise HTTPException(status_code=404, detail="No such application.")
    if not can_transition(app.status, ApplicationState.ARCHIVED):
        raise HTTPException(
            status_code=409,
            detail=f"This application can't be archived from its current state ({app.status.value}).",
        )
    archived = svc.archive(ApplicationId(application_id))
    if archived is None:  # pragma: no cover - defensive: guarded above
        raise HTTPException(status_code=404, detail="No such application.")
    return {"application_id": application_id, "status": archived.status.value}


@router.post("/applications/{application_id}/scan-email")
def scan_email(
    application_id: str,
    body: ScanEmailIn,
    svc=Depends(get_post_submission_service),
) -> dict:
    """Run one inbound email's subject/body through all three outcome detectors
    (rejection / offer / interview-invite -- design-audit Top-25 #5) and record
    whatever confidently matched.

    This finally makes the email-scanning capability (``scan_email_for_rejection``
    et al.) reachable via a real endpoint. Nothing calls it automatically yet --
    matching a raw inbox to the right application is a deliberately separate,
    higher-risk piece of work (a false match would record a fake outcome against
    the wrong application) -- but a human, a test, or a future automated bridge
    now CAN call this. Gated the same as every other route on this router
    (``require_llm_configured``); 404s for an application that does not exist.
    """
    result = svc.scan_email(ApplicationId(application_id), subject=body.subject, body=body.body)
    if result is None:
        # Either the application does not exist, or nothing matched at all --
        # distinguish the two so the caller gets a real 404 for the former.
        if svc.poll_status(ApplicationId(application_id)) is None:
            raise HTTPException(status_code=404, detail="No such application.")
        return {"application_id": application_id, "detected": False}
    return {"application_id": application_id, "detected": True, **result}
