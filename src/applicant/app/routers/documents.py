"""Documents router (FR-RESUME-1/8, FR-ANSWER-1, FR-RESUME-9/10).

# STAGE B — owned by Phase 3.

Exposes the DocumentReview driving port: present the redline (add+subtract
highlights), run the interactive add/subtract/free-text revision loop, and
approve/decline. No submission until the material is approved (review gate,
FR-RESUME-8). The MaterialService is composed from the frozen container's
adapters (storage + llm + latex_tailor) so wiring stays in the composition root.
Gated behind the LLM-settings gate (FR-UI-5).
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse
from pydantic import BaseModel

from applicant.app.container import Container
from applicant.app.deps import (
    get_admin_query_service,
    get_container,  # CRIT-profile: container singleton for the banned-phrase list
    get_material_service,
    get_pending_actions_service,
    get_storage,
    require_llm_configured,
    require_tool_enabled,
)
from applicant.application.services.material_service import MaterialService
from applicant.core.errors import NotFound, ReviewRequired
from applicant.core.ids import GeneratedDocumentId, ResumeVariantId
from applicant.core.rules.jd_match import compute_jd_match  # product-gaps #23
from applicant.core.rules.truthfulness import BANNED_PHRASES  # CRIT-profile

router = APIRouter(
    prefix="/api/documents", tags=["documents"], dependencies=[Depends(require_llm_configured)]
)


def _material_service(container: Container) -> MaterialService:
    # CONC-REQ-1: prefer the PER-REQUEST material service (its storage is bound to a
    # request-scoped Session). Composed from the frozen container's adapters.
    if container.material_service is not None:
        return container.material_service
    return MaterialService(
        container.storage,
        container.llm,
        container.latex_tailor,
        embedding=container.embedding,
        docx_tailoring=container.docx_tailor,
        conversion_service=container.conversion_service,
        notifications=container.notification_service,
        pending_actions=container.pending_actions_service,
        learning=container.learning_service,
        advanced_learning=container.advanced_learning_service,
    )


class TurnIn(BaseModel):
    kind: str  # "add" | "subtract" | "free_text"
    instruction: str = ""
    true_source: str | None = None  # enables the fabrication guardrail on the turn


class CoverLetterIn(BaseModel):
    campaign_id: str
    application_id: str
    # Optional: derived server-side from the profile (base résumé + attribute cloud)
    # when blank, so the front-door can request one with just the application.
    true_source: str = ""
    jd_terms: list[str] = []
    # On-demand decision (FR-RESUME-10): per-campaign default + optional role override.
    campaign_default: bool = False
    role_requires: bool | None = None


class ScreeningAnswerIn(BaseModel):
    campaign_id: str
    application_id: str
    question: str
    true_source: str = ""  # derived server-side when blank (see CoverLetterIn)
    # None -> classify (factual vs essay vs sensitive); else force essay/factual.
    essay: bool | None = None
    # Explicit stored EEO answer, used ONLY for sensitive fields (never AI-guessed).
    explicit_answer: str | None = None


class ScreeningAnswerReuseIn(BaseModel):
    # Product-gaps backlog #20: reuse a previously-generated library answer for a
    # NEW application instead of regenerating fresh.
    campaign_id: str
    application_id: str
    question: str


class DeferredEssayIn(BaseModel):
    # #4: resolve a deferred essay screening question pre-fill recorded during the
    # FR-PREFILL-3 walk — generate + route the answer to review.
    campaign_id: str
    application_id: str
    true_source: str
    label: str = ""
    question: str | None = None
    selector: str | None = None
    url: str | None = None
    explicit_answer: str | None = None


class AggressivenessIn(BaseModel):
    # FR-RESUME-9 truthful-framing dial; the UI control ships grayed (FR-UI-2).
    aggressiveness: int = 20


# CRIT-profile: UI-editable banned-phrase ("no-AI-look") list (FR-RESUME-5).
class BannedPhrasesIn(BaseModel):
    phrases: list[str] = []
# CRIT-profile: end


class RedlineIn(BaseModel):
    variant_id: str
    base_source: str
    new_source: str
    # FR-RESUME-9 grayed aggressiveness control: accepted but not yet load-bearing.
    aggressiveness: int = 20


def _session_payload(session) -> dict:
    return {
        "session_id": session.id,
        "material_id": session.material_id,
        "status": session.status.value,
        "turns": [
            {"kind": t.kind, "instruction": t.instruction, "ai_response": t.ai_response}
            for t in session.turns
        ],
        "redline_state": session.redline_state,
    }


@router.get("/variants/{variant_id}/download")
def download_artifact(variant_id: str, material=Depends(get_material_service)) -> FileResponse:
    """Download the rendered PDF artifact for a resume variant (issue #178).

    Serves the compiled PDF when the real render engine was available and produced
    output. Returns 404 when the artifact does not exist (stub mode or compile
    failure).
    """

    # Check LaTeX artifact path first, then docx.
    artifact_dir = Path.cwd() / ".artifacts"
    candidates = [
        artifact_dir / "latex" / variant_id / "resume.pdf",
        artifact_dir / "docx" / f"{variant_id}.pdf",
        artifact_dir / "latex" / variant_id / "resume.tex",
    ]
    for p in candidates:
        if p.is_file():
            media_type = "application/pdf" if p.suffix == ".pdf" else "text/plain"
            return FileResponse(str(p), media_type=media_type, filename=p.name)

    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="Rendered artifact not found. Enable the real render engine (RESUME_RENDER=on) to produce PDF output.",
    )


@router.get("")
def index() -> dict:
    return {"surface": "documents", "phase": 3, "status": "live"}


@router.get("/applications/{application_id}")
def list_for_application(
    application_id: str, storage=Depends(get_storage)
) -> dict:
    """List generated docs for an application + whether the review gate is open."""
    docs = storage.documents.list_for_application(application_id)  # type: ignore[arg-type]
    return {
        "application_id": application_id,
        "items": [
            {
                "id": d.id,
                "type": d.type.value,
                "approved": d.approved,
                "content": d.content,
                # Advisory "What I drew on" transparency (FR-MIND-5/-11, FR-OBS-2):
                # which learned items shaped this draft. Empty list when none.
                "provenance": _provenance_payload(d.provenance),
            }
            for d in docs
        ],
        "all_approved": all(d.approved for d in docs) if docs else True,
    }


@router.get("/jd-match/{application_id}")
def jd_match(
    application_id: str,
    material=Depends(get_material_service),
    storage=Depends(get_storage),
) -> dict:
    """Résumé <-> job-posting keyword match explainer (product-gaps backlog #23).

    Pure, deterministic, extractive scoring (``core.rules.jd_match`` — no LLM, no
    fabrication risk): which of the posting's high-signal keywords already show up
    in the candidate's true résumé/profile text, and which are missing. A small,
    dedicated read-model rather than piggybacking on ``POST /redline`` — the
    redline endpoint only knows a variant's ``base_source``/``new_source`` strings
    (no application/posting context), while the JD match needs the APPLICATION's
    target posting, so a lookup keyed by ``application_id`` is the natural shape.

    ``resume_text`` is the same flattened true-attribute-cloud + base-résumé text
    ``MaterialService.true_attribute_text`` already treats as the candidate's
    ground truth elsewhere (voice corpus, fabrication checks) -- résumé variants
    themselves are stored as rendered LaTeX/docx files, not plain text, so this is
    the best available plain-text stand-in for "what's on the résumé".

    404 when the application does not exist. An application with no resolvable
    posting degrades to an all-zero result (never fabricates a score) rather than
    404ing, since the application itself is real.
    """
    try:
        app = storage.applications.get(application_id)  # type: ignore[arg-type]
    except Exception:
        app = None
    if app is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="No such application."
        )
    posting = None
    posting_id = getattr(app, "posting_id", None)
    if posting_id is not None:
        try:
            posting = storage.postings.get(posting_id)
        except Exception:
            posting = None
    posting_text = (getattr(posting, "description", "") or "") if posting else ""
    try:
        resume_text = material.true_attribute_text(app.campaign_id)
    except Exception:  # pragma: no cover - defensive; never break the read
        resume_text = ""
    result = compute_jd_match(resume_text, posting_text)
    return {"application_id": application_id, **result}


def _provenance_payload(provenance) -> list[dict]:
    """Serialize a material's advisory learned-item provenance for the review UI.

    Each entry is a plain ``{kind, label, ref}`` dict (FR-MIND-5/-11): ``kind`` is
    ``memory`` | ``playbook`` | ``recall``, ``label`` is the plain-language phrase the
    UI shows, ``ref`` is the underlying item id (memory line / playbook name / recall
    run-id). Descriptive only — never authorization.
    """
    return [
        {"kind": p.kind, "label": p.label, "ref": p.ref}
        for p in (provenance or ())
    ]


@router.post(
    "/redline",
    status_code=200,
    dependencies=[Depends(require_tool_enabled("resume_tailoring"))],
)
def redline(body: RedlineIn, material=Depends(get_material_service)) -> dict:
    """Render the add/subtract redline for the review surface (FR-RESUME-8)."""
    result = material.render_redline(
        body.variant_id, body.base_source, body.new_source  # type: ignore[arg-type]
    )
    return {
        "variant_id": result.variant_id,
        "additions": list(result.additions),
        "subtractions": list(result.subtractions),
        "rendered_html": result.rendered_html,
    }


@router.post(
    "/cover-letter",
    status_code=201,
    dependencies=[Depends(require_tool_enabled("cover_letter_generation"))],
)
def generate_cover_letter(body: CoverLetterIn, material=Depends(get_material_service)) -> dict:
    """Generate a cover letter ON DEMAND (FR-RESUME-10), routed to review.

    Returns ``{"generated": false}`` when the role does not warrant one.
    """
    doc = material.generate_cover_letter(
        body.campaign_id,  # type: ignore[arg-type]
        body.application_id,  # type: ignore[arg-type]
        body.true_source,
        body.jd_terms,
        campaign_default=body.campaign_default,
        role_requires=body.role_requires,
    )
    if doc is None:
        return {"generated": False, "reason": "role does not warrant a cover letter"}
    return {"generated": True, "id": doc.id, "type": doc.type.value, "approved": doc.approved}


@router.post(
    "/screening-answer",
    status_code=201,
    dependencies=[Depends(require_tool_enabled("screening_answer_generation"))],
)
def generate_screening_answer(
    body: ScreeningAnswerIn, material=Depends(get_material_service)
) -> dict:
    """Generate a screening answer (FR-ANSWER-1): factual vs essay vs sensitive."""
    doc = material.generate_screening_answer(
        body.campaign_id,  # type: ignore[arg-type]
        body.application_id,  # type: ignore[arg-type]
        body.question,
        body.true_source,
        essay=body.essay,
        explicit_answer=body.explicit_answer,
    )
    return {"id": doc.id, "type": doc.type.value, "approved": doc.approved, "content": doc.content}


@router.get(
    "/screening-answer-library/{campaign_id}",
    dependencies=[Depends(require_tool_enabled("screening_answer_generation"))],
)
def screening_answer_library(campaign_id: str, material=Depends(get_material_service)) -> dict:
    """The saved screening-answer library for a campaign (product-gaps #20).

    Screening answers are generated per-application (FR-ANSWER-1) through review,
    but common questions ("Why do you want to work here?", "Notice period?") get
    asked over and over. This surfaces the reusable answer bank a prior generation
    quietly built (see ``MaterialService.generate_screening_answer``'s
    ``_save_to_screening_library`` call) so the UI can browse it.
    """
    items = material.list_screening_answer_library(campaign_id)  # type: ignore[arg-type]
    return {"campaign_id": campaign_id, "items": items}


@router.post(
    "/screening-answer-library/reuse",
    status_code=201,
    dependencies=[Depends(require_tool_enabled("screening_answer_generation"))],
)
def reuse_screening_answer(
    body: ScreeningAnswerReuseIn, material=Depends(get_material_service)
) -> dict:
    """Reuse a library answer for a NEW application instead of regenerating it
    (product-gaps #20). ``found: false`` when no library entry matches the
    (normalized) question -- the caller falls back to ``/screening-answer``. A
    match is still routed through review like any other generated material; reuse
    only skips the LLM call, never the truthfulness/review gates.
    """
    doc = material.reuse_screening_answer(
        body.campaign_id,  # type: ignore[arg-type]
        body.application_id,  # type: ignore[arg-type]
        body.question,
    )
    if doc is None:
        return {"found": False}
    return {
        "found": True,
        "id": doc.id,
        "type": doc.type.value,
        "approved": doc.approved,
        "content": doc.content,
    }


@router.get(
    "/interview-prep/{campaign_id}/{application_id}",
    dependencies=[Depends(require_tool_enabled("screening_answer_generation"))],
)
def interview_prep(
    campaign_id: str, application_id: str, material=Depends(get_material_service)
) -> dict:
    """A plain-language interview-prep brief (product-gaps #30).

    Gated on the application having reached the ``interview_invited`` outcome
    signal; returns ``generated: false`` (never a fabricated brief) when it
    hasn't. Reuses the SAME company-research channel cover-letter generation
    already draws on, plus the posting's own stated requirements.
    """
    brief = material.generate_interview_prep(
        campaign_id, application_id  # type: ignore[arg-type]
    )
    if brief is None:
        return {"generated": False}
    return {"generated": True, **brief}


@router.post(
    "/deferred-essay",
    status_code=201,
    dependencies=[Depends(require_tool_enabled("screening_answer_generation"))],
)
def generate_deferred_essay(
    body: DeferredEssayIn,
    material=Depends(get_material_service),
    pending_actions=Depends(get_pending_actions_service),
) -> dict:
    """Generate + review the answer for a DEFERRED essay screening question (#4).

    Phase 2 pre-fill records essay screening questions it must not auto-answer as
    ``agent_question`` pending actions; this endpoint resolves one by generating the
    answer (classified, filtered, fabrication-gated) and routing it to review, and
    clears the originating pending action so the portal item does not linger.
    """
    deferred = {
        "label": body.label or body.question or "",
        "question": body.question,
        "selector": body.selector,
        "url": body.url,
        "explicit_answer": body.explicit_answer,
    }
    doc = material.generate_for_deferred_question(
        body.campaign_id,  # type: ignore[arg-type]
        body.application_id,  # type: ignore[arg-type]
        deferred,
        body.true_source,
    )
    # Resolve the originating agent_question pending action by its dedup key (#4/#7).
    if body.selector:
        try:
            pending_actions.resolve_by_dedup(
                body.campaign_id,  # type: ignore[arg-type]
                f"agent_question:{body.application_id}:{body.selector}",
            )
        except Exception:  # pragma: no cover - defensive
            pass
    return {"id": doc.id, "type": doc.type.value, "approved": doc.approved, "content": doc.content}


@router.post("/aggressiveness", status_code=200)
def set_aggressiveness(body: AggressivenessIn, material=Depends(get_material_service)) -> dict:
    """Set the truthful-framing dial (FR-RESUME-9). Live since #187."""
    value = material.set_aggressiveness(body.aggressiveness)
    return {"aggressiveness": value, "dormant_ui": False}


# CRIT-profile: banned-phrase ("no-AI-look") list editor (FR-RESUME-5).
# The list supplements the curated core seed and is stripped from every generated
# artifact before review. It is held on the CONTAINER-SINGLETON material service so
# an edit persists in-process across requests (the per-request service is a fresh,
# storage-bound instance and would not retain the list). ``seed_phrases`` is the
# read-only curated baseline so the UI can show "always removed" vs "your additions".
@router.get("/banned-phrases", status_code=200)
def get_banned_phrases(container: Container = Depends(get_container)) -> dict:
    material = container.material_service
    custom = list(material.banned_phrases) if material is not None else []
    return {"phrases": custom, "seed_phrases": list(BANNED_PHRASES)}


@router.post("/banned-phrases", status_code=200)
def set_banned_phrases(
    body: BannedPhrasesIn, container: Container = Depends(get_container)
) -> dict:
    material = container.material_service
    if material is not None:
        material.set_banned_phrases(body.phrases)
        custom = list(material.banned_phrases)
    else:
        custom = []
    return {"phrases": custom, "seed_phrases": list(BANNED_PHRASES)}
# CRIT-profile: end


@router.get("/variants/{campaign_id}")
def list_variants(
    campaign_id: str,
    admin_query=Depends(get_admin_query_service),
    material=Depends(get_material_service),
    storage=Depends(get_storage),
) -> dict:
    """Owner-scoped résumé-variant library: lineage / fit scores / approval state
    (FR-RESUME-6, FR-UI-6).

    Reuses the same read-model as the debug surface, but reachable from the
    user-facing document library (not admin-gated) so the variant library is a real
    user surface, not an operator-only view.

    The read-model already carries a raw ``lineage_depth`` count and the immediate
    ``parent_id``, but neither is human-readable — a user can't see "this variant was
    tailored from that one, which was tailored from the original base résumé" (dark-
    engine audit item 50). Attach the actual ancestor chain, root-first, using
    ``MaterialService.lineage`` (which already walks ``parent_id`` to the root) so the
    front door can render a readable breadcrumb without re-implementing the walk.
    """
    variants = admin_query.variant_library(campaign_id)  # type: ignore[arg-type]
    for row in variants:
        variant = storage.resume_variants.get(ResumeVariantId(row["variant_id"]))
        if variant is None:
            row["lineage"] = []
            continue
        # ``lineage`` is nearest-first (self, parent, grandparent, ... root);
        # reverse to root-first so the breadcrumb reads left-to-right as history.
        chain = list(reversed(material.lineage(variant)))
        row["lineage"] = [
            {
                "variant_id": str(v.id),
                "is_root": v.is_root,
                "targeted_jd_signature": v.targeted_jd_signature,
                "approved": v.approved,
            }
            for v in chain
        ]
    return {"campaign_id": campaign_id, "variants": variants}


@router.post("/{document_id}/review", status_code=201)
def open_review(document_id: str, material=Depends(get_material_service)) -> dict:
    """Open the interactive review session for a document (FR-RESUME-8)."""
    session = material.open_revision(GeneratedDocumentId(document_id))
    return _session_payload(session)


@router.post("/{document_id}/turn", status_code=201)
def submit_turn(document_id: str, body: TurnIn, material=Depends(get_material_service)) -> dict:
    """Apply an add/subtract/free-text revision turn (FR-RESUME-8)."""
    try:
        session = material.apply_turn(
            GeneratedDocumentId(document_id),
            body.kind,
            body.instruction,
            true_source=body.true_source,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _session_payload(session)


@router.post("/{document_id}/approve", status_code=201)
def approve(document_id: str, material=Depends(get_material_service)) -> dict:
    """Approve the material, passing the review gate (FR-RESUME-8, FR-NOTIF-4).

    409 when the redline review was never opened ("approve only after viewing");
    404 when the document does not exist.
    """
    try:
        doc = material.approve(GeneratedDocumentId(document_id))
    except NotFound as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ReviewRequired as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return {"id": doc.id, "type": doc.type.value, "approved": doc.approved}


@router.post("/variants/{variant_id}/approve", status_code=201)
def approve_variant(variant_id: str, material=Depends(get_material_service)) -> dict:
    """Approve a GENERATED resume variant through the review gate (#1, FR-RESUME-1/6/8).

    A generated variant routed to review (its material_review pending action + ping)
    is approved here, mirroring document approval. Approval clears the variant's
    pending action + ping and lets the parked pipeline advance past MATERIAL_REVIEW.
    """
    try:
        variant = material.approve_variant(ResumeVariantId(variant_id))
    except NotFound as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return {
        "id": variant.id,
        "type": "resume_variant",
        "approved": variant.approved,
        "campaign_id": variant.campaign_id,
    }


@router.post("/variants/{variant_id}/promote", status_code=201)
def promote_variant(
    variant_id: str, material=Depends(get_material_service), storage=Depends(get_storage)
) -> dict:
    """Promote a résumé variant to be the new base résumé future tailoring forks
    from, instead of the user's original base résumé (dark-engine audit item 33;
    ``MaterialService.promote_to_base_resume``, #293).

    Clears the variant's ``parent_id`` (it becomes the lineage root) and marks it
    approved. Idempotent: promoting an already-promoted variant is a no-op.
    404 when the variant does not exist.
    """
    variant = storage.resume_variants.get(ResumeVariantId(variant_id))
    if variant is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"no such variant {variant_id}"
        )
    promoted = material.promote_to_base_resume(variant)
    return {
        "id": promoted.id,
        "type": "resume_variant",
        "approved": promoted.approved,
        "campaign_id": promoted.campaign_id,
        "parent_id": promoted.parent_id,
    }


@router.post("/{document_id}/decline", status_code=201)
def decline(document_id: str, material=Depends(get_material_service)) -> dict:
    """Decline the material (stays unapproved, blocks submission)."""
    doc = material.decline(GeneratedDocumentId(document_id))
    return {"id": doc.id, "type": doc.type.value, "approved": doc.approved}


@router.post("/applications/{application_id}/ensure-submittable")
def ensure_submittable(application_id: str, material=Depends(get_material_service)) -> dict:
    """Enforce the review gate before submission (FR-RESUME-8). 409 if unapproved."""
    try:
        material.ensure_application_submittable(application_id)  # type: ignore[arg-type]
    except ReviewRequired as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return {"application_id": application_id, "submittable": True}
