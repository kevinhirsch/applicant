"""Review-UX router (EPIC REVIEW-UX — RUX-1/2/3).

The Pending-Reviews decision + refinement workflow — the surface where the owner
actually works a queued application. The flow (per the epic):

    open the SOURCE posting  ->  decide Continue / Save-for-later / Discard
      ->  (if Continue) review + refine the generated answers

This router is deliberately THIN UX + wiring over engines that already exist —
it composes them, it does not re-implement them:

* **RUX-1 source posting** — the review payload carries the live ``source_url`` PLUS
  a cached snapshot (captured at first read from the posting's already-ingested
  fields and persisted into the posting's free-form ``rationale`` JSON, no schema
  change) so a pulled/unreachable listing is still readable. The link never leaks
  PII (it is the posting's own URL; the snapshot is server-side).
* **RUX-2 three-way decision** —
    - **Continue**: approve the app's generated materials through the review gate
      (reuse ``MaterialService.open_revision`` + ``MaterialService.approve`` /
      ``approve_variant``). Continue IS the human OK the RUX-3 edits defer to.
    - **Save-for-later**: reuse ``PendingActionsService.save_for_later`` — a distinct
      "Saved / To submit" bucket + a reminder nudge that reuses the snooze wake-time.
    - **Discard-with-reason**: reuse ``MaterialService.decline`` (archived + reversible,
      never deletes) + ``FeedbackService.submit_posting_feedback`` with negative
      sentiment so the reason feeds negative learning (similar roles rank lower).
* **RUX-3 regenerate** — per-section (reuse ``generate_cover_letter`` /
  ``generate_screening_answer`` / ``select_or_generate``), cross-section + inline-edit
  (reuse the ``open_revision`` -> ``apply_turn`` revision loop), and whole-app
  regenerate. EVERY edit stays review-gated: generation stores unapproved and a
  revision turn never approves, so nothing is sent until the human Continues.

Gated behind the LLM gate (FR-UI-5), like its review siblings (feedback/digest).

WIRING: this router is NOT registered here (shared wiring is owned by the Integrate
step). Register it in ``src/applicant/app/routers/__init__.py``::

    from applicant.app.routers import review        # add to the import block
    app.include_router(review.router)                # add alongside feedback/digest

No new container binding is needed — every service it depends on already has a
provider in ``src/applicant/app/deps.py`` (get_storage / get_material_service /
get_pending_actions_service / get_feedback_service).
"""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from applicant.app.deps import (
    get_feedback_service,
    get_material_service,
    get_pending_actions_service,
    get_storage,
    require_llm_configured,
)

router = APIRouter(
    prefix="/api/review", tags=["review"], dependencies=[Depends(require_llm_configured)]
)

#: Where the cached source-posting snapshot lives on the posting's free-form
#: ``rationale`` JSON dict (RUX-1). Reusing an existing JSON column keeps this a
#: pure composition — no entity/schema change.
SNAPSHOT_KEY = "snapshot"


# --- request models --------------------------------------------------------
class SaveForLaterIn(BaseModel):
    campaign_id: str
    title: str | None = None
    posting_id: str | None = None
    remind_in_hours: float = 24.0


class DiscardIn(BaseModel):
    campaign_id: str
    reason: str
    posting_id: str | None = None


class SectionRegenIn(BaseModel):
    campaign_id: str
    kind: str  # "cover_letter" | "screening_answer" | "resume"
    true_source: str = ""
    jd_terms: list[str] = []
    question: str | None = None  # screening_answer
    posting_id: str | None = None  # resume
    base_source: str | None = None  # resume (defaults to true_source)
    essay: bool | None = None
    explicit_answer: str | None = None
    role_requires: bool | None = None  # cover_letter


class ApplyInstructionIn(BaseModel):
    campaign_id: str
    instruction: str
    kind: str = "free_text"  # free_text | add | subtract
    document_ids: list[str] = []  # empty -> ALL the app's generated sections (cross-section)
    true_source: str | None = None


class WholeAppRegenIn(BaseModel):
    campaign_id: str
    true_source: str = ""
    jd_terms: list[str] = []
    posting_id: str | None = None
    base_source: str | None = None
    questions: list[str] = []
    include_cover_letter: bool = True
    role_requires: bool | None = True


