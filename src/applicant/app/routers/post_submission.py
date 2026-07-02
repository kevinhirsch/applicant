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

from applicant.app.deps import get_post_submission_service, require_llm_configured
from applicant.core.entities.outcome_event import OUTCOME_TYPES
from applicant.core.ids import ApplicationId, CampaignId

router = APIRouter(
    prefix="/api/post-submission",
    tags=["post-submission"],
    dependencies=[Depends(require_llm_configured)],
)


class RecordOutcomeIn(BaseModel):
    outcome_type: str


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
    return {
        "application_id": application_id,
        "outcome_id": str(event.id),
        "type": event.type,
        "source": event.source.value,
    }


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
