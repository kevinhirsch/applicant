"""Concrete SQLAlchemy repositories implementing the storage port protocols.

Each repository maps between the pure-core entities and the ORM models. The
``SqlAlchemyStorage`` aggregates the repositories and provides the unit-of-work
boundary (``commit``/``rollback``) required by ``StoragePort``.
"""

from __future__ import annotations

from datetime import date, datetime, time

from sqlalchemy import select
from sqlalchemy.orm import Session

from applicant.adapters.storage import models as m
from applicant.core.entities.agent_run import AgentRun
from applicant.core.entities.application import Application
from applicant.core.entities.application_screenshot import ApplicationScreenshot
from applicant.core.entities.attribute import Attribute
from applicant.core.entities.follow_up import FollowUp, FollowUpStatus, FollowUpTemplate
from applicant.core.entities.ghosting_signal import GhostingSignal
from applicant.core.entities.portfolio_attachment import PortfolioAttachment, AttachmentType
from applicant.core.entities.rejection_signal import RejectionSignal, RejectionSource
from applicant.core.entities.submission_snapshot import SubmissionSnapshot
from applicant.core.entities.campaign import Campaign, RunMode
from applicant.core.entities.decision import Decision, DecisionType
from applicant.core.entities.detection_event import DetectionEvent
from applicant.core.entities.discovery_source import DiscoverySource
from applicant.core.entities.field_mapping import FieldMapping
from applicant.core.entities.generated_document import (
    DocumentType,
    GeneratedDocument,
    LearnedProvenance,
)
from applicant.core.entities.job_posting import JobPosting
from applicant.core.entities.onboarding_profile import OnboardingProfile
from applicant.core.entities.outcome_event import OutcomeEvent, OutcomeSource
from applicant.core.entities.pending_action import PendingAction
from applicant.core.entities.resume_variant import ResumeVariant
from applicant.core.entities.revision_session import (
    RevisionSession,
    RevisionStatus,
    RevisionTurn,
)
from applicant.core.ids import (
    FollowUpId,
    PortfolioAttachmentId,
    RejectionSignalId,
    SubmissionSnapshotId,
    AgentRunId,
    ApplicationId,
    AttributeId,
    CampaignId,
    DetectionEventId,
    DiscoverySourceId,
    FieldMappingId,
    GeneratedDocumentId,
    JobPostingId,
    OnboardingProfileId,
    PendingActionId,
    ResumeVariantId,
    RevisionSessionId,
    ScreenshotId,
)
from applicant.core.state_machine import ApplicationState

#: Outcome event types that mean the application has reached a terminal/submitted
#: state. Used by ``exists_terminal_for_application`` to make submission idempotent
#: (a second submit must not re-fire if a terminal outcome already exists).
TERMINAL_OUTCOME_TYPES: frozenset[str] = frozenset({"submitted", "converted"})

# --- mapping helpers -------------------------------------------------------


def _campaign_to_entity(row: m.CampaignModel) -> Campaign:
    return Campaign(
        id=CampaignId(row.id),
        name=row.name,
        run_mode=RunMode(row.run_mode),
        throughput_target=row.throughput_target,
        exploration_budget=row.exploration_budget,
        active=row.active,
        criteria=dict(row.criteria or {}),
        schedule=dict(row.schedule or {}),
        learning_state=dict(row.learning_state or {}),
    )


def _attr_to_entity(row: m.AttributeModel) -> Attribute:
    return Attribute(
        id=AttributeId(row.id),
        campaign_id=CampaignId(row.campaign_id),
        name=row.name,
        value=row.value,
        aliases=tuple(row.aliases or ()),
        is_integral=row.is_integral,
        is_sensitive=row.is_sensitive,
    )


def _posting_to_entity(row: m.JobPostingModel) -> JobPosting:
    return JobPosting(
        id=JobPostingId(row.id),
        campaign_id=CampaignId(row.campaign_id),
        title=row.title,
        company=row.company,
        source_url=row.source_url,
        location=row.location,
        work_mode=row.work_mode,
        salary=row.salary,
        description=row.description,
        source_key=row.source_key,
        viability_score=row.viability_score,
        rationale=dict(row.rationale or {}),
    )


def _application_to_entity(row: m.ApplicationModel) -> Application:
    return Application(
        id=ApplicationId(row.id),
        campaign_id=CampaignId(row.campaign_id),
        posting_id=JobPostingId(row.posting_id) if row.posting_id else JobPostingId(""),
        status=ApplicationState(row.status),
        role_name=row.role_name,
        job_title=row.job_title,
        work_mode=row.work_mode,
        root_url=row.root_url,
        resume_variant_id=(ResumeVariantId(row.resume_variant_id) if row.resume_variant_id else None),
        sandbox_session_url=row.sandbox_session_url,
        attributes_used=dict(row.attributes_used or {}),
    )


def _variant_to_entity(row: m.ResumeVariantModel) -> ResumeVariant:
    return ResumeVariant(
        id=ResumeVariantId(row.id),
        campaign_id=CampaignId(row.campaign_id),
        storage_path=row.storage_path,
        parent_id=ResumeVariantId(row.parent_id) if row.parent_id else None,
        targeted_jd_signature=row.targeted_jd_signature,
        approved=row.approved,
        fit_scores=dict(row.fit_scores or {}),
    )


def _document_to_entity(row: m.GeneratedMaterialModel) -> GeneratedDocument:
    return GeneratedDocument(
        id=GeneratedDocumentId(row.id),
        campaign_id=CampaignId(row.campaign_id),
        application_id=ApplicationId(row.application_id) if row.application_id else ApplicationId(""),
        type=DocumentType(row.type),
        content=row.content,
        storage_path=row.storage_path,
        approved=row.approved,
        provenance=_provenance_from_rows(getattr(row, "provenance", None)),
    )


def _provenance_from_rows(rows) -> tuple[LearnedProvenance, ...]:
    """Rehydrate the advisory provenance list from its stored JSON (FR-MIND-5)."""
    if not rows:
        return ()
    out: list[LearnedProvenance] = []
    for r in rows:
        if isinstance(r, dict):
            out.append(
                LearnedProvenance(
                    kind=str(r.get("kind", "")),
                    label=str(r.get("label", "")),
                    ref=str(r.get("ref", "")),
                )
            )
    return tuple(out)


