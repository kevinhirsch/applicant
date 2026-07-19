"""Unit tests for all SQLAlchemy ORM model classes in applicant.adapters.storage.models."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy import inspect as sa_inspect

from applicant.adapters.storage.models import (
    Base,
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
    PendingActionModel,
    CredentialModel,
    ActionEventModel,
    SubmissionSnapshotModel,
    RejectionSignalModel,
    GhostingSignalModel,
    FollowUpModel,
    PortfolioAttachmentModel,
    ScreeningAnswerLibraryModel,
    JSONType,
    _utcnow,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clear_module_state() -> None:
    """Clear any global module state before each test."""
    # No-op: models are declarative so there is no runtime state to clear.
    # This fixture exists so future module-level state has a home.
    pass


# ---------------------------------------------------------------------------
# Unit: _utcnow helper
# ---------------------------------------------------------------------------


class TestUtcnow:
    """Tests for the _utcnow helper function."""

    @pytest.mark.unit
    def test_returns_aware_datetime(self) -> None:
        dt = _utcnow()
        assert isinstance(dt, datetime)
        assert dt.tzinfo is not None

    @pytest.mark.unit
    def test_returns_utc_timezone(self) -> None:
        dt = _utcnow()
        assert dt.tzinfo == timezone.utc or dt.utcoffset().total_seconds() == 0.0

    @pytest.mark.unit
    def test_returns_recent_time(self) -> None:
        now = datetime.now(timezone.utc)
        dt = _utcnow()
        diff = abs((now - dt).total_seconds())
        assert diff < 5.0, f"_utcnow produced a delta of {diff} seconds"


# ---------------------------------------------------------------------------
# Unit: JSONType
# ---------------------------------------------------------------------------


class TestJSONType:
    """Tests for the JSONType variant type."""

    @pytest.mark.unit
    def test_is_json_instance(self) -> None:
        from sqlalchemy.types import JSON

        assert isinstance(JSONType, JSON)


# ---------------------------------------------------------------------------
# Unit: declarative / tablename / base subclass
# ---------------------------------------------------------------------------


class TestDeclarativeBase:
    """Confirm Base works as a declarative base."""

    @pytest.mark.unit
    def test_base_has_metadata(self) -> None:
        assert hasattr(Base, "metadata")


# Table names and Base-subclass check for every model.
MODEL_TABLENAMES: list[tuple[type, str]] = [
    (CampaignModel, "campaigns"),
    (OnboardingProfileModel, "onboarding_profiles"),
    (AttributeModel, "attributes"),
    (FieldMappingModel, "field_mappings"),
    (FontModel, "fonts"),
    (DiscoverySourceModel, "discovery_sources"),
    (JobPostingModel, "job_postings"),
    (ResumeVariantModel, "resume_variants"),
    (GeneratedMaterialModel, "generated_materials"),
    (RevisionSessionModel, "revision_sessions"),
    (ApplicationModel, "applications"),
    (ApplicationScreenshotModel, "application_screenshots"),
    (DecisionModel, "decisions"),
    (OutcomeEventModel, "outcome_events"),
    (AgentRunModel, "agent_runs"),
    (DetectionEventModel, "detection_events"),
    (ToolSettingModel, "tool_settings"),
    (DormantSurfaceBacklogModel, "dormant_surface_backlog"),
    (AppConfigModel, "app_config"),
    (PendingActionModel, "pending_actions"),
    (CredentialModel, "credentials"),
    (ActionEventModel, "action_events"),
    (SubmissionSnapshotModel, "submission_snapshots"),
    (RejectionSignalModel, "rejection_signals"),
    (GhostingSignalModel, "ghosting_signals"),
    (FollowUpModel, "follow_ups"),
    (PortfolioAttachmentModel, "portfolio_attachments"),
    (ScreeningAnswerLibraryModel, "screening_answer_library"),
]


class TestModelRegistration:
    """Every model class has __tablename__ and is a subclass of Base."""

    @pytest.mark.unit
    @pytest.mark.parametrize("model_cls,expected_table", MODEL_TABLENAMES)
    def test_has_tablename_and_is_base_subclass(
        self, model_cls: type, expected_table: str
    ) -> None:
        assert issubclass(model_cls, Base), f"{model_cls.__name__} is not a Base subclass"
        assert model_cls.__tablename__ == expected_table, (
            f"{model_cls.__name__}.__tablename__ expected {expected_table!r}, "
            f"got {model_cls.__tablename__!r}"
        )


# ---------------------------------------------------------------------------
# Unit: per-model column checks
# ---------------------------------------------------------------------------


class TestCampaignModel:
    """campaigns table columns."""

    @pytest.mark.unit
    def test_all_expected_columns(self) -> None:
        expected = {"id", "name", "run_mode", "throughput_target", "exploration_budget",
                    "active", "criteria", "schedule", "learning_state", "created_at"}
        mapper = CampaignModel.__mapper__
        actual = set(c.key for c in mapper.columns)
        assert actual == expected, f"Diff: expected={expected - actual}, extra={actual - expected}"

    @pytest.mark.unit
    def test_id_is_string_primary_key(self) -> None:
        col = CampaignModel.__mapper__.columns["id"]
        assert col.primary_key
        assert isinstance(col.type, col.type.__class__)
        assert str(col.type).lower().startswith("varchar")

    @pytest.mark.unit
    def test_created_at_is_timezone_aware_datetime(self) -> None:
        col = CampaignModel.__mapper__.columns["created_at"]
        assert "timezone" in str(col.type).lower() or col.type.timezone


class TestOnboardingProfileModel:
    """onboarding_profiles table: UniqueConstraint on campaign_id."""

    @pytest.mark.unit
    def test_has_unique_constraint_on_campaign_id(self) -> None:
        constraints = OnboardingProfileModel.__table__.constraints
        unique_names = {c.name for c in constraints if hasattr(c, "columns")}
        assert "uq_onboarding_profiles_campaign" in unique_names

    @pytest.mark.unit
    def test_campaign_id_is_fk(self) -> None:
        col = OnboardingProfileModel.__mapper__.columns["campaign_id"]
        assert col.foreign_keys

    @pytest.mark.unit
    def test_wizard_state_is_json(self) -> None:
        col = OnboardingProfileModel.__mapper__.columns["wizard_state"]
        assert "JSON" in str(col.type).upper()


class TestAttributeModel:
    """attributes table: is_sensitive, is_integral, aliases."""

    @pytest.mark.unit
    def test_has_is_sensitive(self) -> None:
        mapper = AttributeModel.__mapper__
        assert "is_sensitive" in mapper.columns
        col = mapper.columns["is_sensitive"]
        assert "BOOL" in str(col.type).upper()

    @pytest.mark.unit
    def test_has_is_integral(self) -> None:
        mapper = AttributeModel.__mapper__
        assert "is_integral" in mapper.columns
        col = mapper.columns["is_integral"]
        assert "BOOL" in str(col.type).upper()

    @pytest.mark.unit
    def test_has_aliases(self) -> None:
        mapper = AttributeModel.__mapper__
        assert "aliases" in mapper.columns
        col = mapper.columns["aliases"]
        assert "JSON" in str(col.type).upper()


class TestFieldMappingModel:
    """field_mappings table: Index on site_key."""

    @pytest.mark.unit
    def test_has_index_on_site_key(self) -> None:
        indexes = FieldMappingModel.__table__.indexes
        index_names = {ix.name for ix in indexes}
        assert "ix_field_mappings_site_key" in index_names

    @pytest.mark.unit
    def test_site_key_is_string_not_null(self) -> None:
        col = FieldMappingModel.__mapper__.columns["site_key"]
        assert not col.nullable
        assert "VARCHAR" in str(col.type).upper()


class TestFontModel:
    """fonts table: install_status, environment, font_metadata."""

    @pytest.mark.unit
    def test_has_expected_columns(self) -> None:
        expected = {"id", "name", "install_status", "environment", "font_metadata"}
        actual = set(FontModel.__mapper__.columns.keys())
        assert expected.issubset(actual), f"Missing: {expected - actual}"

    @pytest.mark.unit
    def test_install_status_default_pending(self) -> None:
        col = FontModel.__mapper__.columns["install_status"]
        assert col.default is not None
        assert col.default.arg == "pending"

    @pytest.mark.unit
    def test_font_metadata_is_json(self) -> None:
        col = FontModel.__mapper__.columns["font_metadata"]
        assert "JSON" in str(col.type).upper()


class TestDiscoverySourceModel:
    """discovery_sources table: UniqueConstraint on (campaign_id, source_key)."""

    @pytest.mark.unit
    def test_has_unique_on_campaign_and_source(self) -> None:
        constraints = DiscoverySourceModel.__table__.constraints
        unique_names = {c.name for c in constraints if hasattr(c, "columns")}
        assert "uq_discovery_sources_campaign_source" in unique_names
        # Verify columns in the constraint
        for c in constraints:
            if c.name == "uq_discovery_sources_campaign_source":
                col_names = [col.name for col in c.columns]
                assert "campaign_id" in col_names
                assert "source_key" in col_names
                break


class TestJobPostingModel:
    """job_postings table: Index on (campaign_id, viability_score)."""

    @pytest.mark.unit
    def test_has_index_on_campaign_and_viability(self) -> None:
        indexes = JobPostingModel.__table__.indexes
        index_names = {ix.name for ix in indexes}
        assert "ix_job_postings_campaign_viability" in index_names

    @pytest.mark.unit
    def test_viability_score_is_nullable_float(self) -> None:
        col = JobPostingModel.__mapper__.columns["viability_score"]
        assert col.nullable


class TestResumeVariantModel:
    """resume_variants table: self-referencing FK parent_id."""

    @pytest.mark.unit
    def test_parent_id_self_referencing_fk(self) -> None:
        col = ResumeVariantModel.__mapper__.columns["parent_id"]
        assert col.foreign_keys
        fk = next(iter(col.foreign_keys))
        assert fk.column.table.name == "resume_variants"

    @pytest.mark.unit
    def test_parent_id_is_nullable(self) -> None:
        col = ResumeVariantModel.__mapper__.columns["parent_id"]
        assert col.nullable


class TestGeneratedMaterialModel:
    """generated_materials table: type (length 32), content, provenance."""

    @pytest.mark.unit
    def test_type_column_length_32(self) -> None:
        col = GeneratedMaterialModel.__mapper__.columns["type"]
        assert not col.nullable
        assert str(col.type).lower().startswith("varchar")
        assert col.type.length == 32

    @pytest.mark.unit
    def test_has_content_column(self) -> None:
        mapper = GeneratedMaterialModel.__mapper__
        assert "content" in mapper.columns
        col = mapper.columns["content"]
        assert col.nullable

    @pytest.mark.unit
    def test_has_provenance(self) -> None:
        mapper = GeneratedMaterialModel.__mapper__
        assert "provenance" in mapper.columns
        col = mapper.columns["provenance"]
        assert "JSON" in str(col.type).upper()

    @pytest.mark.unit
    def test_default_provenance_config(self) -> None:
        """Provenance column is JSON and has a non-null default (the callable list factory)."""
        col = GeneratedMaterialModel.__mapper__.columns["provenance"]
        assert col.default is not None
        assert "JSON" in str(col.type).upper()


class TestRevisionSessionModel:
    """revision_sessions table: FK to generated_materials."""

    @pytest.mark.unit
    def test_material_id_fk_to_generated_materials(self) -> None:
        col = RevisionSessionModel.__mapper__.columns["material_id"]
        assert col.foreign_keys
        fk = next(iter(col.foreign_keys))
        assert fk.column.table.name == "generated_materials"


class TestApplicationModel:
    """applications table: FK to job_postings and campaign."""

    @pytest.mark.unit
    def test_posting_id_fk_to_job_postings(self) -> None:
        col = ApplicationModel.__mapper__.columns["posting_id"]
        assert col.foreign_keys
        fk = next(iter(col.foreign_keys))
        assert fk.column.table.name == "job_postings"

    @pytest.mark.unit
    def test_campaign_id_fk_to_campaigns(self) -> None:
        col = ApplicationModel.__mapper__.columns["campaign_id"]
        assert col.foreign_keys
        fk = next(iter(col.foreign_keys))
        assert fk.column.table.name == "campaigns"

    @pytest.mark.unit
    def test_has_index_on_campaign_and_status(self) -> None:
        indexes = ApplicationModel.__table__.indexes
        index_names = {ix.name for ix in indexes}
        assert "ix_applications_campaign_status" in index_names


class TestApplicationScreenshotModel:
    """application_screenshots table: FK to applications."""

    @pytest.mark.unit
    def test_application_id_fk_to_applications(self) -> None:
        col = ApplicationScreenshotModel.__mapper__.columns["application_id"]
        assert col.foreign_keys
        fk = next(iter(col.foreign_keys))
        assert fk.column.table.name == "applications"


class TestDecisionModel:
    """decisions table: FK to applications."""

    @pytest.mark.unit
    def test_application_id_fk_to_applications(self) -> None:
        col = DecisionModel.__mapper__.columns["application_id"]
        assert col.foreign_keys
        fk = next(iter(col.foreign_keys))
        assert fk.column.table.name == "applications"

    @pytest.mark.unit
    def test_type_has_length_16(self) -> None:
        col = DecisionModel.__mapper__.columns["type"]
        assert col.type.length == 16


class TestOutcomeEventModel:
    """outcome_events table: FK to applications."""

    @pytest.mark.unit
    def test_application_id_fk_to_applications(self) -> None:
        col = OutcomeEventModel.__mapper__.columns["application_id"]
        assert col.foreign_keys
        fk = next(iter(col.foreign_keys))
        assert fk.column.table.name == "applications"


class TestAgentRunModel:
    """agent_runs table: FK to campaigns, index on (campaign_id, timestamp)."""

    @pytest.mark.unit
    def test_campaign_id_fk_to_campaigns(self) -> None:
        col = AgentRunModel.__mapper__.columns["campaign_id"]
        assert col.foreign_keys
        fk = next(iter(col.foreign_keys))
        assert fk.column.table.name == "campaigns"

    @pytest.mark.unit
    def test_has_index_on_campaign_and_timestamp(self) -> None:
        indexes = AgentRunModel.__table__.indexes
        index_names = {ix.name for ix in indexes}
        assert "ix_agent_runs_campaign_timestamp" in index_names


class TestDetectionEventModel:
    """detection_events table: FK to applications."""

    @pytest.mark.unit
    def test_application_id_fk_to_applications(self) -> None:
        col = DetectionEventModel.__mapper__.columns["application_id"]
        assert col.foreign_keys
        fk = next(iter(col.foreign_keys))
        assert fk.column.table.name == "applications"


class TestToolSettingModel:
    """tool_settings table: basic columns."""

    @pytest.mark.unit
    def test_has_expected_columns(self) -> None:
        expected = {"id", "tool_key", "enabled"}
        actual = set(ToolSettingModel.__mapper__.columns.keys())
        assert actual == expected, f"Diff: expected={expected - actual}, extra={actual - expected}"

    @pytest.mark.unit
    def test_tool_key_is_unique(self) -> None:
        col = ToolSettingModel.__mapper__.columns["tool_key"]
        assert col.unique


class TestDormantSurfaceBacklogModel:
    """dormant_surface_backlog table: basic columns."""

    @pytest.mark.unit
    def test_has_expected_columns(self) -> None:
        expected = {"id", "surface_name", "requirement_ids", "status", "wiring_notes"}
        actual = set(DormantSurfaceBacklogModel.__mapper__.columns.keys())
        assert actual == expected, f"Diff: expected={expected - actual}, extra={actual - expected}"

    @pytest.mark.unit
    def test_surface_name_is_not_null(self) -> None:
        col = DormantSurfaceBacklogModel.__mapper__.columns["surface_name"]
        assert not col.nullable


class TestAppConfigModel:
    """app_config table: basic columns."""

    @pytest.mark.unit
    def test_has_expected_columns(self) -> None:
        expected = {"id", "key", "value"}
        actual = set(AppConfigModel.__mapper__.columns.keys())
        assert actual == expected, f"Diff: expected={expected - actual}, extra={actual - expected}"

    @pytest.mark.unit
    def test_key_is_unique(self) -> None:
        col = AppConfigModel.__mapper__.columns["key"]
        assert col.unique


class TestPendingActionModel:
    """pending_actions table: derived model with expected columns."""

    @pytest.mark.unit
    def test_has_expected_columns(self) -> None:
        expected = {"id", "campaign_id", "application_id", "kind", "title",
                    "dedup_key", "payload", "resolved", "created_at"}
        actual = set(PendingActionModel.__mapper__.columns.keys())
        assert actual == expected, f"Diff: expected={expected - actual}, extra={actual - expected}"

    @pytest.mark.unit
    def test_campaign_id_fk_to_campaigns(self) -> None:
        col = PendingActionModel.__mapper__.columns["campaign_id"]
        assert col.foreign_keys
        fk = next(iter(col.foreign_keys))
        assert fk.column.table.name == "campaigns"

    @pytest.mark.unit
    def test_has_indexes(self) -> None:
        indexes = PendingActionModel.__table__.indexes
        index_names = {ix.name for ix in indexes}
        assert "ix_pending_actions_campaign_resolved" in index_names
        assert "ix_pending_actions_campaign_dedup" in index_names


# ---------------------------------------------------------------------------
# Unit: CredentialModel (has UniqueConstraint)
# ---------------------------------------------------------------------------


class TestCredentialModel:
    """credentials table: UniqueConstraint on (campaign_id, tenant_key)."""

    @pytest.mark.unit
    def test_has_unique_on_campaign_and_tenant(self) -> None:
        constraints = CredentialModel.__table__.constraints
        unique_names = {c.name for c in constraints if hasattr(c, "columns")}
        assert "uq_credentials_campaign_tenant" in unique_names


# ---------------------------------------------------------------------------
# Integration: create_all on SQLite in-memory
# ---------------------------------------------------------------------------


class TestCreateAll:
    """Base.metadata can create all tables on SQLite in-memory."""

    @pytest.mark.unit
    def test_create_all_on_sqlite(self) -> None:
        engine = create_engine("sqlite://")
        Base.metadata.create_all(bind=engine)
        inspector = sa_inspect(engine)
        table_names = inspector.get_table_names()

        # All 28 tables from ALL_TABLES should be present.
        expected_tables = {
            "campaigns",
            "onboarding_profiles",
            "attributes",
            "field_mappings",
            "fonts",
            "discovery_sources",
            "job_postings",
            "resume_variants",
            "generated_materials",
            "revision_sessions",
            "applications",
            "application_screenshots",
            "decisions",
            "outcome_events",
            "agent_runs",
            "detection_events",
            "tool_settings",
            "dormant_surface_backlog",
            "app_config",
            "pending_actions",
            "credentials",
            "action_events",
            "submission_snapshots",
            "rejection_signals",
            "ghosting_signals",
            "follow_ups",
            "portfolio_attachments",
            "screening_answer_library",
        }
        actual = set(table_names)
        assert actual == expected_tables, (
            f"Missing: {expected_tables - actual}, Extra: {actual - expected_tables}"
        )

    @pytest.mark.unit
    def test_create_all_is_idempotent(self) -> None:
        """Calling create_all twice should not raise."""
        engine = create_engine("sqlite://")
        Base.metadata.create_all(bind=engine)
        Base.metadata.create_all(bind=engine)  # second call
        inspector = sa_inspect(engine)
        assert len(inspector.get_table_names()) >= 20


# ---------------------------------------------------------------------------
# Unit: module-level exports
# ---------------------------------------------------------------------------


class TestModuleExports:
    """Key names are importable from the models module."""

    @pytest.mark.unit
    def test_base_exported(self) -> None:
        from applicant.adapters.storage import models

        assert hasattr(models, "Base")
        assert hasattr(models, "CampaignModel")
        assert hasattr(models, "PendingActionModel")
        assert hasattr(models, "ALL_TABLES")

    @pytest.mark.unit
    def test_all_tables_is_list_of_models(self) -> None:
        from applicant.adapters.storage.models import ALL_TABLES

        assert isinstance(ALL_TABLES, list)
        assert len(ALL_TABLES) >= 20
        for cls in ALL_TABLES:
            assert issubclass(cls, Base), f"{cls.__name__} is not a Base subclass"
