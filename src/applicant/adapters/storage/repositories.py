"""Concrete SQLAlchemy repositories implementing the storage port protocols.

Each repository maps between the pure-core entities and the ORM models. The
``SqlAlchemyStorage`` aggregates the repositories and provides the unit-of-work
boundary (``commit``/``rollback``) required by ``StoragePort``.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from applicant.adapters.storage import models as m
from applicant.core.entities.agent_run import AgentRun
from applicant.core.entities.application import Application
from applicant.core.entities.attribute import Attribute
from applicant.core.entities.campaign import Campaign, RunMode
from applicant.core.entities.decision import Decision, DecisionType
from applicant.core.entities.discovery_source import DiscoverySource
from applicant.core.entities.generated_document import DocumentType, GeneratedDocument
from applicant.core.entities.job_posting import JobPosting
from applicant.core.entities.outcome_event import OutcomeEvent, OutcomeSource
from applicant.core.entities.pending_action import PendingAction
from applicant.core.entities.resume_variant import ResumeVariant
from applicant.core.ids import (
    AgentRunId,
    ApplicationId,
    AttributeId,
    CampaignId,
    DiscoverySourceId,
    GeneratedDocumentId,
    JobPostingId,
    PendingActionId,
    ResumeVariantId,
)
from applicant.core.state_machine import ApplicationState

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
    return AgentRun(
        id=AgentRunId(row.id),
        campaign_id=CampaignId(row.campaign_id),
        intent_sentence=blob.get("sentence", ""),
        run_mode=RunMode(blob.get("run_mode", RunMode.CONTINUOUS.value)),
        throughput_target=int(blob.get("throughput_target", 15)),
        stats=dict(blob.get("stats", {})),
        timestamp=row.timestamp,
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
            )
        )

    def get(self, posting_id: JobPostingId) -> JobPosting | None:
        row = self._s.get(m.JobPostingModel, posting_id)
        return _posting_to_entity(row) if row else None

    def list_for_campaign(self, campaign_id: CampaignId) -> list[JobPosting]:
        rows = self._s.scalars(
            select(m.JobPostingModel).where(m.JobPostingModel.campaign_id == campaign_id)
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
            select(m.ApplicationModel).where(m.ApplicationModel.campaign_id == campaign_id)
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
            select(m.DecisionModel).where(m.DecisionModel.application_id == application_id)
        ).all()
        return [_decision_to_entity(r) for r in rows]


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
            select(m.OutcomeEventModel).where(m.OutcomeEventModel.application_id == application_id)
        ).all()
        return [_outcome_to_entity(r) for r in rows]


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
        ).all()
        return [_pending_to_entity(r) for r in rows]

    def resolve(self, action_id: PendingActionId) -> None:
        row = self._s.get(m.PendingActionModel, action_id)
        if row:
            row.resolved = True


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
                },
                timestamp=run.timestamp,
            )
        )

    def get(self, run_id: AgentRunId) -> AgentRun | None:
        row = self._s.get(m.AgentRunModel, run_id)
        return _agent_run_to_entity(row) if row else None

    def list_for_campaign(self, campaign_id: CampaignId) -> list[AgentRun]:
        rows = self._s.scalars(
            select(m.AgentRunModel).where(m.AgentRunModel.campaign_id == campaign_id)
        ).all()
        return [_agent_run_to_entity(r) for r in rows]


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
        self.decisions = DecisionRepo(session)
        self.outcomes = OutcomeEventRepo(session)
        self.pending_actions = PendingActionRepo(session)
        self.discovery_sources = DiscoverySourceRepo(session)
        self.agent_runs = AgentRunRepo(session)

    def commit(self) -> None:
        self._session.commit()

    def rollback(self) -> None:
        self._session.rollback()

    def healthcheck(self) -> bool:
        from sqlalchemy import text

        try:
            self._session.execute(text("SELECT 1"))
            return True
        except Exception:
            return False