def _provenance_to_rows(items) -> list[dict]:
    """Flatten the advisory provenance list to JSON-safe rows for storage."""
    return [
        {"kind": p.kind, "label": p.label, "ref": p.ref}
        for p in (items or ())
    ]


def _revision_to_entity(row: m.RevisionSessionModel) -> RevisionSession:
    return RevisionSession(
        id=RevisionSessionId(row.id),
        material_id=GeneratedDocumentId(row.material_id),
        status=RevisionStatus(row.status),
        turns=tuple(
            RevisionTurn(
                kind=t.get("kind", ""),
                instruction=t.get("instruction", ""),
                ai_response=t.get("ai_response", ""),
            )
            for t in (row.turns or [])
        ),
        redline_state=dict(row.redline_state or {}),
    )


def _decision_to_entity(row: m.DecisionModel) -> Decision:
    return Decision(
        id=row.id,
        application_id=ApplicationId(row.application_id),
        type=DecisionType(row.type),
        feedback_text=row.feedback_text,
        criteria_delta=dict(row.criteria_delta or {}),
    )


def _outcome_to_entity(row: m.OutcomeEventModel) -> OutcomeEvent:
    return OutcomeEvent(
        id=row.id,
        application_id=ApplicationId(row.application_id),
        type=row.type,
        source=OutcomeSource(row.source),
    )


def _screenshot_to_entity(row: m.ApplicationScreenshotModel) -> ApplicationScreenshot:
    return ApplicationScreenshot(
        id=ScreenshotId(row.id),
        application_id=ApplicationId(row.application_id),
        page_ref=row.page_ref,
        page_url=row.page_url or "",
    )


def _pending_to_entity(row: m.PendingActionModel) -> PendingAction:
    return PendingAction(
        id=PendingActionId(row.id),
        campaign_id=CampaignId(row.campaign_id),
        kind=row.kind,
        title=row.title,
        application_id=ApplicationId(row.application_id) if row.application_id else None,
        payload=dict(row.payload or {}),
        resolved=row.resolved,
        created_at=row.created_at,
    )


def _field_mapping_to_entity(row: m.FieldMappingModel) -> FieldMapping:
    return FieldMapping(
        id=FieldMappingId(row.id),
        site_key=row.site_key,
        field_selector=row.field_selector,
        campaign_id=CampaignId(row.campaign_id) if row.campaign_id else None,
        attribute_id=AttributeId(row.attribute_id) if row.attribute_id else None,
        metadata=dict(row.mapping_metadata or {}),
    )


def _discovery_source_to_entity(row: m.DiscoverySourceModel) -> DiscoverySource:
    return DiscoverySource(
        id=DiscoverySourceId(row.id),
        campaign_id=CampaignId(row.campaign_id),
        source_key=row.source_key,
        enabled=row.enabled,
        yield_stats=dict(row.yield_stats or {}),
    )


def _agent_run_to_entity(row: m.AgentRunModel) -> AgentRun:
    blob = dict(row.intent_sentence or {})
    kwargs = dict(
        id=AgentRunId(row.id),
        campaign_id=CampaignId(row.campaign_id),
        intent_sentence=blob.get("sentence", ""),
        run_mode=RunMode(blob.get("run_mode", RunMode.CONTINUOUS.value)),
        throughput_target=int(blob.get("throughput_target", 15)),
        stats=dict(blob.get("stats", {})),
        timestamp=row.timestamp,
    )
    # Preserve the monotonic insertion ``seq`` for deterministic tie-break on equal
    # timestamps (FR-AGENT-7); fall back to the entity default when absent.
    if "seq" in blob:
        kwargs["seq"] = int(blob["seq"])
    return AgentRun(**kwargs)


def _detection_to_entity(row: m.DetectionEventModel) -> DetectionEvent:
    return DetectionEvent(
        id=DetectionEventId(row.id),
        application_id=ApplicationId(row.application_id),
        signal_type=row.signal_type,
        detail=dict(row.signal_detail or {}),
        timestamp=row.timestamp,
    )


def _onboarding_to_entity(row: m.OnboardingProfileModel) -> OnboardingProfile:
    return OnboardingProfile(
        id=OnboardingProfileId(row.id),
        campaign_id=CampaignId(row.campaign_id),
        completion_flag=row.completion_flag,
        wizard_state=dict(row.wizard_state or {}),
        intake=dict(row.intake or {}),
    )


# --- repositories ----------------------------------------------------------


class CampaignRepo:
    def __init__(self, session: Session) -> None:
        self._s = session

    def add(self, campaign: Campaign) -> None:
        self._s.merge(
            m.CampaignModel(
                id=campaign.id,
                name=campaign.name,
                run_mode=campaign.run_mode.value,
                throughput_target=campaign.throughput_target,
                exploration_budget=campaign.exploration_budget,
                active=campaign.active,
                criteria=campaign.criteria,
                schedule=campaign.schedule,
                learning_state=campaign.learning_state,
            )
        )

    def get(self, campaign_id: CampaignId) -> Campaign | None:
        row = self._s.get(m.CampaignModel, campaign_id)
        return _campaign_to_entity(row) if row else None

    def list(self) -> list[Campaign]:
        rows = self._s.scalars(select(m.CampaignModel)).all()
        return [_campaign_to_entity(r) for r in rows]


class AttributeRepo:
    def __init__(self, session: Session) -> None:
        self._s = session

    def add(self, attribute: Attribute) -> None:
        self._s.merge(
            m.AttributeModel(
                id=attribute.id,
                campaign_id=attribute.campaign_id,
                name=attribute.name,
                value=attribute.value,
                is_integral=attribute.is_integral,
                is_sensitive=attribute.is_sensitive,
                aliases=list(attribute.aliases),
            )
        )

    def get(self, attribute_id: AttributeId) -> Attribute | None:
        row = self._s.get(m.AttributeModel, attribute_id)
        return _attr_to_entity(row) if row else None

    def list_for_campaign(self, campaign_id: CampaignId) -> list[Attribute]:
        rows = self._s.scalars(
            select(m.AttributeModel).where(m.AttributeModel.campaign_id == campaign_id)
        ).all()
        return [_attr_to_entity(r) for r in rows]

    def delete(self, attribute_id: AttributeId) -> None:  # CRIT-profile: FR-ATTR-3
        row = self._s.get(m.AttributeModel, attribute_id)
        if row is not None:
            self._s.delete(row)


