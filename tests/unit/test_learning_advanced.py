"""AdvancedLearningService Phase-4 depth tests (FR-LEARN-2/3/4/5, §10).

Covers the real-conversion loop (approval PLUS submission, never bare approval),
rich converting-role signature mining, cross-input folds (decline/revision/soft-
error/source-yield), continuous attribute reconciliation with conflict detection,
and the sensitive (EEO) never-auto-learn boundary.
"""

from __future__ import annotations

import pytest

from applicant.adapters.embedding.local_embedding import LocalEmbedding
from applicant.adapters.storage.in_memory import InMemoryStorage
from applicant.application.services.learning_advanced import AdvancedLearningService
from applicant.application.services.learning_service import LearningService
from applicant.core.entities.application import Application
from applicant.core.entities.attribute import Attribute, AttributeStore
from applicant.core.entities.campaign import Campaign
from applicant.core.entities.job_posting import JobPosting
from applicant.core.entities.learning_model import LearningModel
from applicant.core.entities.outcome_event import OutcomeEvent, OutcomeSource
from applicant.core.ids import (
    ApplicationId,
    AttributeId,
    CampaignId,
    JobPostingId,
    OutcomeEventId,
    ResumeVariantId,
    new_id,
)
from applicant.core.state_machine import ApplicationState


@pytest.fixture
def storage() -> InMemoryStorage:
    return InMemoryStorage()


@pytest.fixture
def base(storage) -> LearningService:
    return LearningService(storage, LocalEmbedding())


@pytest.fixture
def advanced(storage, base) -> AdvancedLearningService:
    return AdvancedLearningService(base=base, storage=storage)


@pytest.fixture
def campaign(storage) -> Campaign:
    c = Campaign(id=CampaignId(new_id()), name="c")
    storage.campaigns.add(c)
    storage.commit()
    return c


def _approved_app(campaign_id, **kw) -> Application:
    return Application(
        id=ApplicationId(new_id()),
        campaign_id=campaign_id,
        posting_id=JobPostingId(new_id()),
        status=ApplicationState.APPROVED,
        role_name=kw.get("role_name", "Senior Backend Engineer"),
        job_title=kw.get("job_title"),
        work_mode=kw.get("work_mode", "remote"),
        resume_variant_id=kw.get("resume_variant_id"),
    )


# === real conversion = approval PLUS submission (§10, FR-LEARN-2) ===========
@pytest.mark.unit
def test_bare_approval_is_not_a_conversion(advanced, campaign):
    app = _approved_app(campaign.id)
    model = LearningModel(campaign_id=campaign.id)
    assert advanced.is_conversion(app, []) is False
    after = advanced.record_conversion(model, app, [])
    assert after.converting_role_signature == {}  # needle does not move


@pytest.mark.unit
def test_approval_plus_submission_converts_and_shifts_bias(advanced, campaign):
    app = _approved_app(campaign.id)
    event = OutcomeEvent(
        id=OutcomeEventId(new_id()),
        application_id=app.id,
        type="submitted",
        source=OutcomeSource.AUTO,
    )
    assert advanced.is_conversion(app, [event]) is True
    after = advanced.record_conversion(LearningModel(campaign_id=campaign.id), app, [event])
    assert after.converting_role_signature  # non-empty
    assert after.converting_samples == 1
    assert "role:senior backend engineer" in after.converting_role_signature
    assert "work_mode:remote" in after.converting_role_signature


@pytest.mark.unit
def test_manual_mark_submitted_also_converts(advanced, campaign):
    app = _approved_app(campaign.id)
    event = OutcomeEvent(
        id=OutcomeEventId(new_id()),
        application_id=app.id,
        type="submitted",
        source=OutcomeSource.MANUAL,
    )
    assert advanced.is_conversion(app, [event]) is True


@pytest.mark.unit
def test_rich_signature_mines_seniority_skills_comp_variant_source(advanced, campaign):
    variant = ResumeVariantId(new_id())
    app = _approved_app(
        campaign.id, job_title="Staff Software Engineer", resume_variant_id=variant
    )
    posting = JobPosting(
        id=app.posting_id,
        campaign_id=campaign.id,
        title="Staff Software Engineer",
        company="Globex",
        source_url="u",
        work_mode="remote",
        location="Austin, TX",
        salary="$200k-$240k",
        description="Python, Kubernetes, AWS. Distributed systems.",
        source_key="jobspy:linkedin",
    )
    event = OutcomeEvent(
        id=OutcomeEventId(new_id()), application_id=app.id, type="submitted"
    )
    after = advanced.record_conversion(
        LearningModel(campaign_id=campaign.id), app, [event], posting=posting
    )
    sig = after.converting_role_signature
    assert "seniority:staff" in sig
    assert "skill:python" in sig and "skill:kubernetes" in sig
    assert "comp:200k+" in sig
    assert f"variant:{variant}" in sig
    assert "source:jobspy:linkedin" in sig
    assert "location:austin, tx" in sig


