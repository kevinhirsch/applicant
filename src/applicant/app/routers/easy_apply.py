"""Easy Apply assisted-mode router (P2-14, road-to-market backlog).

P1-11 already detects a board's built-in quick-apply channel at discovery time
(``JobPosting.easy_apply``) and tags the digest/tracker rows with it -- detection
only, zero automation. This is the next step the owner explicitly scoped for
now: the ASSISTED-MODE product surface -- a deep link to the real posting, the
candidate's own prepared materials, and a plain checklist -- with the actual
live-account automation (walking the quick-apply modal, logging in with a real
persistent session) **deferred** until the owner supplies a real, owner-
controlled account for proof runs (see the road-to-market backlog's P2-14 entry
and its dependent P5-6 full-autopilot story). Nothing here logs into a job
board, fills a field, or clicks anything -- the user drives every action
themselves, the exact same review-before-submit / stop-boundary posture the
rest of the engine enforces (``core/rules/prefill_boundary.py``).

Safety: the consent screen this pairs with is a real stop-boundary surface, not
decoration -- ``GET .../{posting_id}`` refuses (409) until
``SetupService.record_easy_apply_consent`` has actually recorded acceptance.
That record is set ONLY by the dedicated ``POST /api/setup/easy-apply-consent``
endpoint (``setup.py``) -- there is no caller-supplied flag on this route (or
any other) that can opt the check in.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from applicant.app.deps import get_setup_service, get_storage

router = APIRouter(prefix="/api/easy-apply", tags=["easy-apply"])

#: The plain-language, no-jargon checklist the assisted-mode brief hands back for
#: every Easy-Apply posting. Static (identical for every role) -- kept as a
#: module-level constant so both the front door and any future test can assert
#: the exact wording without re-deriving it. Order matters: it walks the same
#: sequence a human would actually follow.
ASSIST_CHECKLIST: tuple[str, ...] = (
    "Open the posting using the link below.",
    "Attach your tailored resume and cover letter from your Documents library.",
    "Answer the screening questions yourself -- including any EEO or "
    "work-authorization questions, which Applicant never answers for you.",
    "Review everything, then submit the application yourself on the job board.",
)


@router.get("/{campaign_id}/{posting_id}")
def assist(
    campaign_id: str,
    posting_id: str,
    svc=Depends(get_setup_service),
    storage=Depends(get_storage),
) -> dict:
    """The assisted-mode brief for one Easy-Apply posting (P2-14).

    Server-enforced stop-boundary: this never logs into the job board, fills a
    field, or submits anything -- it only hands back a deep link, a plain
    checklist, and a pointer at the candidate's own already-prepared materials,
    and ONLY once the consent screen has actually been recorded server-side
    (409 otherwise -- never a caller-supplied opt-in around it). 404 when the
    posting doesn't exist, doesn't belong to ``campaign_id``, or isn't actually
    tagged Easy-Apply (mirrors ``criteria.py``'s ``posting_alignment`` 404
    shape for the same "wrong posting/campaign pair" case).
    """
    consent = svc.easy_apply_consent_status()
    if not consent.get("given"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Accept the Easy Apply assisted-mode consent screen first.",
        )
    posting = storage.postings.get(posting_id)  # type: ignore[arg-type]
    if posting is None or str(posting.campaign_id) != str(campaign_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such posting.")
    if not bool(getattr(posting, "easy_apply", False)):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="This posting isn't tagged as an Easy Apply role.",
        )
    return {
        "campaign_id": str(campaign_id),
        "posting_id": str(posting_id),
        "title": posting.title,
        "company": posting.company,
        "deep_link": posting.source_url,
        "checklist": list(ASSIST_CHECKLIST),
        "consent_given_at": consent.get("given_at"),
    }