class JobPostingRepo:
    def __init__(self, session: Session) -> None:
        self._s = session

    def add(self, posting: JobPosting) -> None:
        self._s.merge(
            m.JobPostingModel(
                id=posting.id,
                campaign_id=posting.campaign_id,
                title=posting.title,
                company=posting.company,
                location=posting.location,
                work_mode=posting.work_mode,
                salary=posting.salary,
                source_url=posting.source_url,
                source_key=posting.source_key,
                description=posting.description,
                viability_score=posting.viability_score,
                rationale=posting.rationale,
            )
        )

    def get(self, posting_id: JobPostingId) -> JobPosting | None:
        row = self._s.get(m.JobPostingModel, posting_id)
        return _posting_to_entity(row) if row else None

    def list_for_campaign(self, campaign_id: CampaignId) -> list[JobPosting]:
        rows = self._s.scalars(
            select(m.JobPostingModel)
            .where(m.JobPostingModel.campaign_id == campaign_id)
            .order_by(m.JobPostingModel.id)
        ).all()
        return [_posting_to_entity(r) for r in rows]

    def list_unscored_for_campaign(self, campaign_id: CampaignId) -> list[JobPosting]:
        rows = self._s.scalars(
            select(m.JobPostingModel)
            .where(m.JobPostingModel.campaign_id == campaign_id)
            .where(m.JobPostingModel.viability_score.is_(None))
            .order_by(m.JobPostingModel.id)
        ).all()
        return [_posting_to_entity(r) for r in rows]


class ApplicationRepo:
    def __init__(self, session: Session) -> None:
        self._s = session

    def _to_model(self, app: Application) -> m.ApplicationModel:
        return m.ApplicationModel(
            id=app.id,
            campaign_id=app.campaign_id,
            posting_id=app.posting_id or None,
            role_name=app.role_name,
            job_title=app.job_title,
            work_mode=app.work_mode,
            root_url=app.root_url,
            resume_variant_id=app.resume_variant_id,
            status=app.status.value,
            sandbox_session_url=app.sandbox_session_url,
            attributes_used=app.attributes_used,
        )

    def add(self, application: Application) -> None:
        self._s.merge(self._to_model(application))

    def update(self, application: Application) -> None:
        self._s.merge(self._to_model(application))

    def get(self, application_id: ApplicationId) -> Application | None:
        row = self._s.get(m.ApplicationModel, application_id)
        return _application_to_entity(row) if row else None

    def list_for_campaign(self, campaign_id: CampaignId) -> list[Application]:
        rows = self._s.scalars(
            select(m.ApplicationModel)
            .where(m.ApplicationModel.campaign_id == campaign_id)
            .order_by(m.ApplicationModel.id)
        ).all()
        return [_application_to_entity(r) for r in rows]

    def get_by_posting(
        self, campaign_id: CampaignId, posting_id: JobPostingId
    ) -> Application | None:
        row = self._s.scalars(
            select(m.ApplicationModel)
            .where(m.ApplicationModel.campaign_id == campaign_id)
            .where(m.ApplicationModel.posting_id == posting_id)
            .order_by(m.ApplicationModel.id)
        ).first()
        return _application_to_entity(row) if row else None

    def list_by_status(
        self, campaign_id: CampaignId, statuses: tuple[ApplicationState, ...]
    ) -> list[Application]:
        if not statuses:
            return []
        rows = self._s.scalars(
            select(m.ApplicationModel)
            .where(m.ApplicationModel.campaign_id == campaign_id)
            .where(m.ApplicationModel.status.in_([s.value for s in statuses]))
            .order_by(m.ApplicationModel.id)
        ).all()
        return [_application_to_entity(r) for r in rows]


class ResumeVariantRepo:
    def __init__(self, session: Session) -> None:
        self._s = session

    def add(self, variant: ResumeVariant) -> None:
        self._s.merge(
            m.ResumeVariantModel(
                id=variant.id,
                campaign_id=variant.campaign_id,
                storage_path=variant.storage_path,
                parent_id=variant.parent_id,
                targeted_jd_signature=variant.targeted_jd_signature,
                approved=variant.approved,
                fit_scores=variant.fit_scores,
            )
        )

    def get(self, variant_id: ResumeVariantId) -> ResumeVariant | None:
        row = self._s.get(m.ResumeVariantModel, variant_id)
        return _variant_to_entity(row) if row else None

    def list_for_campaign(self, campaign_id: CampaignId) -> list[ResumeVariant]:
        rows = self._s.scalars(
            select(m.ResumeVariantModel).where(m.ResumeVariantModel.campaign_id == campaign_id)
        ).all()
        return [_variant_to_entity(r) for r in rows]


class GeneratedDocumentRepo:
    def __init__(self, session: Session) -> None:
        self._s = session

    def add(self, document: GeneratedDocument) -> None:
        self._s.merge(
            m.GeneratedMaterialModel(
                id=document.id,
                campaign_id=document.campaign_id,
                application_id=document.application_id or None,
                type=document.type.value,
                content=document.content,
                storage_path=document.storage_path,
                approved=document.approved,
                provenance=_provenance_to_rows(document.provenance),
            )
        )

    def get(self, document_id: GeneratedDocumentId) -> GeneratedDocument | None:
        row = self._s.get(m.GeneratedMaterialModel, document_id)
        return _document_to_entity(row) if row else None

    def list_for_application(self, application_id: ApplicationId) -> list[GeneratedDocument]:
        rows = self._s.scalars(
            select(m.GeneratedMaterialModel).where(
                m.GeneratedMaterialModel.application_id == application_id
            )
        ).all()
        return [_document_to_entity(r) for r in rows]

    def list_for_campaign(self, campaign_id: CampaignId) -> list[GeneratedDocument]:
        """All generated materials for a campaign (#363 purge verification parity)."""
        rows = self._s.scalars(
            select(m.GeneratedMaterialModel).where(
                m.GeneratedMaterialModel.campaign_id == campaign_id
            )
        ).all()
        return [_document_to_entity(r) for r in rows]


