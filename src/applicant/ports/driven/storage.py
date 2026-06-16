"""Storage port (FR-ATTR, FR-LOG, FR-DUR, FR-CRIT-4).

Repository protocols, one per aggregate. Everything is campaign-scoped (FR-CRIT-4).
The default adapter is Postgres/JSONB (``adapters.storage``); contract tests prove
any adapter honors these protocols. A ``UnitOfWork`` groups repositories under one
transaction.

These Protocols deliberately use ``object`` / entity types from the core so the
core never imports SQLAlchemy.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from applicant.core.entities.agent_run import AgentRun
from applicant.core.entities.application import Application
from applicant.core.entities.attribute import Attribute
from applicant.core.entities.campaign import Campaign
from applicant.core.entities.decision import Decision
from applicant.core.entities.discovery_source import DiscoverySource
from applicant.core.entities.field_mapping import FieldMapping
from applicant.core.entities.generated_document import GeneratedDocument
from applicant.core.entities.job_posting import JobPosting
from applicant.core.entities.outcome_event import OutcomeEvent
from applicant.core.entities.pending_action import PendingAction
from applicant.core.entities.resume_variant import ResumeVariant
from applicant.core.entities.revision_session import RevisionSession
from applicant.core.ids import (
    AgentRunId,
    ApplicationId,
    AttributeId,
    CampaignId,
    FieldMappingId,
    GeneratedDocumentId,
    JobPostingId,
    PendingActionId,
    ResumeVariantId,
    RevisionSessionId,
)


@runtime_checkable
class CampaignRepository(Protocol):
    def add(self, campaign: Campaign) -> None: ...
    def get(self, campaign_id: CampaignId) -> Campaign | None: ...
    def list(self) -> list[Campaign]: ...


@runtime_checkable
class AttributeRepository(Protocol):
    def add(self, attribute: Attribute) -> None: ...
    def get(self, attribute_id: AttributeId) -> Attribute | None: ...
    def list_for_campaign(self, campaign_id: CampaignId) -> list[Attribute]: ...


@runtime_checkable
class JobPostingRepository(Protocol):
    def add(self, posting: JobPosting) -> None: ...
    def get(self, posting_id: JobPostingId) -> JobPosting | None: ...
    def list_for_campaign(self, campaign_id: CampaignId) -> list[JobPosting]: ...


@runtime_checkable
class ApplicationRepository(Protocol):
    def add(self, application: Application) -> None: ...
    def get(self, application_id: ApplicationId) -> Application | None: ...
    def update(self, application: Application) -> None: ...
    def list_for_campaign(self, campaign_id: CampaignId) -> list[Application]: ...


@runtime_checkable
class ResumeVariantRepository(Protocol):
    def add(self, variant: ResumeVariant) -> None: ...
    def get(self, variant_id: ResumeVariantId) -> ResumeVariant | None: ...
    def list_for_campaign(self, campaign_id: CampaignId) -> list[ResumeVariant]: ...


@runtime_checkable
class GeneratedDocumentRepository(Protocol):
    def add(self, document: GeneratedDocument) -> None: ...
    def get(self, document_id: GeneratedDocumentId) -> GeneratedDocument | None: ...
    def list_for_application(self, application_id: ApplicationId) -> list[GeneratedDocument]: ...


@runtime_checkable
class RevisionSessionRepository(Protocol):
    """Durable interactive redline sessions (FR-RESUME-8): resumable across restarts."""

    def add(self, session: RevisionSession) -> None: ...
    def get(self, session_id: RevisionSessionId) -> RevisionSession | None: ...
    def get_for_material(self, material_id: GeneratedDocumentId) -> RevisionSession | None: ...


@runtime_checkable
class DecisionRepository(Protocol):
    def add(self, decision: Decision) -> None: ...
    def list_for_application(self, application_id: ApplicationId) -> list[Decision]: ...


@runtime_checkable
class OutcomeEventRepository(Protocol):
    def add(self, event: OutcomeEvent) -> None: ...
    def list_for_application(self, application_id: ApplicationId) -> list[OutcomeEvent]: ...


@runtime_checkable
class PendingActionRepository(Protocol):
    def add(self, action: PendingAction) -> None: ...
    def get(self, action_id: PendingActionId) -> PendingAction | None: ...
    def list_open(self, campaign_id: CampaignId) -> list[PendingAction]: ...
    def resolve(self, action_id: PendingActionId) -> None: ...


@runtime_checkable
class FieldMappingRepository(Protocol):
    """Attribute->form-field bindings; shared or per-campaign (FR-ATTR-2)."""

    def add(self, mapping: FieldMapping) -> None: ...
    def get(self, mapping_id: FieldMappingId) -> FieldMapping | None: ...
    def list_for_site(self, site_key: str) -> list[FieldMapping]: ...
    def list_for_campaign(self, campaign_id: CampaignId) -> list[FieldMapping]: ...
    def find(self, site_key: str, field_selector: str) -> FieldMapping | None: ...


@runtime_checkable
class DiscoverySourceRepository(Protocol):
    """Per-campaign source toggles + learned yield stats (FR-DISC-2/5)."""

    def upsert(self, source: DiscoverySource) -> None: ...
    def get(self, campaign_id: CampaignId, source_key: str) -> DiscoverySource | None: ...
    def list_for_campaign(self, campaign_id: CampaignId) -> list[DiscoverySource]: ...


@runtime_checkable
class AgentRunRepository(Protocol):
    """Per-run intent + run-control snapshot (FR-AGENT-1/2/7)."""

    def add(self, run: AgentRun) -> None: ...
    def get(self, run_id: AgentRunId) -> AgentRun | None: ...
    def list_for_campaign(self, campaign_id: CampaignId) -> list[AgentRun]: ...


@runtime_checkable
class StoragePort(Protocol):
    """Aggregate of all repositories under one unit of work.

    Adapters expose each repository and a transactional boundary. Implementations
    may be Postgres-backed (default) or in-memory (tests).
    """

    campaigns: CampaignRepository
    attributes: AttributeRepository
    postings: JobPostingRepository
    applications: ApplicationRepository
    resume_variants: ResumeVariantRepository
    documents: GeneratedDocumentRepository
    revisions: RevisionSessionRepository
    decisions: DecisionRepository
    outcomes: OutcomeEventRepository
    pending_actions: PendingActionRepository
    field_mappings: FieldMappingRepository
    discovery_sources: DiscoverySourceRepository
    agent_runs: AgentRunRepository

    def commit(self) -> None: ...
    def rollback(self) -> None: ...
    def healthcheck(self) -> bool:
        """True if the backing store is reachable (tolerated False in tests)."""
        ...
