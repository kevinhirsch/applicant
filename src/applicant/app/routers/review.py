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
from html import escape as _escape

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from applicant.app.deps import (
    get_digest_service,
    get_feedback_service,
    get_material_service,
    get_pending_actions_service,
    get_storage,
    require_llm_configured,
)
from applicant.core.entities.generated_document import DocumentType
from applicant.core.entities.revision_session import RevisionStatus
from applicant.core.errors import NotFound
from applicant.core.rules.freshness import posting_freshness

router = APIRouter(
    prefix="/api/review", tags=["review"], dependencies=[Depends(require_llm_configured)]
)

#: Where the cached source-posting snapshot lives on the posting's free-form
#: ``rationale`` JSON dict (RUX-1). Reusing an existing JSON column keeps this a
#: pure composition — no entity/schema change.
SNAPSHOT_KEY = "snapshot"


# --- request models --------------------------------------------------------
class DraftIn(BaseModel):
    campaign_id: str


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
    # Two modes: (a) refine an EXISTING section in place by its ``section_id``
    # (the review-panel button — stable id, review-gated), or (b) generate a FRESH
    # section from ``kind`` + sources (the explicit API / BDD path).
    section_id: str | None = None  # (a) existing generated-document id to refine
    instruction: str = ""  # (a) optional refinement instruction (empty is allowed)
    kind: str = ""  # (b) "cover_letter" | "screening_answer" | "resume"
    true_source: str = ""
    jd_terms: list[str] = []
    question: str | None = None  # screening_answer
    posting_id: str | None = None  # resume
    base_source: str | None = None  # resume (defaults to true_source)
    essay: bool | None = None
    explicit_answer: str | None = None
    role_requires: bool | None = None  # cover_letter


class EditSectionIn(BaseModel):
    section_id: str
    content: str = ""


class ApplyInstructionIn(BaseModel):
    campaign_id: str
    instruction: str
    kind: str = "free_text"  # free_text | add | subtract
    document_ids: list[str] = []  # empty -> ALL the app's generated sections (cross-section)
    true_source: str | None = None


class WholeAppRegenIn(BaseModel):
    campaign_id: str
    # Panel mode (no explicit inputs below): refresh every EXISTING section in place,
    # optionally guided by ``instruction`` (empty is allowed — the "Regenerate whole
    # app" button no longer errors with no typed feedback).
    instruction: str = ""
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


#: Human-friendly section labels for the review panel (never the raw enum value).
_SECTION_LABELS = {
    DocumentType.RESUME: "Résumé",
    DocumentType.COVER_LETTER: "Cover letter",
    DocumentType.SCREENING_ANSWER: "Screening answer",
    DocumentType.PORTFOLIO: "Portfolio",
    DocumentType.ATTACHMENT: "Attachment",
}


def _section_status(storage, doc) -> str:
    """Plain review status for a generated section (RUX-3).

    Reflects the review gate + the durable revision session: an approved document is
    ``"approved"``; a declined one ``"declined"``; anything else is a ``"pending"``
    draft awaiting the human's decision. Every regenerate/edit path keeps a section
    unapproved, so the panel can always show that nothing is submitted yet.
    """
    if getattr(doc, "approved", False):
        return "approved"
    try:
        session = storage.revisions.get_for_material(doc.id)
    except Exception:  # pragma: no cover - status is advisory; never break the read
        session = None
    if session is not None and session.status is RevisionStatus.DECLINED:
        return "declined"
    return "pending"


def _serialize_section(storage, doc) -> dict:
    """One generated document as the ``{section_id,label,content,status}`` shape the
    review panel binds against (RUX-3 fix A/B).

    ``document_id`` + ``kind`` + ``approved`` are carried alongside for callers that
    key off them (and for the existing apply-instruction contract), but the panel only
    needs ``section_id`` (its x-for key), ``label`` (header), ``content`` (the editable
    textarea) and ``status`` (the review-gated badge)."""
    return {
        "section_id": str(doc.id),
        "document_id": str(doc.id),
        "kind": doc.type.value,
        "label": _SECTION_LABELS.get(doc.type, doc.type.value),
        "content": doc.content or "",
        "status": _section_status(storage, doc),
        "approved": bool(getattr(doc, "approved", False)),
    }


