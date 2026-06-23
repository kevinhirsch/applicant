"""Learn curated memory from the user's feedback (FR-LEARN-3, FR-MIND-1/-7/-9/-11).

The ``FeedbackSummaryProvider`` maps the user's own stored feedback — digest decline
reasons (FR-DIG-5) and résumé/answer revision instructions (FR-RESUME-8) — into
preference-tagged ``RunSummary`` records; a curation tick over them proposes staged
curated **user-memory** entries (never skills), idempotent on re-tick. With no
feedback present the provider yields nothing and the nudge proposes nothing.
"""

from __future__ import annotations

import pytest

from applicant.adapters.memory.in_memory import InMemoryMemoryStore, InMemorySkillStore
from applicant.adapters.storage.in_memory import InMemoryStorage
from applicant.application.services.curation_service import (
    CurationLedger,
    CurationService,
    MemoryProposal,
    SkillProposal,
)
from applicant.application.services.feedback_history import FeedbackSummaryProvider
from applicant.core.entities.application import Application
from applicant.core.entities.campaign import Campaign
from applicant.core.entities.decision import Decision, DecisionType
from applicant.core.entities.generated_document import DocumentType, GeneratedDocument
from applicant.core.entities.revision_session import (
    RevisionSession,
    RevisionStatus,
    RevisionTurn,
)
from applicant.core.ids import (
    ApplicationId,
    CampaignId,
    DecisionId,
    GeneratedDocumentId,
    JobPostingId,
    RevisionSessionId,
    new_id,
)
from applicant.core.state_machine import ApplicationState
from applicant.ports.driven.memory_store import KIND_USER


def _seed_app(storage, *, active=True) -> tuple[CampaignId, Application]:
    cid = CampaignId(new_id())
    storage.campaigns.add(Campaign(id=cid, name="Search", active=active))
    app = Application(
        id=ApplicationId(new_id()),
        campaign_id=cid,
        posting_id=JobPostingId(new_id()),
        status=ApplicationState.SCORED,
        role_name="Backend Engineer",
        job_title="Backend Engineer",
        work_mode="remote",
        root_url="https://acme.myworkdayjobs.com/job/9",
    )
    storage.applications.add(app)
    return cid, app


def _seed_decline(storage, app, text: str) -> None:
    storage.decisions.add(
        Decision(
            id=DecisionId(new_id()),
            application_id=app.id,
            type=DecisionType.DECLINE,
            feedback_text=text,
        )
    )


def _seed_revision(storage, app, cid, *instructions: str) -> None:
    doc = GeneratedDocument(
        id=GeneratedDocumentId(new_id()),
        campaign_id=cid,
        application_id=app.id,
        type=DocumentType.RESUME,
    )
    storage.documents.add(doc)
    storage.revisions.add(
        RevisionSession(
            id=RevisionSessionId(new_id()),
            material_id=doc.id,
            status=RevisionStatus.OPEN,
            turns=tuple(
                RevisionTurn(kind="free_text", instruction=i) for i in instructions
            ),
        )
    )


def _curation(ledger=None) -> CurationService:
    return CurationService(
        memory_store=InMemoryMemoryStore(),
        skill_store=InMemorySkillStore(),
        ledger=ledger or CurationLedger(),
    )


@pytest.mark.unit
def test_provider_maps_declines_and_revisions_to_preference_summaries():
    storage = InMemoryStorage()
    cid, app = _seed_app(storage)
    _seed_decline(storage, app, "Too much travel — I only want fully remote roles.")
    _seed_revision(
        storage, app, cid,
        "Drop the buzzwords from the summary.",
        "Lead with my Python work.",
    )

    summaries = FeedbackSummaryProvider()(storage)

    # One decline + two revision turns -> three preference summaries.
    assert len(summaries) == 3
    assert all(s.is_preference for s in summaries)
    # Preferences are never workflows -> never skill-eligible.
    assert all(s.tool_calls == 0 for s in summaries)
    assert all(s.campaign_id == str(cid) for s in summaries)
    blob = " ".join(s.text for s in summaries)
    assert "fully remote" in blob
    assert "buzzwords" in blob and "Python" in blob
    # Stable, distinct run ids so the curator can dedupe (FR-MIND-7).
    assert len({s.run_id for s in summaries}) == 3


