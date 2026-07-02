"""Regression tests for the per-variant A/B scoreboard (design-audit Top-25 #19).

``AdminQueryService.variant_library`` gains an honestly-computed ``uses`` count
and ``interview_rate`` per resume variant, derived from the SAME real linkage
the tracker board already reads: ``Application.resume_variant_id`` -> the
outcome-event trail (``interview_invited`` / ``offer``), gated to applications
that actually reached a submitted/post-submission state (``TRACKER_STATES``).
No new persistence -- this is a pure read-model addition over existing data,
so these tests are hermetic (``InMemoryStorage``, no real DB).
"""

from __future__ import annotations

from applicant.adapters.orchestration.checkpoint_shim import CheckpointShimOrchestrator
from applicant.adapters.storage.in_memory import InMemoryStorage
from applicant.application.services.admin_query_service import AdminQueryService
from applicant.core.entities.application import Application
from applicant.core.entities.outcome_event import OutcomeEvent, OutcomeSource
from applicant.core.entities.resume_variant import ResumeVariant
from applicant.core.ids import (
    ApplicationId,
    CampaignId,
    JobPostingId,
    OutcomeEventId,
    ResumeVariantId,
    new_id,
)
from applicant.core.state_machine import ApplicationState


def _svc():
    return AdminQueryService(InMemoryStorage(), CheckpointShimOrchestrator())


def _app(cid, variant_id, status, *, posting=None):
    return Application(
        id=ApplicationId(new_id()),
        campaign_id=cid,
        posting_id=posting or JobPostingId(new_id()),
        status=status,
        resume_variant_id=variant_id,
    )


def test_variant_with_no_applications_reports_zero_uses_and_no_rate():
    storage = InMemoryStorage()
    cid = CampaignId(new_id())
    variant = ResumeVariant(id=ResumeVariantId(new_id()), campaign_id=cid, storage_path="v.tex")
    storage.resume_variants.add(variant)
    storage.commit()
    svc = AdminQueryService(storage, CheckpointShimOrchestrator())

    lib = {v["variant_id"]: v for v in svc.variant_library(cid)}

    assert lib[str(variant.id)]["uses"] == 0
    assert lib[str(variant.id)]["interview_rate"] is None


def test_variant_use_only_counts_applications_that_reached_a_submitted_state():
    storage = InMemoryStorage()
    cid = CampaignId(new_id())
    variant = ResumeVariant(id=ResumeVariantId(new_id()), campaign_id=cid, storage_path="v.tex")
    storage.resume_variants.add(variant)
    # Still mid-pipeline (material prep) -- picked the variant, but never
    # actually submitted. Must NOT count as a "use".
    storage.applications.add(_app(cid, variant.id, ApplicationState.MATERIAL_PREP))
    # Actually submitted -- counts.
    storage.applications.add(_app(cid, variant.id, ApplicationState.SUBMITTED_BY_USER))
    storage.commit()
    svc = AdminQueryService(storage, CheckpointShimOrchestrator())

    lib = {v["variant_id"]: v for v in svc.variant_library(cid)}

    assert lib[str(variant.id)]["uses"] == 1
    # One use, no positive-signal outcome recorded -> an honest 0%, not None
    # (None is reserved for "no uses at all yet" -- see the zero-uses test above).
    assert lib[str(variant.id)]["interview_rate"] == 0.0


def test_variant_interview_rate_derived_from_real_outcome_trail():
    storage = InMemoryStorage()
    cid = CampaignId(new_id())
    variant = ResumeVariant(id=ResumeVariantId(new_id()), campaign_id=cid, storage_path="v.tex")
    storage.resume_variants.add(variant)

    app_interviewed = _app(cid, variant.id, ApplicationState.AWAITING_RESPONSE)
    app_no_signal = _app(cid, variant.id, ApplicationState.AWAITING_RESPONSE)
    storage.applications.add(app_interviewed)
    storage.applications.add(app_no_signal)
    storage.outcomes.add(
        OutcomeEvent(
            id=OutcomeEventId(new_id()),
            application_id=app_interviewed.id,
            type="interview_invited",
            source=OutcomeSource.AUTO,
        )
    )
    storage.commit()
    svc = AdminQueryService(storage, CheckpointShimOrchestrator())

    lib = {v["variant_id"]: v for v in svc.variant_library(cid)}
    row = lib[str(variant.id)]

    assert row["uses"] == 2
    assert row["interview_rate"] == 50.0


def test_variant_scoreboard_distinguishes_two_variants_by_conversion():
    """The A/B half of #19: two variants, same campaign, different outcomes."""
    storage = InMemoryStorage()
    cid = CampaignId(new_id())
    strong = ResumeVariant(id=ResumeVariantId(new_id()), campaign_id=cid, storage_path="a.tex")
    weak = ResumeVariant(id=ResumeVariantId(new_id()), campaign_id=cid, storage_path="b.tex")
    storage.resume_variants.add(strong)
    storage.resume_variants.add(weak)

    for _ in range(2):
        app = _app(cid, strong.id, ApplicationState.AWAITING_RESPONSE)
        storage.applications.add(app)
        storage.outcomes.add(
            OutcomeEvent(
                id=OutcomeEventId(new_id()),
                application_id=app.id,
                type="offer",
                source=OutcomeSource.AUTO,
            )
        )
    for _ in range(2):
        storage.applications.add(_app(cid, weak.id, ApplicationState.REJECTED))
    storage.commit()
    svc = AdminQueryService(storage, CheckpointShimOrchestrator())

    lib = {v["variant_id"]: v for v in svc.variant_library(cid)}

    assert lib[str(strong.id)]["uses"] == 2
    assert lib[str(strong.id)]["interview_rate"] == 100.0
    assert lib[str(weak.id)]["uses"] == 2
    assert lib[str(weak.id)]["interview_rate"] == 0.0