def _linked_variant(storage, application_id):
    """The app's linked GENERATED résumé variant, or ``None`` (P1 résumé-in-review).

    ``ResumeVariant`` is a distinct entity from ``GeneratedDocument`` — it lives in its
    own table (``storage.resume_variants``), keyed off ``Application.resume_variant_id``
    — so it was never among ``_generated_docs`` and never appeared in ``/sections``.
    """
    from applicant.core.ids import ApplicationId

    aid = application_id if not isinstance(application_id, str) else ApplicationId(application_id)
    app = storage.applications.get(aid)
    variant_id = getattr(app, "resume_variant_id", None) if app is not None else None
    if variant_id is None:
        return None
    return storage.resume_variants.get(variant_id)


def _serialize_variant(variant) -> dict:
    """The app's résumé VARIANT in the same ``{section_id,label,content,status}`` shape
    ``_serialize_section`` uses (P1 fix — the résumé never appeared in "Generated
    answers" even though Continue already silently approves it via ``approve_variant``).

    A variant is file-rendered (``storage_path`` — LaTeX/docx), not a plain-text
    ``content`` string, so there is no inline body to preview/edit the way a cover
    letter or screening answer has. ``kind: "resume"`` + ``variant_id`` let the panel
    (and ``regenerate_section`` below) treat it as reviewable — status/approved reflect
    the SAME review gate Continue enforces — and regeneratable via the existing
    kind-based résumé path, without inventing a fabricated body.
    """
    coverage = (variant.fit_scores or {}).get("coverage")
    coverage_note = (
        f"coverage vs this role: {round(coverage * 100)}%"
        if isinstance(coverage, (int, float))
        else "not yet scored against this role"
    )
    return {
        "section_id": str(variant.id),
        "document_id": str(variant.id),
        "variant_id": str(variant.id),
        "kind": "resume",
        "label": "Résumé",
        "content": (
            f"Tailored résumé variant — {coverage_note}. Résumé variants are "
            "file-rendered, so there is no inline text preview here — use "
            "Regenerate for a fresh tailored draft."
        ),
        "status": "approved" if bool(getattr(variant, "approved", False)) else "pending",
        "approved": bool(getattr(variant, "approved", False)),
    }


def _sections_payload(storage, application_id) -> list[dict]:
    """Every engine-generated section of an app, in the panel's binding shape (RUX-3).

    P1 fix: also carries the app's linked GENERATED résumé variant (when one exists)
    alongside the cover letter / screening-answer ``GeneratedDocument`` sections.
    """
    sections = [_serialize_section(storage, d) for d in _generated_docs(storage, application_id)]
    variant = _linked_variant(storage, application_id)
    if variant is not None:
        sections.append(_serialize_variant(variant))
    return sections