@pytest.mark.unit
def test_provider_is_bounded():
    storage = InMemoryStorage()
    cid, app = _seed_app(storage)
    for i in range(10):
        _seed_decline(storage, app, f"reason {i}")

    summaries = FeedbackSummaryProvider(max_summaries=3)(storage)
    assert len(summaries) == 3


@pytest.mark.unit
def test_provider_skips_inactive_campaign_and_empty_feedback():
    storage = InMemoryStorage()
    # Inactive campaign with feedback -> ignored.
    _, inactive_app = _seed_app(storage, active=False)
    _seed_decline(storage, inactive_app, "ignored")
    # Active campaign, but an APPROVE / blank-feedback decision carries no lesson.
    cid, app = _seed_app(storage)
    storage.decisions.add(
        Decision(
            id=DecisionId(new_id()),
            application_id=app.id,
            type=DecisionType.APPROVE,
            feedback_text="",
        )
    )
    assert FeedbackSummaryProvider()(storage) == []


@pytest.mark.unit
def test_curation_tick_proposes_staged_user_memory_not_skills():
    storage = InMemoryStorage()
    cid, app = _seed_app(storage)
    _seed_decline(storage, app, "I prefer roles that sponsor visas.")
    _seed_revision(storage, app, cid, "Make the cover letter more concise.")

    summaries = FeedbackSummaryProvider()(storage)
    ledger = CurationLedger()
    svc = _curation(ledger)
    result = svc.run_curation_tick(summaries)

    assert result.reviewed == 2
    # Preferences yield curated MEMORY proposals, never skills (FR-MIND-1/-2).
    assert len(result.skill_proposals) == 0
    assert len(result.memory_proposals) >= 1
    assert all(isinstance(p, MemoryProposal) for p in result.memory_proposals)
    # Tagged as the user's own preference memory (KIND_USER), not environment lessons.
    assert all(p.entry.kind == KIND_USER for p in result.memory_proposals)
    # Approval on (default) -> staged for review, nothing auto-applied (FR-MIND-9).
    assert result.auto_applied == 0
    assert result.staged == len(result.memory_proposals)
    assert all(isinstance(p, MemoryProposal) for p in ledger.staged)
    assert not any(isinstance(p, SkillProposal) for p in ledger.staged)


@pytest.mark.unit
def test_curation_tick_is_idempotent_on_retick():
    storage = InMemoryStorage()
    cid, app = _seed_app(storage)
    _seed_decline(storage, app, "Only senior roles, please.")

    provider = FeedbackSummaryProvider()
    ledger = CurationLedger()
    svc = _curation(ledger)

    first = svc.run_curation_tick(provider(storage))
    assert first.reviewed == 1
    staged_after_first = len(ledger.staged)

    # Re-tick over the SAME feedback -> nothing re-reviewed, nothing re-staged.
    second = svc.run_curation_tick(provider(storage))
    assert second.reviewed == 0
    assert second.memory_proposals == ()
    assert len(ledger.staged) == staged_after_first


@pytest.mark.unit
def test_no_feedback_means_no_proposals_and_unchanged_behavior():
    storage = InMemoryStorage()
    _seed_app(storage)  # campaign + application, but no decisions / revisions

    summaries = FeedbackSummaryProvider()(storage)
    assert summaries == []

    svc = _curation()
    result = svc.run_curation_tick(summaries)
    assert result.reviewed == 0
    assert result.memory_proposals == ()
    assert result.skill_proposals == ()
    assert result.staged == 0