# --- helpers ---------------------------------------------------------------
def _pa_to_dict(action) -> dict:
    return {
        "id": str(action.id),
        "kind": action.kind,
        "title": action.title,
        "application_id": str(action.application_id) if action.application_id else None,
        "payload": action.payload or {},
    }


def _ensure_snapshot(storage, posting) -> dict:
    """Return the posting's cached snapshot, capturing one on first read if absent (RUX-1).

    "Captured at ingest": discovery/intake normalize the posting's fields (title,
    company, description, ...) at ingest, so the snapshot is a frozen, readable copy
    built from that already-ingested content — it stays readable even if the live
    listing is later pulled. Persisted into the posting's free-form ``rationale`` JSON
    (no schema change) so it survives restarts; idempotent (a present snapshot wins).
    Best-effort persistence: a read must never 500 because the cache-warm write hit
    a snag — the snapshot is still returned.
    """
    existing = (posting.rationale or {}).get(SNAPSHOT_KEY)
    if existing:
        return existing
    snapshot = {
        "captured_at": datetime.now(UTC).isoformat(),
        "title": posting.title,
        "company": posting.company,
        "location": posting.location,
        "work_mode": posting.work_mode,
        "salary": posting.salary,
        "text": posting.description or "",
        "source_url": posting.source_url,
    }
    try:
        updated = dataclasses.replace(
            posting, rationale={**(posting.rationale or {}), SNAPSHOT_KEY: snapshot}
        )
        storage.postings.add(updated)
        storage.commit()
    except Exception:  # pragma: no cover - cache-warm must never break the read
        pass
    return snapshot


def _require_app(storage, application_id: str):
    from applicant.core.ids import ApplicationId

    app = storage.applications.get(ApplicationId(application_id))
    if app is None:
        raise HTTPException(status_code=404, detail=f"no such application {application_id}")
    return app


def _generated_docs(storage, application_id):
    """The app's engine-generated documents (excludes operator-supplied attachments)."""
    from applicant.core.ids import ApplicationId

    aid = application_id if not isinstance(application_id, str) else ApplicationId(application_id)
    return [
        d
        for d in storage.documents.list_for_application(aid)
        if not d.type.is_attachment
    ]


# --- index -----------------------------------------------------------------
@router.get("")
def index() -> dict:
    return {"surface": "review", "phase": 3, "status": "live"}


# === RUX-1: source posting link + cached snapshot ==========================
@router.get("/{application_id}/source")
def source_posting(application_id: str, storage=Depends(get_storage)) -> dict:
    """Live source-posting URL + a cached snapshot for the app under review (RUX-1)."""
    app = _require_app(storage, application_id)
    posting = storage.postings.get(app.posting_id)
    if posting is None:
        raise HTTPException(
            status_code=404, detail="no source posting for this application"
        )
    snapshot = _ensure_snapshot(storage, posting)
    return {
        "application_id": application_id,
        "posting_id": str(posting.id),
        "source_url": posting.source_url,  # live link (the posting's own URL — no PII)
        "snapshot": snapshot,  # cached copy — readable even if the listing is pulled
        "snapshot_ref": f"posting:{posting.id}",
    }


# === RUX-2: three-way decision — Continue / Save-for-later / Discard ========
@router.post("/{application_id}/continue")
def continue_review(
    application_id: str,
    storage=Depends(get_storage),
    material=Depends(get_material_service),
) -> dict:
    """Continue: approve the app's generated materials through the review gate (RUX-2).

    Reuses the review gate: ``open_revision`` (opening the redline surface, which the
    "view-before-approve" server-side guard requires) then ``MaterialService.approve``
    per generated document, and ``approve_variant`` for a linked generated résumé
    variant. Continue is the human OK the RUX-3 edits stay unapproved for.
    """
    app = _require_app(storage, application_id)
    approved: list[str] = []
    for doc in _generated_docs(storage, application_id):
        material.open_revision(doc.id)  # idempotent — represents "review surface opened"
        result = material.approve(doc.id)
        approved.append(str(result.id))
    approved_variant: str | None = None
    variant_id = getattr(app, "resume_variant_id", None)
    if variant_id is not None:
        variant = storage.resume_variants.get(variant_id)
        if variant is not None and not variant.approved:
            material.approve_variant(variant_id)
            approved_variant = str(variant_id)
    return {
        "decision": "continue",
        "proceeded": True,
        "approved_documents": approved,
        "approved_variant": approved_variant,
    }