@pytest.mark.unit
def test_conversion_alignment_biases_similar_roles(advanced, campaign):
    app = _approved_app(campaign.id, job_title="Senior Backend Engineer")
    event = OutcomeEvent(
        id=OutcomeEventId(new_id()), application_id=app.id, type="submitted"
    )
    model = advanced.record_conversion(LearningModel(campaign_id=campaign.id), app, [event])
    similar = _approved_app(campaign.id, job_title="Senior Backend Engineer")
    far = _approved_app(campaign.id, job_title="Pastry Chef", work_mode="onsite")
    assert advanced.conversion_alignment(model, similar) > advanced.conversion_alignment(
        model, far
    )


@pytest.mark.unit
def test_record_and_persist_conversion_survives_reload(advanced, base, storage, campaign):
    app = _approved_app(campaign.id)
    storage.applications.add(app)
    storage.outcomes.add(
        OutcomeEvent(id=OutcomeEventId(new_id()), application_id=app.id, type="submitted")
    )
    storage.commit()
    advanced.record_and_persist_conversion(campaign.id, app)
    # Reload from storage proves per-campaign learning state survives restart.
    reloaded = base.load_model(campaign.id)
    assert reloaded.converting_role_signature
    assert "role:senior backend engineer" in reloaded.converting_role_signature


@pytest.mark.unit
def test_signature_summary_groups_by_facet(advanced, campaign):
    app = _approved_app(campaign.id, job_title="Senior Backend Engineer")
    event = OutcomeEvent(id=OutcomeEventId(new_id()), application_id=app.id, type="submitted")
    model = advanced.record_conversion(LearningModel(campaign_id=campaign.id), app, [event])
    summary = advanced.converting_signature_summary(model)
    assert "senior backend engineer" in summary.get("role", [])
    assert "remote" in summary.get("work_mode", [])


# === cross-input folds (FR-LEARN-3) ========================================
@pytest.mark.unit
def test_fold_revision_feedback_learns_user_edits(advanced, campaign):
    model = LearningModel(campaign_id=campaign.id)
    model = advanced.fold_revision_feedback(
        model,
        edits=[
            {"op": "add", "text": "leadership mentoring"},
            {"op": "subtract", "text": "buzzword synergy"},
        ],
    )
    stats = model.feature_stats
    assert any("leadership" in k for k in stats)
    # the added token reads as approved, the subtracted as declined
    add_key = next(k for k in stats if "leadership" in k)
    assert any(lbl.endswith(":approve") for lbl in stats[add_key])


@pytest.mark.unit
def test_fold_soft_error_and_source_yield(advanced, campaign):
    model = LearningModel(campaign_id=campaign.id)
    model = advanced.fold_soft_error_resolution(
        model, attribute_name="Work authorization", site_key="workday"
    )
    assert any("required_field" in k for k in model.feature_stats)
    model = advanced.fold_source_yield(model, {"jobspy:indeed": {"matches": 3, "submissions": 1}})
    assert model.source_weights["jobspy:indeed"] > 0


# === continuous attribute reconciliation (FR-LEARN-4 / FR-FB-3 / FR-ATTR-6) =
@pytest.mark.unit
def test_reconcile_auto_applies_non_integral_and_gates_integral(advanced, campaign):
    store = AttributeStore(campaign_id=campaign.id)
    store, result = advanced.reconcile_inputs(
        store,
        [
            {"name": "years_python", "value": "8", "source": "resume", "is_integral": False},
            {"name": "legal_name", "value": "Jane Q.", "source": "chat", "is_integral": True},
        ],
    )
    assert len(result.applied) == 1 and result.applied[0].name == "years_python"
    assert len(result.pending) == 1 and result.pending[0].name == "legal_name"
    assert store.find("years_python") is not None
    assert store.find("legal_name") is None  # integral held at the gate


@pytest.mark.unit
def test_reconcile_surfaces_conflict_without_overwrite(advanced, campaign):
    store = AttributeStore(
        campaign_id=campaign.id,
        attributes=(
            Attribute(
                id=AttributeId(new_id()),
                campaign_id=campaign.id,
                name="preferred_location",
                value="Remote",
            ),
        ),
    )
    store, result = advanced.reconcile_inputs(
        store,
        [{"name": "preferred_location", "value": "Austin", "source": "survey"}],
    )
    assert result.conflicts and result.conflicts[0].current_value == "Remote"
    assert not result.applied
    assert store.find("preferred_location").value == "Remote"  # untouched


@pytest.mark.unit
def test_reconcile_skips_sensitive_eeo(advanced, campaign):
    store = AttributeStore(campaign_id=campaign.id)
    store, result = advanced.reconcile_inputs(
        store, [{"name": "Gender", "value": "Male", "source": "resume"}]
    )
    assert "Gender" in result.skipped
    assert not result.applied and not result.pending
    assert store.find("Gender") is None  # FR-ATTR-6 never auto-learned
