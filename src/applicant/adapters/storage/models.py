"""SQLAlchemy 2.0 ORM for all 19 base tables + derived pending_actions.

Source: docs/data-model.md (master spec §8). Everything is campaign-scoped
(FR-CRIT-4). JSONB columns use a portable type that maps to JSONB on Postgres and
JSON on SQLite (so fast tests can run on SQLite while production uses Postgres).

Tables (19 base, per §8):
 1 campaigns          2 onboarding_profiles  3 attributes        4 field_mappings
 5 fonts              6 discovery_sources    7 job_postings      8 resume_variants
 9 generated_materials 10 revision_sessions  11 applications     12 application_screenshots
13 decisions          14 outcome_events      15 agent_runs       16 detection_events
17 tool_settings      18 dormant_surface_backlog                 19 app_config
Plus derived: pending_actions.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import JSON

#: JSONB on Postgres, plain JSON elsewhere (SQLite test runs).
JSONType = JSON().with_variant(JSONB(), "postgresql")


def _utcnow() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    """Single declarative base for the whole schema."""


# 1 -------------------------------------------------------------------------
class CampaignModel(Base):
    __tablename__ = "campaigns"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    run_mode: Mapped[str] = mapped_column(String(32), default="continuous")
    throughput_target: Mapped[int] = mapped_column(Integer, default=15)
    exploration_budget: Mapped[float] = mapped_column(Float, default=0.1)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    criteria: Mapped[dict] = mapped_column(JSONType, default=dict)
    schedule: Mapped[dict] = mapped_column(JSONType, default=dict)
    learning_state: Mapped[dict] = mapped_column(JSONType, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


# 2 -------------------------------------------------------------------------
class OnboardingProfileModel(Base):
    __tablename__ = "onboarding_profiles"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    campaign_id: Mapped[str] = mapped_column(ForeignKey("campaigns.id"), nullable=False, index=True)
    completion_flag: Mapped[bool] = mapped_column(Boolean, default=False)
    wizard_state: Mapped[dict] = mapped_column(JSONType, default=dict)
    intake: Mapped[dict] = mapped_column(JSONType, default=dict)


# 3 -------------------------------------------------------------------------
class AttributeModel(Base):
    __tablename__ = "attributes"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    campaign_id: Mapped[str] = mapped_column(ForeignKey("campaigns.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    value: Mapped[str] = mapped_column(Text, default="")
    is_integral: Mapped[bool] = mapped_column(Boolean, default=False)
    is_sensitive: Mapped[bool] = mapped_column(Boolean, default=False)
    aliases: Mapped[list] = mapped_column(JSONType, default=list)


# 4 -------------------------------------------------------------------------
class FieldMappingModel(Base):
    __tablename__ = "field_mappings"
    # Hot lookup: list_for_site / find scan by site_key.
    __table_args__ = (Index("ix_field_mappings_site_key", "site_key"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    # nullable for globally-learned mappings (values stay per-campaign).
    campaign_id: Mapped[str | None] = mapped_column(ForeignKey("campaigns.id"), nullable=True, index=True)
    attribute_id: Mapped[str | None] = mapped_column(ForeignKey("attributes.id"), nullable=True)
    site_key: Mapped[str] = mapped_column(String(255), nullable=False)
    field_selector: Mapped[str] = mapped_column(Text, nullable=False)
    mapping_metadata: Mapped[dict] = mapped_column(JSONType, default=dict)


# 5 -------------------------------------------------------------------------
class FontModel(Base):
    __tablename__ = "fonts"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    install_status: Mapped[str] = mapped_column(String(32), default="pending")
    environment: Mapped[str] = mapped_column(String(64), default="default")
    font_metadata: Mapped[dict] = mapped_column(JSONType, default=dict)


# 6 -------------------------------------------------------------------------
class DiscoverySourceModel(Base):
    __tablename__ = "discovery_sources"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    campaign_id: Mapped[str] = mapped_column(ForeignKey("campaigns.id"), nullable=False, index=True)
    source_key: Mapped[str] = mapped_column(String(128), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    yield_stats: Mapped[dict] = mapped_column(JSONType, default=dict)


# 7 -------------------------------------------------------------------------
class JobPostingModel(Base):
    __tablename__ = "job_postings"
    # Hot lookup: list_unscored_for_campaign filters by (campaign_id, viability_score).
    __table_args__ = (
        Index("ix_job_postings_campaign_viability", "campaign_id", "viability_score"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    campaign_id: Mapped[str] = mapped_column(ForeignKey("campaigns.id"), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    company: Mapped[str] = mapped_column(String(512), default="")
    location: Mapped[str | None] = mapped_column(String(512), nullable=True)
    work_mode: Mapped[str | None] = mapped_column(String(64), nullable=True)
    salary: Mapped[str | None] = mapped_column(String(128), nullable=True)
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    source_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    viability_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    normalized: Mapped[dict] = mapped_column(JSONType, default=dict)
    rationale: Mapped[dict] = mapped_column(JSONType, default=dict)
    description: Mapped[str] = mapped_column(Text, default="")


# 8 -------------------------------------------------------------------------
class ResumeVariantModel(Base):
    __tablename__ = "resume_variants"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    campaign_id: Mapped[str] = mapped_column(ForeignKey("campaigns.id"), nullable=False, index=True)
    storage_path: Mapped[str] = mapped_column(Text, nullable=False)
    parent_id: Mapped[str | None] = mapped_column(ForeignKey("resume_variants.id"), nullable=True)
    targeted_jd_signature: Mapped[str | None] = mapped_column(Text, nullable=True)
    approved: Mapped[bool] = mapped_column(Boolean, default=False)
    fit_scores: Mapped[dict] = mapped_column(JSONType, default=dict)


# 9 -------------------------------------------------------------------------
class GeneratedMaterialModel(Base):
    __tablename__ = "generated_materials"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    campaign_id: Mapped[str] = mapped_column(ForeignKey("campaigns.id"), nullable=False, index=True)
    application_id: Mapped[str | None] = mapped_column(ForeignKey("applications.id"), nullable=True, index=True)
    type: Mapped[str] = mapped_column(String(32), nullable=False)  # resume/cover_letter/screening_answer
    content: Mapped[str | None] = mapped_column(Text, nullable=True)
    storage_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    approved: Mapped[bool] = mapped_column(Boolean, default=False)
    redline_state: Mapped[dict] = mapped_column(JSONType, default=dict)
    # Advisory-only learned-item provenance ("What I drew on", FR-MIND-5/-11,
    # FR-OBS-2). A bounded list of {kind,label,ref}; empty by default so a draft
    # made without an agent-memory substrate stores nothing extra.
    provenance: Mapped[list] = mapped_column(JSONType, default=list)


# 10 ------------------------------------------------------------------------
class RevisionSessionModel(Base):
    __tablename__ = "revision_sessions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    material_id: Mapped[str] = mapped_column(ForeignKey("generated_materials.id"), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), default="open")
    redline_state: Mapped[dict] = mapped_column(JSONType, default=dict)
    turns: Mapped[list] = mapped_column(JSONType, default=list)


# 11 ------------------------------------------------------------------------
class ApplicationModel(Base):
    __tablename__ = "applications"
    # Hot lookup: list_by_status filters by (campaign_id, status).
    __table_args__ = (
        Index("ix_applications_campaign_status", "campaign_id", "status"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    campaign_id: Mapped[str] = mapped_column(ForeignKey("campaigns.id"), nullable=False, index=True)
    posting_id: Mapped[str | None] = mapped_column(ForeignKey("job_postings.id"), nullable=True, index=True)
    role_name: Mapped[str | None] = mapped_column(String(512), nullable=True)
    job_title: Mapped[str | None] = mapped_column(String(512), nullable=True)
    work_mode: Mapped[str | None] = mapped_column(String(64), nullable=True)
    root_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    resume_variant_id: Mapped[str | None] = mapped_column(ForeignKey("resume_variants.id"), nullable=True)
    status: Mapped[str] = mapped_column(String(64), default="DISCOVERED")  # §7 state machine
    sandbox_session_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    attributes_used: Mapped[dict] = mapped_column(JSONType, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)


# 12 ------------------------------------------------------------------------
class ApplicationScreenshotModel(Base):
    __tablename__ = "application_screenshots"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    application_id: Mapped[str] = mapped_column(ForeignKey("applications.id"), nullable=False, index=True)
    page_ref: Mapped[str] = mapped_column(Text, nullable=False)
    page_url: Mapped[str] = mapped_column(Text, default="")
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


# 13 ------------------------------------------------------------------------
class DecisionModel(Base):
    __tablename__ = "decisions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    application_id: Mapped[str] = mapped_column(ForeignKey("applications.id"), nullable=False, index=True)
    type: Mapped[str] = mapped_column(String(16), nullable=False)  # approve/decline
    feedback_text: Mapped[str] = mapped_column(Text, default="")
    criteria_delta: Mapped[dict] = mapped_column(JSONType, default=dict)


# 14 ------------------------------------------------------------------------
class OutcomeEventModel(Base):
    __tablename__ = "outcome_events"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    application_id: Mapped[str] = mapped_column(ForeignKey("applications.id"), nullable=False, index=True)
    type: Mapped[str] = mapped_column(String(32), nullable=False)
    source: Mapped[str] = mapped_column(String(16), default="auto")  # auto/manual
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


# 15 ------------------------------------------------------------------------
class AgentRunModel(Base):
    __tablename__ = "agent_runs"
    # Hot lookup: latest / count_pipelines_started_on order/filter by (campaign_id, timestamp).
    __table_args__ = (
        Index("ix_agent_runs_campaign_timestamp", "campaign_id", "timestamp"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    campaign_id: Mapped[str] = mapped_column(ForeignKey("campaigns.id"), nullable=False, index=True)
    intent_sentence: Mapped[dict] = mapped_column(JSONType, default=dict)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


# 16 ------------------------------------------------------------------------
class DetectionEventModel(Base):
    __tablename__ = "detection_events"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    application_id: Mapped[str] = mapped_column(ForeignKey("applications.id"), nullable=False, index=True)
    signal_type: Mapped[str] = mapped_column(String(64), nullable=False)
    signal_detail: Mapped[dict] = mapped_column(JSONType, default=dict)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


# 17 ------------------------------------------------------------------------
class ToolSettingModel(Base):
    __tablename__ = "tool_settings"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tool_key: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)


# 18 ------------------------------------------------------------------------
class DormantSurfaceBacklogModel(Base):
    __tablename__ = "dormant_surface_backlog"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    surface_name: Mapped[str] = mapped_column(String(255), nullable=False)
    requirement_ids: Mapped[list] = mapped_column(JSONType, default=list)
    status: Mapped[str] = mapped_column(String(32), default="dormant")
    wiring_notes: Mapped[dict] = mapped_column(JSONType, default=dict)


# 19 ------------------------------------------------------------------------
class AppConfigModel(Base):
    __tablename__ = "app_config"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    key: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    value: Mapped[dict] = mapped_column(JSONType, default=dict)


# 20 ------------------------------------------------------------------------
class CredentialModel(Base):
    """Sealed per-site/tenant credential set (FR-VAULT-1/3, FR-CRIT-4, NFR-PRIV-1).

    Holds the libsodium-SEALED ``username``/``secret`` blobs (base64) + metadata.
    NEVER stores plaintext. Campaign-scoped (FR-CRIT-4) and keyed per tenant/site so
    Workday's per-tenant credential sets are first-class. The row survives restarts so
    24/7 unattended operation (FR-VAULT-3) does not lose banked credentials.
    """

    __tablename__ = "credentials"
    # Keep the SQLite (create_all) lane in sync with the Postgres migration
    # (alembic/versions/0003_credentials.py): one credential set per
    # (campaign, tenant) so banking the same tenant is a consistent upsert.
    __table_args__ = (
        UniqueConstraint(
            "campaign_id", "tenant_key", name="uq_credentials_campaign_tenant"
        ),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    campaign_id: Mapped[str] = mapped_column(
        ForeignKey("campaigns.id"), nullable=False, index=True
    )
    tenant_key: Mapped[str] = mapped_column(String(255), nullable=False)
    sealed_username: Mapped[str] = mapped_column(Text, nullable=False)
    sealed_secret: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str] = mapped_column(String(32), default="manual")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


# derived -------------------------------------------------------------------
class PendingActionModel(Base):
    __tablename__ = "pending_actions"
    # Hot lookups: list_open filters by (campaign_id, resolved); dedup matching by
    # (campaign_id, dedup_key) — both promoted to real indexes (no JSONB payload scan).
    __table_args__ = (
        Index("ix_pending_actions_campaign_resolved", "campaign_id", "resolved"),
        Index("ix_pending_actions_campaign_dedup", "campaign_id", "dedup_key"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    campaign_id: Mapped[str] = mapped_column(ForeignKey("campaigns.id"), nullable=False, index=True)
    application_id: Mapped[str | None] = mapped_column(ForeignKey("applications.id"), nullable=True, index=True)
    kind: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    # Promoted from inside ``payload`` to a real indexed column (FR scale): dedup
    # matching is now a direct (campaign_id, dedup_key) lookup, not an O(open) scan.
    dedup_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    payload: Mapped[dict] = mapped_column(JSONType, default=dict)
    resolved: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


ALL_TABLES = [
    CampaignModel,
    OnboardingProfileModel,
    AttributeModel,
    FieldMappingModel,
    FontModel,
    DiscoverySourceModel,
    JobPostingModel,
    ResumeVariantModel,
    GeneratedMaterialModel,
    RevisionSessionModel,
    ApplicationModel,
    ApplicationScreenshotModel,
    DecisionModel,
    OutcomeEventModel,
    AgentRunModel,
    DetectionEventModel,
    ToolSettingModel,
    DormantSurfaceBacklogModel,
    AppConfigModel,
    CredentialModel,
    PendingActionModel,
]