@router.post("/{application_id}/save-for-later", status_code=201)
def save_for_later(
    application_id: str,
    body: SaveForLaterIn,
    storage=Depends(get_storage),
    pending=Depends(get_pending_actions_service),
) -> dict:
    """Save-for-later: move the app to the distinct "Saved / To submit" bucket (RUX-2).

    Reuses ``PendingActionsService.save_for_later`` — materialize + snooze, where the
    snooze wake-time IS the reminder nudge. Out of the active queue, reversible.
    """
    from applicant.core.ids import ApplicationId, CampaignId

    aid = ApplicationId(application_id)
    app = storage.applications.get(aid)
    title = body.title or (
        (app.job_title or app.role_name or "Saved application") if app else "Saved application"
    )
    posting_id = body.posting_id or (str(app.posting_id) if app else None)
    action = pending.save_for_later(
        CampaignId(body.campaign_id),
        title=title,
        application_id=aid,
        posting_id=posting_id,
        remind_in_hours=body.remind_in_hours,
    )
    return {
        "decision": "save_for_later",
        "bucket": "saved",
        "saved_action_id": str(action.id),
        "reminder_at": (action.payload or {}).get("snoozed_until"),
    }


@router.get("/{campaign_id}/saved")
def saved_bucket(
    campaign_id: str, pending=Depends(get_pending_actions_service)
) -> dict:
    """The distinct "Saved / To submit" bucket for a campaign (RUX-2)."""
    from applicant.core.ids import CampaignId

    items = pending.list_saved(CampaignId(campaign_id))
    return {"campaign_id": campaign_id, "items": [_pa_to_dict(a) for a in items]}


@router.post("/{application_id}/discard", status_code=201)
def discard(
    application_id: str,
    body: DiscardIn,
    storage=Depends(get_storage),
    material=Depends(get_material_service),
    feedback=Depends(get_feedback_service),
) -> dict:
    """Discard-with-reason: decline (reversibly) + feed the reason to negative learning (RUX-2).

    A reason is mandatory. Reuses ``MaterialService.decline`` (the materials stay as
    an archived, reversible record — never deleted) + ``FeedbackService`` with
    negative sentiment so the reason ranks similar roles lower (FR-LEARN + feedback).
    """
    from applicant.core.ids import CampaignId, JobPostingId

    reason = (body.reason or "").strip()
    if not reason:
        raise HTTPException(status_code=422, detail="a discard reason is required")
    app = _require_app(storage, application_id)
    declined: list[str] = []
    for doc in _generated_docs(storage, application_id):
        material.decline(doc.id)  # archived + reversible; never deletes user data
        declined.append(str(doc.id))
    posting_id = body.posting_id or str(app.posting_id)
    try:
        learning = feedback.submit_posting_feedback(
            CampaignId(body.campaign_id),
            JobPostingId(posting_id),
            sentiment="negative",
            text=reason,
        )
    except Exception:  # pragma: no cover - a learning hiccup must not lose the discard
        learning = {"folded": False}
    return {
        "decision": "discard",
        "reason": reason,
        "declined_documents": declined,
        "learning": learning,
        "reversible": True,
    }


# === RUX-3: per-section / cross-section / whole-app regenerate ==============
@router.post("/{application_id}/regenerate/section", status_code=201)
def regenerate_section(
    application_id: str,
    body: SectionRegenIn,
    storage=Depends(get_storage),
    material=Depends(get_material_service),
) -> dict:
    """Regenerate ONE section, review-gated (RUX-3).

    Reuses ``generate_cover_letter`` / ``generate_screening_answer`` /
    ``select_or_generate``; the new material is stored UNAPPROVED (review-gated).
    """
    from applicant.core.ids import ApplicationId, CampaignId, JobPostingId

    _require_app(storage, application_id)
    aid = ApplicationId(application_id)
    cid = CampaignId(body.campaign_id)
    kind = (body.kind or "").lower()
    if kind == "cover_letter":
        doc = material.generate_cover_letter(
            cid, aid, body.true_source, body.jd_terms, role_requires=body.role_requires
        )
        if doc is None:
            return {
                "section": "cover_letter",
                "regenerated": False,
                "reason": "a cover letter is not warranted for this role",
            }
        return {
            "section": "cover_letter",
            "regenerated": True,
            "document_id": str(doc.id),
            "approved": doc.approved,
            "review_gated": True,
        }
    if kind == "screening_answer":
        if not body.question:
            raise HTTPException(
                status_code=422, detail="a 'question' is required for a screening_answer"
            )
        doc = material.generate_screening_answer(
            cid,
            aid,
            body.question,
            body.true_source,
            essay=body.essay,
            explicit_answer=body.explicit_answer,
        )
        return {
            "section": "screening_answer",
            "regenerated": True,
            "document_id": str(doc.id),
            "approved": doc.approved,
            "review_gated": True,
        }
    if kind == "resume":
        if not body.posting_id:
            raise HTTPException(
                status_code=422, detail="a 'posting_id' is required for a resume section"
            )
        base = body.base_source or body.true_source
        result = material.select_or_generate(
            cid, JobPostingId(body.posting_id), body.jd_terms, base, application_id=aid
        )
        return {
            "section": "resume",
            "regenerated": True,
            "variant_id": str(result.variant.id),
            "generated": result.generated,
            "approved": result.variant.approved,
            "review_gated": True,
        }
    raise HTTPException(status_code=422, detail=f"unknown section kind: {body.kind!r}")