class RevisionSessionRepo:
    """Durable interactive redline sessions (FR-RESUME-8): resumable across restarts."""

    def __init__(self, session: Session) -> None:
        self._s = session

    def add(self, session: RevisionSession) -> None:
        self._s.merge(
            m.RevisionSessionModel(
                id=session.id,
                material_id=session.material_id,
                status=session.status.value,
                redline_state=session.redline_state,
                turns=[
                    {"kind": t.kind, "instruction": t.instruction, "ai_response": t.ai_response}
                    for t in session.turns
                ],
            )
        )

    def get(self, session_id: RevisionSessionId) -> RevisionSession | None:
        row = self._s.get(m.RevisionSessionModel, session_id)
        return _revision_to_entity(row) if row else None

    def get_for_material(self, material_id: GeneratedDocumentId) -> RevisionSession | None:
        row = self._s.scalars(
            select(m.RevisionSessionModel).where(
                m.RevisionSessionModel.material_id == material_id
            )
        ).first()
        return _revision_to_entity(row) if row else None


class DecisionRepo:
    def __init__(self, session: Session) -> None:
        self._s = session

    def add(self, decision: Decision) -> None:
        self._s.merge(
            m.DecisionModel(
                id=decision.id,
                application_id=decision.application_id,
                type=decision.type.value,
                feedback_text=decision.feedback_text,
                criteria_delta=decision.criteria_delta,
            )
        )

    def list_for_application(self, application_id: ApplicationId) -> list[Decision]:
        rows = self._s.scalars(
            select(m.DecisionModel)
            .where(m.DecisionModel.application_id == application_id)
            .order_by(m.DecisionModel.id)
        ).all()
        return [_decision_to_entity(r) for r in rows]

    def list_approved_postings_for_campaign(
        self, campaign_id: CampaignId
    ) -> list[JobPostingId]:
        """Posting ids with an APPROVED decision (distinct, ordered).

        A decision's ``application_id`` may be either a real application id (resolve to
        its ``posting_id`` via the join) OR a posting id directly — the digest UI
        approves a digest ROW, whose id is the posting id, before any application row
        exists (see DigestService._campaign_for_decision). Both legs are honored so a
        freshly approved digest item is found.
        """
        # Leg 1: decision references a real application -> use its posting_id.
        via_app = (
            select(m.ApplicationModel.posting_id.label("posting_id"))
            .join(
                m.DecisionModel,
                m.DecisionModel.application_id == m.ApplicationModel.id,
            )
            .where(m.ApplicationModel.campaign_id == campaign_id)
            .where(m.DecisionModel.type == DecisionType.APPROVE.value)
            .where(m.ApplicationModel.posting_id.is_not(None))
        )
        # Leg 2: decision references the posting id directly (no application yet).
        via_posting = (
            select(m.JobPostingModel.id.label("posting_id"))
            .join(
                m.DecisionModel,
                m.DecisionModel.application_id == m.JobPostingModel.id,
            )
            .where(m.JobPostingModel.campaign_id == campaign_id)
            .where(m.DecisionModel.type == DecisionType.APPROVE.value)
        )
        union = via_app.union(via_posting).subquery()
        rows = self._s.execute(
            select(union.c.posting_id).distinct().order_by(union.c.posting_id)
        ).all()
        return [JobPostingId(r[0]) for r in rows]


