"""Storage port (FR-ATTR, FR-LOG, FR-DUR, FR-CRIT-4).

Repository protocols, one per aggregate. Everything is campaign-scoped (FR-CRIT-4).
The default adapter is Postgres/JSONB (``adapters.storage``); contract tests prove
any adapter honors these protocols. A ``UnitOfWork`` groups repositories under one
transaction.

These Protocols deliberately use ``object`` / entity types from the core so the
core never imports SQLAlchemy.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Protocol, runtime_checkable

from applicant.core.entities.action_event import ActionEvent
from applicant.core.entities.agent_run import AgentRun
from applicant.core.entities.application import Application
from applicant.core.entities.application_screenshot import ApplicationScreenshot
from applicant.core.entities.attribute import Attribute
from applicant.core.entities.campaign import Campaign
from applicant.core.entities.decision import Decision
from applicant.core.entities.detection_event import DetectionEvent
from applicant.core.entities.discovery_source import DiscoverySource
from applicant.core.entities.field_mapping import FieldMapping
from applicant.core.entities.follow_up import FollowUp
from applicant.core.entities.generated_document import GeneratedDocument
from applicant.core.entities.ghosting_signal import GhostingSignal
from applicant.core.entities.job_posting import JobPosting
from applicant.core.entities.onboarding_profile import OnboardingProfile
from applicant.core.entities.outcome_event import OutcomeEvent
from applicant.core.entities.pending_action import PendingAction
from applicant.core.entities.portfolio_attachment import PortfolioAttachment
from applicant.core.entities.rejection_signal import RejectionSignal
from applicant.core.entities.resume_variant import ResumeVariant
from applicant.core.entities.revision_session import RevisionSession
from applicant.core.entities.screening_answer_library import ScreeningAnswerLibraryEntry
from applicant.core.entities.submission_snapshot import SubmissionSnapshot
from applicant.core.ids import (
    AgentRunId,
    ApplicationId,
    AttributeId,
    CampaignId,
    FieldMappingId,
    FollowUpId,
    GeneratedDocumentId,
    JobPostingId,
    PendingActionId,
    PortfolioAttachmentId,
    ResumeVariantId,
    RevisionSessionId,
    SubmissionSnapshotId,
)
from applicant.core.state_machine import ApplicationState


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
    def list_unscored_for_campaign(self, campaign_id: CampaignId) -> list[JobPosting]:
        """Postings in ``campaign_id`` whose ``viability_score`` is None (need scoring)."""
        ...


@runtime_checkable
class ApplicationRepository(Protocol):
    def add(self, application: Application) -> None: ...
    def get(self, application_id: ApplicationId) -> Application | None: ...
    def update(self, application: Application) -> None: ...
    def list_for_campaign(self, campaign_id: CampaignId) -> list[Application]: ...
    def get_by_posting(
        self, campaign_id: CampaignId, posting_id: JobPostingId
    ) -> Application | None:
        """The application for ``posting_id`` within ``campaign_id`` (or None)."""
        ...

    def list_by_status(
        self, campaign_id: CampaignId, statuses: tuple[ApplicationState, ...]
    ) -> list[Application]:
        """Applications in ``campaign_id`` whose status is in ``statuses``."""
        ...


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
    def list_for_campaign(self, campaign_id: CampaignId) -> list[GeneratedDocument]:
        """All generated materials for ``campaign_id`` (purge verification, #363)."""
        ...


@runtime_checkable
class RevisionSessionRepository(Protocol):
    """Durable interactive redline sessions (FR-RESUME-8): resumable across restarts."""

    def add(self, session: RevisionSession) -> None: ...
    def get(self, session_id: RevisionSessionId) -> RevisionSession | None: ...
    def get_for_material(self, material_id: GeneratedDocumentId) -> RevisionSession | None: ...
    def list_for_materials(
        self, material_ids: list[GeneratedDocumentId]
    ) -> list[RevisionSession]:
        """Batch ``get_for_material`` for many materials at once (no N+1)."""
        ...


@runtime_checkable
class DecisionRepository(Protocol):
    def add(self, decision: Decision) -> None: ...
    def list_for_application(self, application_id: ApplicationId) -> list[Decision]: ...
    def list_for_campaign(self, campaign_id: CampaignId) -> list[Decision]:
        """All decisions attached to a real application in ``campaign_id`` (no N+1)."""
        ...
    def list_approved_postings_for_campaign(
        self, campaign_id: CampaignId
    ) -> list[JobPostingId]:
        """Posting ids in ``campaign_id`` with an APPROVED decision (single join, no N+1)."""
        ...


@runtime_checkable
class OutcomeEventRepository(Protocol):
    def add(self, event: OutcomeEvent) -> None: ...
    def list_for_application(self, application_id: ApplicationId) -> list[OutcomeEvent]: ...
    def list_for_campaign(
        self,
        campaign_id: CampaignId,
        *,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[OutcomeEvent]: ...
    def exists_terminal_for_application(self, application_id: ApplicationId) -> bool:
        """True if a terminal (submitted/converted) outcome exists (idempotent submit)."""
        ...


@runtime_checkable
class ApplicationScreenshotRepository(Protocol):
    """Per-page screenshots captured during pre-fill (FR-LOG-2 / FR-OBS-2)."""

    def add(self, shot: ApplicationScreenshot) -> None: ...
    def list_for_application(self, application_id: ApplicationId) -> list[ApplicationScreenshot]: ...
    def list_for_campaign(
        self,
        campaign_id: CampaignId,
        *,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[ApplicationScreenshot]:
        """All screenshots whose application belongs to ``campaign_id`` (batch load)."""
        ...


@runtime_checkable
class DetectionEventRepository(Protocol):
    """Automation-detection signals persisted for the FR-OBS-2 debug surface."""

    def add(self, event: DetectionEvent) -> None: ...
    def list_for_application(self, application_id: ApplicationId) -> list[DetectionEvent]: ...
    def list_for_campaign(self, campaign_id: CampaignId) -> list[DetectionEvent]: ...


@runtime_checkable
class SubmissionSnapshotRepository(Protocol):
    def add(self, snapshot: SubmissionSnapshot) -> None: ...
    def get(self, snapshot_id: SubmissionSnapshotId) -> SubmissionSnapshot | None: ...
    def get_for_application(self, application_id: ApplicationId) -> SubmissionSnapshot | None: ...
    def list_for_campaign(self, campaign_id: CampaignId) -> list[SubmissionSnapshot]: ...
    def delete_for_application(self, application_id: ApplicationId) -> bool: ...


class RejectionSignalRepository(Protocol):
    def add(self, signal: RejectionSignal) -> None: ...
    def list_for_application(self, application_id: ApplicationId) -> list[RejectionSignal]: ...
    def list_for_campaign(self, campaign_id: CampaignId) -> list[RejectionSignal]: ...


class GhostingSignalRepository(Protocol):
    def add(self, signal: GhostingSignal) -> None: ...
    def list_for_application(self, application_id: ApplicationId) -> list[GhostingSignal]: ...
    def list_for_campaign(self, campaign_id: CampaignId) -> list[GhostingSignal]: ...


class FollowUpRepository(Protocol):
    def add(self, follow_up: FollowUp) -> None: ...
    #: Persist a status change (e.g. SCHEDULED -> SENT, dark-engine audit B2
    #: item 7's idempotent send queue). Same upsert semantics as ``add``.
    def update(self, follow_up: FollowUp) -> None: ...
    def get(self, follow_up_id: FollowUpId) -> FollowUp | None: ...
    def list_for_application(self, application_id: ApplicationId) -> list[FollowUp]: ...
    def list_for_campaign(self, campaign_id: CampaignId) -> list[FollowUp]: ...
    def list_due(self, now: datetime) -> list[FollowUp]: ...


@runtime_checkable
class PortfolioAttachmentRepository(Protocol):
    def add(self, attachment: PortfolioAttachment) -> None: ...
    def get(self, attachment_id: PortfolioAttachmentId) -> PortfolioAttachment | None: ...
    def list_for_application(self, application_id: ApplicationId) -> list[PortfolioAttachment]: ...
    def list_for_campaign(self, campaign_id: CampaignId) -> list[PortfolioAttachment]: ...
    def delete(self, attachment_id: PortfolioAttachmentId) -> bool: ...
    def delete_for_application(self, application_id: ApplicationId) -> int: ...


@runtime_checkable
class ActionEventRepository(Protocol):
    """Append-only audit trail (FR-LOG-4, FR-OBS-2)."""

    def add(self, event: ActionEvent) -> None: ...
    def list_for_campaign(
        self,
        campaign_id: CampaignId,
        *,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[ActionEvent]: ...
    def list_for_application(
        self, application_id: ApplicationId
    ) -> list[ActionEvent]: ...
    #: Cascade helper: erase every action-trail row for a campaign (used by the
    #: campaign-purge cascade so "Clear demo data" / a campaign delete leaves no
    #: residual audit rows). Returns the count deleted.
    def delete_for_campaign(self, campaign_id: CampaignId) -> int: ...


class OnboardingProfileRepository(Protocol):
    """Resumable onboarding intake + completion record (FR-ONBOARD-2)."""

    def add(self, profile: OnboardingProfile) -> None: ...
    def get_for_campaign(self, campaign_id: CampaignId) -> OnboardingProfile | None: ...


@runtime_checkable
class PendingActionRepository(Protocol):
    def add(self, action: PendingAction) -> None: ...
    def get(self, action_id: PendingActionId) -> PendingAction | None: ...
    def list_open(self, campaign_id: CampaignId) -> list[PendingAction]: ...
    def resolve(self, action_id: PendingActionId) -> None: ...
    def find_open_by_dedup(
        self, campaign_id: CampaignId, dedup_key: str
    ) -> PendingAction | None:
        """Open action in ``campaign_id`` matching ``dedup_key`` (direct indexed lookup)."""
        ...


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
class ScreeningAnswerLibraryRepository(Protocol):
    """Reusable, campaign-scoped screening-answer library (product-gaps #20).

    Keyed by the NORMALIZED question text (``core.rules.materials.
    normalize_screening_question``) so a re-asked question (same wording, minor
    variation) resolves to the same entry. ``upsert`` mirrors
    ``DiscoverySourceRepository`` -- the newest generation for a given question
    replaces the stored one, so the library always reflects the latest voice.
    """

    def upsert(self, entry: ScreeningAnswerLibraryEntry) -> None: ...
    def get(
        self, campaign_id: CampaignId, question_key: str
    ) -> ScreeningAnswerLibraryEntry | None: ...
    def list_for_campaign(
        self, campaign_id: CampaignId
    ) -> list[ScreeningAnswerLibraryEntry]: ...
    def delete_for_campaign(self, campaign_id: CampaignId) -> int:
        """Purge every library entry for ``campaign_id`` (#363 purge parity)."""
        ...


@runtime_checkable
class AgentRunRepository(Protocol):
    """Per-run intent + run-control snapshot (FR-AGENT-1/2/7)."""

    def add(self, run: AgentRun) -> None: ...
    def get(self, run_id: AgentRunId) -> AgentRun | None: ...
    def list_for_campaign(
        self,
        campaign_id: CampaignId,
        *,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[AgentRun]: ...
    def count_pipelines_started_on(self, campaign_id: CampaignId, day: date) -> int:
        """Total pipelines started for ``campaign_id`` on ``day`` (UTC date).

        Sums each run's ``stats["pipelines_started"]`` for the day (NOT a count of run
        rows), so the per-day throughput cap reflects applications actually acted on.
        """
        ...

    def sum_stats_between(
        self,
        campaign_id: CampaignId,
        start: datetime,
        end: datetime,
        keys: tuple[str, ...],
    ) -> dict[str, float]:
        """Sum each of ``keys`` across every run's ``stats`` in ``[start, end]`` (P1-6).

        Generalizes ``count_pipelines_started_on``'s "sum a numeric stats field
        across a day's runs" pattern to an arbitrary inclusive datetime range and
        an arbitrary set of keys, so the cost & pace guardrails can read both
        "today" (a day window) and "month to date" (a wider window) through one
        method. A key absent from a given run's ``stats`` contributes 0. Returns
        a dict with every requested key present (0.0 when no run has it).
        """
        ...

    def latest(self, campaign_id: CampaignId) -> AgentRun | None:
        """Most recent run for ``campaign_id`` (by timestamp, seq tie-break)."""
        ...

    def max_seq(self, campaign_id: CampaignId) -> int:
        """Highest ``seq`` among runs for ``campaign_id`` (0 if none)."""
        ...

    def prune_old(self, campaign_id: CampaignId, *, keep: int) -> int:
        """Keep the newest ``keep`` runs for ``campaign_id``; delete the rest.

        Retention for 24/7 ticking (#11): newness is ordered by ``(timestamp, seq)`` so
        pruning is deterministic and stable across both lanes. Returns the number of
        runs deleted.
        """
        ...


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
    screenshots: ApplicationScreenshotRepository
    pending_actions: PendingActionRepository
    field_mappings: FieldMappingRepository
    discovery_sources: DiscoverySourceRepository
    screening_answer_library: ScreeningAnswerLibraryRepository
    agent_runs: AgentRunRepository
    detection_events: DetectionEventRepository
    onboarding_profiles: OnboardingProfileRepository
    submission_snapshots: SubmissionSnapshotRepository
    rejection_signals: RejectionSignalRepository
    ghosting_signals: GhostingSignalRepository
    follow_ups: FollowUpRepository
    portfolio_attachments: PortfolioAttachmentRepository
    action_events: ActionEventRepository

    def commit(self) -> None: ...
    def rollback(self) -> None: ...
    def healthcheck(self) -> bool:
        """True if the backing store is reachable (tolerated False in tests)."""
        ...