@router.post("/{application_id}/apply-instruction", status_code=201)
def apply_instruction(
    application_id: str,
    body: ApplyInstructionIn,
    storage=Depends(get_storage),
    material=Depends(get_material_service),
) -> dict:
    """Apply one instruction across sections, or inline-edit a section — review-gated (RUX-3).

    Reuses the ``open_revision`` -> ``apply_turn`` revision loop. With no
    ``document_ids`` the instruction fans across ALL the app's generated sections
    (cross-section / whole-app feedback); with a single id it is an inline edit of
    that section. A revision turn never approves, so every result stays review-gated.
    """
    from applicant.core.ids import GeneratedDocumentId

    if body.kind not in ("free_text", "add", "subtract"):
        raise HTTPException(status_code=422, detail=f"unknown turn kind: {body.kind!r}")
    _require_app(storage, application_id)
    if body.document_ids:
        target_ids = [GeneratedDocumentId(d) for d in body.document_ids]
    else:
        target_ids = [d.id for d in _generated_docs(storage, application_id)]
    results: list[dict] = []
    for did in target_ids:
        session = material.apply_turn(
            did, body.kind, body.instruction, true_source=body.true_source
        )
        results.append(
            {
                "document_id": str(did),
                "turns": len(session.turns),
                "content": (session.redline_state or {}).get("content"),
                "status": getattr(session.status, "value", str(session.status)),
            }
        )
    return {
        "instruction": body.instruction,
        "kind": body.kind,
        "sections": results,
        "review_gated": True,
    }


@router.post("/{application_id}/regenerate/whole", status_code=201)
def regenerate_whole(
    application_id: str,
    body: WholeAppRegenIn,
    storage=Depends(get_storage),
    material=Depends(get_material_service),
) -> dict:
    """Regenerate the WHOLE application — every section, review-gated (RUX-3).

    Composes the per-section generators (résumé variant, cover letter, each screening
    answer). Every regenerated section is stored UNAPPROVED (review-gated).
    """
    from applicant.core.ids import ApplicationId, CampaignId, JobPostingId

    _require_app(storage, application_id)
    aid = ApplicationId(application_id)
    cid = CampaignId(body.campaign_id)
    regenerated: list[dict] = []
    base = body.base_source or body.true_source
    if body.posting_id:
        result = material.select_or_generate(
            cid, JobPostingId(body.posting_id), body.jd_terms, base, application_id=aid
        )
        regenerated.append(
            {
                "section": "resume",
                "variant_id": str(result.variant.id),
                "generated": result.generated,
                "approved": result.variant.approved,
            }
        )
    if body.include_cover_letter:
        doc = material.generate_cover_letter(
            cid, aid, body.true_source, body.jd_terms, role_requires=body.role_requires
        )
        if doc is not None:
            regenerated.append(
                {
                    "section": "cover_letter",
                    "document_id": str(doc.id),
                    "approved": doc.approved,
                }
            )
    for question in body.questions:
        doc = material.generate_screening_answer(cid, aid, question, body.true_source)
        regenerated.append(
            {
                "section": "screening_answer",
                "question": question,
                "document_id": str(doc.id),
                "approved": doc.approved,
            }
        )
    return {"regenerated": regenerated, "review_gated": True}