class OutcomeEventRepo:
    def __init__(self, session: Session) -> None:
        self._s = session

    def add(self, event: OutcomeEvent) -> None:
        self._s.merge(
            m.OutcomeEventModel(
                id=event.id,
                application_id=event.application_id,
                type=event.type,
                source=event.source.value,
            )
        )

    def list_for_application(self, application_id: ApplicationId) -> list[OutcomeEvent]:
        rows = self._s.scalars(
            select(m.OutcomeEventModel)
            .where(m.OutcomeEventModel.application_id == application_id)
            .order_by(m.OutcomeEventModel.created_at, m.OutcomeEventModel.id)
        ).all()
        return [_outcome_to_entity(r) for r in rows]

    def list_for_campaign(
        self,
        campaign_id: CampaignId,
        *,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[OutcomeEvent]:
        """All outcome events for a campaign (join through applications).

        Campaign-scoped (FR-CRIT-4): outcomes must never bleed across campaigns, so
        learning-depth queries filter by the owning application's campaign. ``limit``/
        ``offset`` bound the scan for paginated admin loads (default: unbounded).
        """
        stmt = (
            select(m.OutcomeEventModel)
            .join(
                m.ApplicationModel,
                m.OutcomeEventModel.application_id == m.ApplicationModel.id,
            )
            .where(m.ApplicationModel.campaign_id == campaign_id)
            .order_by(m.OutcomeEventModel.created_at, m.OutcomeEventModel.id)
        )
        if offset:
            stmt = stmt.offset(offset)
        if limit is not None:
            stmt = stmt.limit(limit)
        rows = self._s.scalars(stmt).all()
        return [_outcome_to_entity(r) for r in rows]

    def exists_terminal_for_application(self, application_id: ApplicationId) -> bool:
        """True if a terminal (submitted/converted) outcome already exists."""
        row = self._s.scalars(
            select(m.OutcomeEventModel.id)
            .where(m.OutcomeEventModel.application_id == application_id)
            .where(m.OutcomeEventModel.type.in_(tuple(TERMINAL_OUTCOME_TYPES)))
            .limit(1)
        ).first()
        return row is not None


class ApplicationScreenshotRepo:
    def __init__(self, session: Session) -> None:
        self._s = session

    def add(self, shot: ApplicationScreenshot) -> None:
        self._s.merge(
            m.ApplicationScreenshotModel(
                id=shot.id,
                application_id=shot.application_id,
                page_ref=shot.page_ref,
                page_url=shot.page_url,
            )
        )

    def list_for_application(self, application_id: ApplicationId) -> list[ApplicationScreenshot]:
        rows = self._s.scalars(
            select(m.ApplicationScreenshotModel)
            .where(m.ApplicationScreenshotModel.application_id == application_id)
            .order_by(m.ApplicationScreenshotModel.captured_at, m.ApplicationScreenshotModel.id)
        ).all()
        return [_screenshot_to_entity(r) for r in rows]

    def list_for_campaign(
        self,
        campaign_id: CampaignId,
        *,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[ApplicationScreenshot]:
        """All screenshots whose application belongs to ``campaign_id`` (batch load).

        Kills the admin N+1 (one query instead of per-application fetches). ``limit``/
        ``offset`` bound the scan; default behavior is unbounded.
        """
        stmt = (
            select(m.ApplicationScreenshotModel)
            .join(
                m.ApplicationModel,
                m.ApplicationScreenshotModel.application_id == m.ApplicationModel.id,
            )
            .where(m.ApplicationModel.campaign_id == campaign_id)
            .order_by(
                m.ApplicationScreenshotModel.captured_at, m.ApplicationScreenshotModel.id
            )
        )
        if offset:
            stmt = stmt.offset(offset)
        if limit is not None:
            stmt = stmt.limit(limit)
        rows = self._s.scalars(stmt).all()
        return [_screenshot_to_entity(r) for r in rows]


class PendingActionRepo:
    def __init__(self, session: Session) -> None:
        self._s = session

    def add(self, action: PendingAction) -> None:
        self._s.merge(
            m.PendingActionModel(
                id=action.id,
                campaign_id=action.campaign_id,
                application_id=action.application_id,
                kind=action.kind,
                title=action.title,
                # dedup_key is promoted to a real indexed column; it still lives in
                # ``payload`` for callers, but we mirror it here for direct lookup.
                dedup_key=(action.payload or {}).get("dedup_key"),
                payload=action.payload,
                resolved=action.resolved,
                created_at=action.created_at,
            )
        )

    def get(self, action_id: PendingActionId) -> PendingAction | None:
        row = self._s.get(m.PendingActionModel, action_id)
        return _pending_to_entity(row) if row else None

    def list_open(self, campaign_id: CampaignId) -> list[PendingAction]:
        rows = self._s.scalars(
            select(m.PendingActionModel)
            .where(m.PendingActionModel.campaign_id == campaign_id)
            .where(m.PendingActionModel.resolved.is_(False))
            .order_by(m.PendingActionModel.created_at, m.PendingActionModel.id)
        ).all()
        return [_pending_to_entity(r) for r in rows]

    def find_open_by_dedup(
        self, campaign_id: CampaignId, dedup_key: str
    ) -> PendingAction | None:
        """Direct (campaign_id, dedup_key) indexed lookup — no payload scan."""
        row = self._s.scalars(
            select(m.PendingActionModel)
            .where(m.PendingActionModel.campaign_id == campaign_id)
            .where(m.PendingActionModel.dedup_key == dedup_key)
            .where(m.PendingActionModel.resolved.is_(False))
            .order_by(m.PendingActionModel.created_at, m.PendingActionModel.id)
        ).first()
        return _pending_to_entity(row) if row else None

    def resolve(self, action_id: PendingActionId) -> None:
        row = self._s.get(m.PendingActionModel, action_id)
        if row:
            row.resolved = True


class FieldMappingRepo:
    def __init__(self, session: Session) -> None:
        self._s = session

    def add(self, mapping: FieldMapping) -> None:
        self._s.merge(
            m.FieldMappingModel(
                id=mapping.id,
                campaign_id=mapping.campaign_id,
                attribute_id=mapping.attribute_id,
                site_key=mapping.site_key,
                field_selector=mapping.field_selector,
                mapping_metadata=mapping.metadata,
            )
        )

    def get(self, mapping_id: FieldMappingId) -> FieldMapping | None:
        row = self._s.get(m.FieldMappingModel, mapping_id)
        return _field_mapping_to_entity(row) if row else None

    def list_for_site(self, site_key: str) -> list[FieldMapping]:
        rows = self._s.scalars(
            select(m.FieldMappingModel).where(m.FieldMappingModel.site_key == site_key)
        ).all()
        return [_field_mapping_to_entity(r) for r in rows]

    def list_for_campaign(self, campaign_id: CampaignId) -> list[FieldMapping]:
        rows = self._s.scalars(
            select(m.FieldMappingModel).where(m.FieldMappingModel.campaign_id == campaign_id)
        ).all()
        return [_field_mapping_to_entity(r) for r in rows]

    def find(self, site_key: str, field_selector: str) -> FieldMapping | None:
        # Deterministic ORDER BY id so multiple matching mappings always resolve to
        # the SAME one across runs/lanes (no nondeterministic first-row pick).
        rows = self._s.scalars(
            select(m.FieldMappingModel)
            .where(m.FieldMappingModel.site_key == site_key)
            .where(m.FieldMappingModel.field_selector == field_selector)
            .order_by(m.FieldMappingModel.id)
        ).all()
        entities = [_field_mapping_to_entity(r) for r in rows]
        scoped = [e for e in entities if e.campaign_id is not None]
        return (scoped or entities or [None])[0]


class DiscoverySourceRepo:
    def __init__(self, session: Session) -> None:
        self._s = session

    def upsert(self, source: DiscoverySource) -> None:
        self._s.merge(
            m.DiscoverySourceModel(
                id=source.id,
                campaign_id=source.campaign_id,
                source_key=source.source_key,
                enabled=source.enabled,
                yield_stats=source.yield_stats,
            )
        )

    def get(self, campaign_id: CampaignId, source_key: str) -> DiscoverySource | None:
        row = self._s.scalars(
            select(m.DiscoverySourceModel)
            .where(m.DiscoverySourceModel.campaign_id == campaign_id)
            .where(m.DiscoverySourceModel.source_key == source_key)
        ).first()
        return _discovery_source_to_entity(row) if row else None

    def list_for_campaign(self, campaign_id: CampaignId) -> list[DiscoverySource]:
        rows = self._s.scalars(
            select(m.DiscoverySourceModel).where(
                m.DiscoverySourceModel.campaign_id == campaign_id
            )
        ).all()
        return [_discovery_source_to_entity(r) for r in rows]


class AgentRunRepo:
    def __init__(self, session: Session) -> None:
        self._s = session

    def add(self, run: AgentRun) -> None:
        self._s.merge(
            m.AgentRunModel(
                id=run.id,
                campaign_id=run.campaign_id,
                intent_sentence={
                    "sentence": run.intent_sentence,
                    "run_mode": run.run_mode.value,
                    "throughput_target": run.throughput_target,
                    "stats": run.stats,
                    "seq": run.seq,
                },
                timestamp=run.timestamp,
            )
        )

    def get(self, run_id: AgentRunId) -> AgentRun | None:
        row = self._s.get(m.AgentRunModel, run_id)
        return _agent_run_to_entity(row) if row else None

    def list_for_campaign(
        self,
        campaign_id: CampaignId,
        *,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[AgentRun]:
        stmt = (
            select(m.AgentRunModel)
            .where(m.AgentRunModel.campaign_id == campaign_id)
            .order_by(m.AgentRunModel.timestamp, m.AgentRunModel.id)
        )
        if offset:
            stmt = stmt.offset(offset)
        if limit is not None:
            stmt = stmt.limit(limit)
        rows = self._s.scalars(stmt).all()
        return [_agent_run_to_entity(r) for r in rows]

    def count_pipelines_started_on(self, campaign_id: CampaignId, day: date) -> int:
        """Total pipelines started for ``campaign_id`` on the UTC ``day``.

        Sums each run's ``stats["pipelines_started"]`` (NOT a count of run rows) so the
        per-day throughput cap reflects how many applications were actually acted on,
        even when one tick starts many. ``stats`` lives inside the JSON blob, so the
        sum is computed in Python (mirrors the in-memory lane)."""
        start = datetime.combine(day, time.min)
        end = datetime.combine(day, time.max)
        rows = self._s.scalars(
            select(m.AgentRunModel)
            .where(m.AgentRunModel.campaign_id == campaign_id)
            .where(m.AgentRunModel.timestamp >= start)
            .where(m.AgentRunModel.timestamp <= end)
        ).all()
        total = 0
        for r in rows:
            run = _agent_run_to_entity(r)
            total += int((run.stats or {}).get("pipelines_started", 0))
        return total

    def latest(self, campaign_id: CampaignId) -> AgentRun | None:
        """Most recent run (timestamp DESC, seq tie-break per FR-AGENT-7)."""
        rows = self._s.scalars(
            select(m.AgentRunModel).where(m.AgentRunModel.campaign_id == campaign_id)
        ).all()
        runs = [_agent_run_to_entity(r) for r in rows]
        if not runs:
            return None
        # ``seq`` lives inside the JSON blob, so tie-break in Python (mirrors in-memory).
        return max(runs, key=lambda r: (r.timestamp, r.seq))

    def max_seq(self, campaign_id: CampaignId) -> int:
        """Highest ``seq`` among campaign runs (0 if none)."""
        rows = self._s.scalars(
            select(m.AgentRunModel).where(m.AgentRunModel.campaign_id == campaign_id)
        ).all()
        return max((_agent_run_to_entity(r).seq for r in rows), default=0)

    def prune_old(self, campaign_id: CampaignId, *, keep: int) -> int:
        """Keep the newest ``keep`` runs for ``campaign_id``; delete the rest.

        Newness is ordered by ``(timestamp, seq)``. ``seq`` lives inside the JSON blob,
        so ordering is resolved in Python (mirrors the in-memory lane) before the stale
        rows are deleted. Returns the number of runs deleted."""
        if keep < 0:
            keep = 0
        rows = self._s.scalars(
            select(m.AgentRunModel).where(m.AgentRunModel.campaign_id == campaign_id)
        ).all()
        ordered = sorted(
            rows, key=lambda r: (r.timestamp, _agent_run_to_entity(r).seq)
        )
        stale = ordered[: max(0, len(ordered) - keep)]
        for row in stale:
            self._s.delete(row)
        return len(stale)


class DetectionEventRepo:
    def __init__(self, session: Session) -> None:
        self._s = session

    def add(self, event: DetectionEvent) -> None:
        self._s.merge(
            m.DetectionEventModel(
                id=event.id,
                application_id=event.application_id,
                signal_type=event.signal_type,
                signal_detail=event.detail,
                timestamp=event.timestamp,
            )
        )

    def list_for_application(self, application_id: ApplicationId) -> list[DetectionEvent]:
        rows = self._s.scalars(
            select(m.DetectionEventModel)
            .where(m.DetectionEventModel.application_id == application_id)
            .order_by(m.DetectionEventModel.timestamp, m.DetectionEventModel.id)
        ).all()
        return [_detection_to_entity(r) for r in rows]

    def list_for_campaign(self, campaign_id: CampaignId) -> list[DetectionEvent]:
        rows = self._s.scalars(
            select(m.DetectionEventModel)
            .join(
                m.ApplicationModel,
                m.DetectionEventModel.application_id == m.ApplicationModel.id,
            )
            .where(m.ApplicationModel.campaign_id == campaign_id)
            .order_by(m.DetectionEventModel.timestamp, m.DetectionEventModel.id)
        ).all()
        return [_detection_to_entity(r) for r in rows]



def _snapshot_to_entity(row):
    return SubmissionSnapshot(id=row.id, application_id=row.application_id, answers=dict(row.answers or {}), materials=list(row.materials or []), ats_metadata=dict(row.ats_metadata or {}))

def _rejection_to_entity(row):
    return RejectionSignal(id=row.id, application_id=row.application_id, source=RejectionSource(row.source), signal_text=row.signal_text, confidence=row.confidence, detail=dict(row.detail or {}))

def _ghosting_to_entity(row):
    return GhostingSignal(campaign_id=row.campaign_id, application_id=row.application_id, sla_days=row.sla_days, submission_age_days=row.submission_age_days, detail=dict(row.detail or {}))

def _follow_up_to_entity(row):
    return FollowUp(id=row.id, campaign_id=row.campaign_id, application_id=row.application_id, template=FollowUpTemplate(row.template), status=FollowUpStatus(row.status), subject=row.subject, body=row.body, scheduled_at=row.scheduled_at, sent_at=row.sent_at)

def _attachment_to_entity(row):
    return PortfolioAttachment(id=row.id, campaign_id=row.campaign_id, application_id=row.application_id if row.application_id else None, attachment_type=AttachmentType(row.attachment_type), file_name=row.file_name, storage_path=row.storage_path, display_name=row.display_name, description=row.description, metadata=dict(row.metadata or {}))


class SubmissionSnapshotRepo:
    def __init__(self, session): self._s = session
    def add(self, s): self._s.merge(m.SubmissionSnapshotModel(id=s.id, application_id=s.application_id, answers=s.answers, materials=s.materials, ats_metadata=s.ats_metadata))
    def get(self, sid): row = self._s.get(m.SubmissionSnapshotModel, sid); return _snapshot_to_entity(row) if row else None
    def get_for_application(self, aid): row = self._s.scalars(select(m.SubmissionSnapshotModel).where(m.SubmissionSnapshotModel.application_id == aid).order_by(m.SubmissionSnapshotModel.captured_at.desc())).first(); return _snapshot_to_entity(row) if row else None
    def list_for_campaign(self, cid): rows = self._s.scalars(select(m.SubmissionSnapshotModel).join(m.ApplicationModel, m.SubmissionSnapshotModel.application_id == m.ApplicationModel.id).where(m.ApplicationModel.campaign_id == cid)).all(); return [_snapshot_to_entity(r) for r in rows]
    def delete_for_application(self, aid): return bool(self._s.query(m.SubmissionSnapshotModel).filter(m.SubmissionSnapshotModel.application_id == aid).delete(synchronize_session=False))

class RejectionSignalRepo:
    def __init__(self, session): self._s = session
    def add(self, sig): self._s.merge(m.RejectionSignalModel(id=sig.id, application_id=sig.application_id, source=sig.source.value, signal_text=sig.signal_text, confidence=sig.confidence, detail=sig.detail))
    def list_for_application(self, aid): rows = self._s.scalars(select(m.RejectionSignalModel).where(m.RejectionSignalModel.application_id == aid).order_by(m.RejectionSignalModel.detected_at)).all(); return [_rejection_to_entity(r) for r in rows]
    def list_for_campaign(self, cid): rows = self._s.scalars(select(m.RejectionSignalModel).join(m.ApplicationModel, m.RejectionSignalModel.application_id == m.ApplicationModel.id).where(m.ApplicationModel.campaign_id == cid).order_by(m.RejectionSignalModel.detected_at)).all(); return [_rejection_to_entity(r) for r in rows]

class GhostingSignalRepo:
    def __init__(self, session): self._s = session
    def add(self, sig): from applicant.core.ids import new_id; self._s.merge(m.GhostingSignalModel(id=new_id(), campaign_id=sig.campaign_id, application_id=sig.application_id, sla_days=sig.sla_days, submission_age_days=sig.submission_age_days, detail=sig.detail))
    def list_for_application(self, aid): rows = self._s.scalars(select(m.GhostingSignalModel).where(m.GhostingSignalModel.application_id == aid).order_by(m.GhostingSignalModel.detected_at)).all(); return [_ghosting_to_entity(r) for r in rows]
    def list_for_campaign(self, cid): rows = self._s.scalars(select(m.GhostingSignalModel).where(m.GhostingSignalModel.campaign_id == cid).order_by(m.GhostingSignalModel.detected_at)).all(); return [_ghosting_to_entity(r) for r in rows]

class FollowUpRepo:
    def __init__(self, session): self._s = session
    def add(self, f): self._s.merge(m.FollowUpModel(id=f.id, campaign_id=f.campaign_id, application_id=f.application_id, template=f.template.value, status=f.status.value, subject=f.subject, body=f.body, scheduled_at=f.scheduled_at, sent_at=f.sent_at))
    def get(self, fid): row = self._s.get(m.FollowUpModel, fid); return _follow_up_to_entity(row) if row else None
    def list_for_application(self, aid): rows = self._s.scalars(select(m.FollowUpModel).where(m.FollowUpModel.application_id == aid).order_by(m.FollowUpModel.created_at)).all(); return [_follow_up_to_entity(r) for r in rows]
    def list_for_campaign(self, cid): rows = self._s.scalars(select(m.FollowUpModel).where(m.FollowUpModel.campaign_id == cid).order_by(m.FollowUpModel.created_at)).all(); return [_follow_up_to_entity(r) for r in rows]
    def list_due(self, now): rows = self._s.scalars(select(m.FollowUpModel).where(m.FollowUpModel.scheduled_at <= now).where(m.FollowUpModel.status == "SCHEDULED").order_by(m.FollowUpModel.scheduled_at)).all(); return [_follow_up_to_entity(r) for r in rows]

class PortfolioAttachmentRepo:
    def __init__(self, session): self._s = session
    def add(self, a): self._s.merge(m.PortfolioAttachmentModel(id=a.id, campaign_id=a.campaign_id, application_id=a.application_id, attachment_type=a.attachment_type.value, file_name=a.file_name, storage_path=a.storage_path, display_name=a.display_name, description=a.description, metadata=a.metadata))
    def get(self, aid): row = self._s.get(m.PortfolioAttachmentModel, aid); return _attachment_to_entity(row) if row else None
    def list_for_application(self, aid): rows = self._s.scalars(select(m.PortfolioAttachmentModel).where(m.PortfolioAttachmentModel.application_id == aid).order_by(m.PortfolioAttachmentModel.created_at)).all(); return [_attachment_to_entity(r) for r in rows]
    def list_for_campaign(self, cid): rows = self._s.scalars(select(m.PortfolioAttachmentModel).where(m.PortfolioAttachmentModel.campaign_id == cid).order_by(m.PortfolioAttachmentModel.created_at)).all(); return [_attachment_to_entity(r) for r in rows]
    def delete(self, aid): row = self._s.get(m.PortfolioAttachmentModel, aid); self._s.delete(row); return bool(row)
    def delete_for_application(self, aid): return int(self._s.query(m.PortfolioAttachmentModel).filter(m.PortfolioAttachmentModel.application_id == aid).delete(synchronize_session=False) or 0)

class OnboardingProfileRepo:
    def __init__(self, session: Session) -> None:
        self._s = session

    def add(self, profile: OnboardingProfile) -> None:
        self._s.merge(
            m.OnboardingProfileModel(
                id=profile.id,
                campaign_id=profile.campaign_id,
                completion_flag=profile.completion_flag,
                wizard_state=profile.wizard_state,
                intake=profile.intake,
            )
        )

    def get_for_campaign(self, campaign_id: CampaignId) -> OnboardingProfile | None:
        row = self._s.scalars(
            select(m.OnboardingProfileModel).where(
                m.OnboardingProfileModel.campaign_id == campaign_id
            )
        ).first()
        return _onboarding_to_entity(row) if row else None


class SqlAlchemyStorage:
    """Concrete ``StoragePort``: aggregates repositories under one session."""

    def __init__(self, session: Session) -> None:
        self._session = session
        self.campaigns = CampaignRepo(session)
        self.attributes = AttributeRepo(session)
        self.postings = JobPostingRepo(session)
        self.applications = ApplicationRepo(session)
        self.resume_variants = ResumeVariantRepo(session)
        self.documents = GeneratedDocumentRepo(session)
        self.revisions = RevisionSessionRepo(session)
        self.decisions = DecisionRepo(session)
        self.outcomes = OutcomeEventRepo(session)
        self.screenshots = ApplicationScreenshotRepo(session)
        self.pending_actions = PendingActionRepo(session)
        self.field_mappings = FieldMappingRepo(session)
        self.discovery_sources = DiscoverySourceRepo(session)
        self.agent_runs = AgentRunRepo(session)
        self.detection_events = DetectionEventRepo(session)
        self.onboarding_profiles = OnboardingProfileRepo(session)
        self.submission_snapshots = SubmissionSnapshotRepo(session)
        self.rejection_signals = RejectionSignalRepo(session)
        self.ghosting_signals = GhostingSignalRepo(session)
        self.follow_ups = FollowUpRepo(session)
        self.portfolio_attachments = PortfolioAttachmentRepo(session)

    def commit(self) -> None:
        self._session.commit()

    def rollback(self) -> None:
        self._session.rollback()

    def purge_campaign(self, cid: CampaignId) -> dict[str, int]:
        """Cascade-delete every row belonging to ``cid`` (#363, FR-CRIT-4, NFR-PRIV-1).

        Mirrors :meth:`InMemoryStorage.purge_campaign`: erases the PII-bearing +
        derived rows (onboarding intake, attribute cloud, résumé variants, generated
        materials, the application-scoped children, postings, per-campaign field
        mappings, discovery sources, agent runs, pending actions) and finally the
        campaign row, in FK-safe order (children before parents). Banked credentials
        are purged separately via the credential store. Returns a per-table count so a
        caller can verify a complete purge. The caller commits the unit of work.
        """
        s = self._session
        scid = str(cid)

        app_ids = [
            r[0]
            for r in s.query(m.ApplicationModel.id)
            .filter(m.ApplicationModel.campaign_id == scid)
            .all()
        ]
        material_ids = [
            r[0]
            for r in s.query(m.GeneratedMaterialModel.id)
            .filter(m.GeneratedMaterialModel.campaign_id == scid)
            .all()
        ]

        def _del(model, *crit) -> int:
            if not crit:
                return 0
            return int(
                s.query(model).filter(*crit).delete(synchronize_session=False) or 0
            )

        counts: dict[str, int] = {}
        # Application-scoped children first (FK -> applications).
        if app_ids:
            counts["decisions"] = _del(
                m.DecisionModel, m.DecisionModel.application_id.in_(app_ids)
            )
            counts["outcomes"] = _del(
                m.OutcomeEventModel, m.OutcomeEventModel.application_id.in_(app_ids)
            )
            counts["screenshots"] = _del(
                m.ApplicationScreenshotModel,
                m.ApplicationScreenshotModel.application_id.in_(app_ids),
            )
            counts["detection_events"] = _del(
                m.DetectionEventModel,
                m.DetectionEventModel.application_id.in_(app_ids),
            )
            counts["submission_snapshots"] = _del(
                m.SubmissionSnapshotModel,
                m.SubmissionSnapshotModel.application_id.in_(app_ids),
            )
            counts["rejection_signals"] = _del(
                m.RejectionSignalModel,
                m.RejectionSignalModel.application_id.in_(app_ids),
            )
            counts["ghosting_signals"] = _del(
                m.GhostingSignalModel,
                m.GhostingSignalModel.application_id.in_(app_ids),
            )
            counts["follow_ups"] = _del(
                m.FollowUpModel,
                m.FollowUpModel.application_id.in_(app_ids),
            )
            counts["portfolio_attachments"] = _del(
                m.PortfolioAttachmentModel,
                m.PortfolioAttachmentModel.application_id.in_(app_ids),
            )
                m.DetectionEventModel,
                m.DetectionEventModel.application_id.in_(app_ids),
            )
        # Revision sessions (FK -> generated_materials) before the materials.
        if material_ids:
            counts["revisions"] = _del(
                m.RevisionSessionModel,
                m.RevisionSessionModel.material_id.in_(material_ids),
            )
        counts["documents"] = _del(
            m.GeneratedMaterialModel, m.GeneratedMaterialModel.campaign_id == scid
        )
        # Applications reference resume_variants + postings, so delete them first.
        counts["applications"] = _del(
            m.ApplicationModel, m.ApplicationModel.campaign_id == scid
        )
        counts["resume_variants"] = _del(
            m.ResumeVariantModel, m.ResumeVariantModel.campaign_id == scid
        )
        counts["postings"] = _del(
            m.JobPostingModel, m.JobPostingModel.campaign_id == scid
        )
        counts["attributes"] = _del(
            m.AttributeModel, m.AttributeModel.campaign_id == scid
        )
        counts["field_mappings"] = _del(
            m.FieldMappingModel, m.FieldMappingModel.campaign_id == scid
        )
        counts["discovery_sources"] = _del(
            m.DiscoverySourceModel, m.DiscoverySourceModel.campaign_id == scid
        )
        counts["agent_runs"] = _del(
            m.AgentRunModel, m.AgentRunModel.campaign_id == scid
        )
        counts["pending_actions"] = _del(
            m.PendingActionModel, m.PendingActionModel.campaign_id == scid
        )
        counts["onboarding_profiles"] = _del(
            m.OnboardingProfileModel, m.OnboardingProfileModel.campaign_id == scid
        )
        # Credentials FK -> campaigns; purge any that the credential store missed so
        # the campaign row can be deleted without a FK violation.
        counts["credentials"] = _del(
            m.CredentialModel, m.CredentialModel.campaign_id == scid
        )
        counts["campaigns"] = _del(m.CampaignModel, m.CampaignModel.id == scid)
        return counts

    def prune_pii_older_than(self, cutoff: datetime) -> dict[str, int]:
        """Prune PII (attributes + onboarding intakes) recorded before ``cutoff`` (#363).

        Mirrors :meth:`InMemoryStorage.prune_pii_older_than`: only the PII-bearing
        tables are swept; in-window PII is retained. Returns a per-table count. The
        caller commits the unit of work.
        """
        s = self._session
        attrs = int(
            s.query(m.AttributeModel)
            .filter(m.AttributeModel.created_at < cutoff)
            .delete(synchronize_session=False)
            or 0
        )
        profiles = int(
            s.query(m.OnboardingProfileModel)
            .filter(m.OnboardingProfileModel.created_at < cutoff)
            .delete(synchronize_session=False)
            or 0
        )
        return {"attributes": attrs, "onboarding_profiles": profiles}

    def healthcheck(self) -> bool:
        from sqlalchemy import text

        try:
            self._session.execute(text("SELECT 1"))
            return True
        except Exception:
            return False