def _snapshot_html(snapshot: dict) -> str:
    """Render the cached posting snapshot as a self-contained, escaped HTML page (RUX-1).

    The panels open this in a new tab as a blob, so a pulled/unreachable listing is
    still readable. Every field is HTML-escaped (the snapshot is captured from
    ingested, potentially-untrusted posting text) — this is display-only, never a
    live link the user is asked to trust."""
    snapshot = snapshot or {}
    title = _escape(str(snapshot.get("title") or "This role"))
    company = _escape(str(snapshot.get("company") or ""))
    meta_bits = [
        snapshot.get("company"),
        snapshot.get("location"),
        snapshot.get("work_mode"),
        snapshot.get("salary"),
    ]
    meta = _escape(" · ".join(str(b) for b in meta_bits if b))
    captured = _escape(str(snapshot.get("captured_at") or ""))
    source_url = str(snapshot.get("source_url") or "")
    is_http = source_url.startswith("http://") or source_url.startswith("https://")
    link = (
        f'<p><a href="{_escape(source_url)}" rel="noopener noreferrer">Live posting</a></p>'
        if is_http
        else ""
    )
    # Preserve the posting's line breaks; escape first so no markup can be injected.
    body = _escape(str(snapshot.get("text") or "")).replace("\n", "<br>")
    return (
        "<!doctype html><html><head><meta charset='utf-8'>"
        f"<title>{title}</title>"
        "<style>body{font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif;"
        "max-width:720px;margin:2rem auto;padding:0 1rem;line-height:1.5;color:#1a1a1a}"
        ".meta{color:#6b7683;font-size:.9rem;margin:.25rem 0 1rem}"
        ".cap{color:#8a8f98;font-size:.8rem;margin-top:2rem;border-top:1px solid #e3e8ec;"
        "padding-top:.75rem}</style></head><body>"
        f"<h1>{title}</h1>"
        f"<div class='meta'>{meta}</div>"
        f"{link}"
        f"<div>{body}</div>"
        f"<div class='cap'>Cached snapshot{f' · captured {captured}' if captured else ''}. "
        "Read-only copy of the posting as first ingested.</div>"
        "</body></html>"
    )


def _freshness_fields(posting) -> dict:
    """Top-level posted_* freshness cue for a posting, or empty dict when unknown (RUX-1)."""
    fresh = posting_freshness(
        getattr(posting, "date_posted", None), getattr(posting, "first_seen", None)
    )
    if not fresh:
        return {"posted_label": "", "posted_relative": "", "posted_stale": False}
    return {
        "posted_label": fresh.get("posted_label", ""),
        "posted_relative": fresh.get("posted_relative", ""),
        "posted_stale": bool(fresh.get("posted_stale", False)),
        "posted_date": fresh.get("posted_date"),
    }


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
        # RUX-1 fix C: the review modal reads these at the top level (title/company +
        # freshness) and opens ``html`` as a cached-snapshot blob when the listing is
        # pulled. Emitting them here keeps the panel a single ``get`` call.
        "snapshot_available": True,
        "html": _snapshot_html(snapshot),
        "title": posting.title,
        "company": posting.company,
        "location": posting.location,
        **_freshness_fields(posting),
        # RUX-3 fix A: the generated sections the panel refines. Without this the
        # panel's rvSections was always [] and every per-section control was inert.
        "sections": _sections_payload(storage, application_id),
    }


@router.get("/{application_id}/sections")
def sections(application_id: str, storage=Depends(get_storage)) -> dict:
    """The app's generated sections in the review panel's binding shape (RUX-3 fix A).

    ``[{section_id,label,content,status,kind,approved}]`` — what unblocks the whole
    per-section review surface. Dedicated endpoint (the composite ``/source`` also
    embeds these) so the panel / regenerate handlers can refresh sections in isolation.
    """
    _require_app(storage, application_id)
    return {
        "application_id": application_id,
        "sections": _sections_payload(storage, application_id),
    }


@router.get("/posting/{posting_id}/snapshot")
def posting_snapshot(posting_id: str, storage=Depends(get_storage)) -> dict:
    """The cached posting snapshot rendered as HTML, keyed by POSTING id (RUX-1 fix C).

    The Digest "Cached snapshot" button has only a posting id (there may be no
    application yet), so it can't use the application-keyed ``/source``. Returns the
    same rendered ``html`` blob the review modal opens for a pulled/unreachable listing.
    """
    from applicant.core.ids import JobPostingId

    posting = storage.postings.get(JobPostingId(posting_id))
    if posting is None:
        raise HTTPException(status_code=404, detail=f"no such posting {posting_id}")
    snapshot = _ensure_snapshot(storage, posting)
    return {
        "posting_id": str(posting.id),
        "source_url": posting.source_url,
        "snapshot": snapshot,
        "snapshot_available": True,
        "html": _snapshot_html(snapshot),
        **_freshness_fields(posting),
    }


@router.post("/posting/{posting_id}/draft", status_code=201)
def draft_from_posting(
    posting_id: str,
    body: DraftIn,
    digest=Depends(get_digest_service),
) -> dict:
    """Draft (or find) the application for a POSTING, keyed by posting id (RUX-1 fix D).

    A digest/top-match row is a pre-application POSTING with no ``application_id`` yet
    (0 of 98 digest rows carried one) — there is nothing to open by application id
    until one exists. "Review" on such a row must draft the application FIRST, never
    pass the posting id off as an application id (that 404s "no such application").

    Routes through the EXISTING draft-this path — reuses ``DigestService.approve``
    (the same gated path the chat ``draft_application`` tool and the landing page's
    "Draft this" button already use): find-or-create the application for this posting
    and advance it into the pursue/draft pipeline. Materials are tailored from there
    but stay review-gated — this never submits anything and never auto-approves
    generated materials (that stays the human's call through Continue). Idempotent: a
    second draft of the same posting finds the application already created and
    returns it unchanged (no duplicate).
    """
    from applicant.core.ids import JobPostingId

    try:
        decision = digest.approve(JobPostingId(posting_id))
    except NotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {
        "application_id": str(decision.application_id),
        "posting_id": posting_id,
        "campaign_id": body.campaign_id,
        "drafted": True,
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

    Two modes:

    * **by ``section_id``** (the review-panel button): refine the EXISTING generated
      document in place via the ``open_revision`` -> ``apply_turn`` revision loop, so
      the section keeps its id (the panel merges the result by ``section_id``) and the
      turn never approves. Returns the consistent singular ``{section:{...}}`` shape.
      P1 fix: a ``section_id`` that is not a ``GeneratedDocument`` falls back to the
      app's linked résumé VARIANT (now that it appears in ``/sections`` too) — a
      variant isn't free-text revised in place (it's selected/forked), so this routes
      to the SAME ``select_or_generate`` the explicit ``kind="resume"`` mode below uses,
      scoped to the application's own posting.
    * **by ``kind`` + sources** (the explicit API / BDD path): generate a FRESH section
      (``generate_cover_letter`` / ``generate_screening_answer`` / ``select_or_generate``).

    Either way the material is stored UNAPPROVED (review-gated).
    """
    from applicant.core.ids import (
        ApplicationId,
        CampaignId,
        GeneratedDocumentId,
        JobPostingId,
        ResumeVariantId,
    )

    app = _require_app(storage, application_id)
    aid = ApplicationId(application_id)
    cid = CampaignId(body.campaign_id)

    # Mode (a): refine an existing section in place (the panel's per-section button).
    if body.section_id:
        did = GeneratedDocumentId(body.section_id)
        doc = storage.documents.get(did)
        if doc is not None:
            instruction = (body.instruction or "").strip() or (
                "Give this section a fresh take — reframe and tighten it while staying "
                "strictly truthful."
            )
            # A free-text revision turn: re-drafts the content, never approves (the turn
            # loop is review-gated), and keeps the document id stable. ``true_source`` is
            # derived server-side by the service when omitted (fabrication guard still
            # runs).
            material.apply_turn(
                did, "free_text", instruction, true_source=(body.true_source or None)
            )
            return {
                "section": _serialize_section(storage, storage.documents.get(did)),
                "regenerated": True,
                "review_gated": True,
            }
        # Not a GeneratedDocument -- the app's linked résumé VARIANT, if it matches.
        variant = storage.resume_variants.get(ResumeVariantId(body.section_id))
        if variant is None:
            raise HTTPException(
                status_code=404, detail=f"no such section {body.section_id}"
            )
        if app.posting_id is None:
            raise HTTPException(
                status_code=422,
                detail="this application has no linked posting to tailor the résumé against",
            )
        jd_terms = [t for t in (variant.targeted_jd_signature or "").split(",") if t]
        result = material.select_or_generate(
            cid, app.posting_id, jd_terms, body.true_source or "", application_id=aid
        )
        return {
            "section": _serialize_variant(result.variant),
            "regenerated": True,
            "review_gated": True,
        }

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
        # Normalize to the panel's ``{section_id,label,content,status}`` shape so the
        # cross-section x-for :key="section_id" renders (it was missing before, so the
        # updated drafts never rendered). ``document_id`` + ``turns`` are kept for the
        # existing turn-recorded contract.
        doc = storage.documents.get(did)
        item = (
            _serialize_section(storage, doc)
            if doc is not None
            else {"section_id": str(did), "document_id": str(did), "label": "Section",
                  "content": (session.redline_state or {}).get("content") or "",
                  "status": "pending", "kind": "", "approved": False}
        )
        item["turns"] = len(session.turns)
        results.append(item)
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

    Two modes:

    * **panel mode** (no ``posting_id`` / ``questions`` / ``true_source``): refresh
      every EXISTING generated section in place via the revision loop, optionally
      guided by ``instruction`` (empty allowed — the "Regenerate whole app" button no
      longer errors with no typed feedback). Ids stay stable, nothing approves.
    * **explicit mode** (any of those inputs present): freshly compose the per-section
      generators (résumé variant, cover letter, each screening answer).

    Every regenerated section is stored UNAPPROVED (review-gated) either way.
    """
    from applicant.core.ids import ApplicationId, CampaignId, JobPostingId

    _require_app(storage, application_id)
    aid = ApplicationId(application_id)
    cid = CampaignId(body.campaign_id)

    explicit = bool(body.posting_id) or bool(body.questions) or bool(
        (body.true_source or "").strip()
    )
    if not explicit:
        # Panel mode: re-draft every existing section in place (uniform with the
        # per-section button), never approving. When there is nothing drafted yet
        # this is a harmless no-op that returns an empty section set.
        instruction = (body.instruction or "").strip() or (
            "Regenerate this section with a fresh, truthful take."
        )
        for doc in _generated_docs(storage, application_id):
            material.apply_turn(doc.id, "free_text", instruction, true_source=None)
        return {
            "regenerated": [],
            "sections": _sections_payload(storage, application_id),
            "review_gated": True,
        }

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
    return {
        "regenerated": regenerated,
        # Also hand back the normalized current section set so the panel can render
        # the refreshed drafts uniformly with the panel-mode path.
        "sections": _sections_payload(storage, application_id),
        "review_gated": True,
    }


@router.post("/{application_id}/edit-section")
def edit_section(
    application_id: str,
    body: EditSectionIn,
    storage=Depends(get_storage),
    material=Depends(get_material_service),
) -> dict:
    """Persist a human's inline edit to a section's content — review-gated (RUX-3 fix B.4).

    The human is the author here (not the LLM), so this is a literal content
    replacement via ``MaterialService.set_section_content``: the deterministic
    em-dash/banned-phrase post-filter still runs, the edit is stored UNAPPROVED (an
    edit is unreviewed), and the durable revision session is opened so the later
    view-before-approve gate is satisfied. Nothing is submitted.
    """
    from applicant.core.ids import GeneratedDocumentId, ResumeVariantId

    _require_app(storage, application_id)
    did = GeneratedDocumentId(body.section_id)
    if storage.documents.get(did) is None:
        # P1 fix: the app's linked résumé VARIANT now appears in /sections too, but a
        # variant is file-rendered (no plain-text ``content`` field) -- give an
        # honest, actionable 422 instead of a bare 404 when it lands here (Regenerate
        # is the equivalent action for a résumé; inline text edit isn't supported).
        if storage.resume_variants.get(ResumeVariantId(body.section_id)) is not None:
            raise HTTPException(
                status_code=422,
                detail="Résumé variants can't be inline-edited — use Regenerate instead.",
            )
        raise HTTPException(status_code=404, detail=f"no such section {body.section_id}")
    updated = material.set_section_content(did, body.content)
    return {
        "section": _serialize_section(storage, updated),
        "review_gated": True,
    }
