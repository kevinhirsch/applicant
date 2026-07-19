"""Unit tests for FeedbackSummaryProvider (FR-MIND-1/-7/-13, FR-LEARN-3, FR-DIG-5, FR-RESUME-8).

Tests the feedback-summary provider in isolation — maps stored user feedback into
preference-tagged ``RunSummary`` records. These tests do NOT exercise the curation
tick itself (covered in ``test_feedback_history_curation.py``).
"""

from __future__ import annotations

import pytest

from applicant.adapters.storage.in_memory import InMemoryStorage
from applicant.application.services.feedback_history import (
    DEFAULT_MAX_SUMMARIES,
    FeedbackSummaryProvider,
)
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


# ---------------------------------------------------------------------------
# Parallel-safety autouse fixture
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _no_cache() -> None:
    """No lru_cache in the module; fixture exists for xdist parallel safety."""
    return


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _storage_with_campaign(active: bool = True) -> tuple[InMemoryStorage, CampaignId, Application]:
    """Create an InMemoryStorage with one campaign and one application."""
    storage = InMemoryStorage()
    cid = CampaignId(new_id())
    storage.campaigns.add(Campaign(id=cid, name="Test Campaign", active=active))
    app = Application(
        id=ApplicationId(new_id()),
        campaign_id=cid,
        posting_id=JobPostingId(new_id()),
        status=ApplicationState.SCORED,
        role_name="Backend Engineer",
        job_title="Backend Engineer",
        work_mode="remote",
        root_url="https://example.com/job/1",
    )
    storage.applications.add(app)
    return storage, cid, app


def _add_decline(storage, app, text: str = "") -> Decision:
    """Add a decline decision with optional feedback text."""
    d = Decision(
        id=DecisionId(new_id()),
        application_id=app.id,
        type=DecisionType.DECLINE,
        feedback_text=text,
    )
    storage.decisions.add(d)
    return d


def _add_approve(storage, app, text: str = "") -> Decision:
    """Add an approve decision (no feedback expected)."""
    d = Decision(
        id=DecisionId(new_id()),
        application_id=app.id,
        type=DecisionType.APPROVE,
        feedback_text=text,
    )
    storage.decisions.add(d)
    return d


def _add_revision(storage, app, cid: CampaignId, *instructions: str) -> RevisionSession:
    """Add a document with a revision session containing the given instruction turns."""
    doc = GeneratedDocument(
        id=GeneratedDocumentId(new_id()),
        campaign_id=cid,
        application_id=app.id,
        type=DocumentType.RESUME,
    )
    storage.documents.add(doc)
    session = RevisionSession(
        id=RevisionSessionId(new_id()),
        material_id=doc.id,
        status=RevisionStatus.OPEN,
        turns=tuple(
            RevisionTurn(kind="free_text", instruction=i) for i in instructions
        ),
    )
    storage.revisions.add(session)
    return session


# ---------------------------------------------------------------------------
# Construction and defaults
# ---------------------------------------------------------------------------

class TestConstructor:
    """FeedbackSummaryProvider constructor behavior."""

    @pytest.mark.unit
    def test_default_max_summaries(self) -> None:
        provider = FeedbackSummaryProvider()
        assert provider._max == DEFAULT_MAX_SUMMARIES  # 25

    @pytest.mark.unit
    def test_clamps_max_to_at_least_one(self) -> None:
        provider = FeedbackSummaryProvider(max_summaries=0)
        assert provider._max == 1

        provider = FeedbackSummaryProvider(max_summaries=-5)
        assert provider._max == 1

    @pytest.mark.unit
    def test_accepts_custom_max(self) -> None:
        provider = FeedbackSummaryProvider(max_summaries=10)
        assert provider._max == 10


# ---------------------------------------------------------------------------
# Empty / no-data cases
# ---------------------------------------------------------------------------

class TestEmpty:
    """Provider called with empty storage."""

    @pytest.mark.unit
    def test_empty_storage_returns_empty_list(self) -> None:
        storage = InMemoryStorage()
        summaries = FeedbackSummaryProvider()(storage)
        assert summaries == []

    @pytest.mark.unit
    def test_no_applications_returns_empty(self) -> None:
        storage = InMemoryStorage()
        cid = CampaignId(new_id())
        storage.campaigns.add(Campaign(id=cid, name="Empty"))
        summaries = FeedbackSummaryProvider()(storage)
        assert summaries == []

    @pytest.mark.unit
    def test_inactive_campaign_skipped(self) -> None:
        storage, cid, app = _storage_with_campaign(active=False)
        _add_decline(storage, app, "Not good enough")
        summaries = FeedbackSummaryProvider()(storage)
        assert summaries == []

    @pytest.mark.unit
    def test_active_campaign_no_feedback_returns_empty(self) -> None:
        storage, cid, app = _storage_with_campaign(active=True)
        summaries = FeedbackSummaryProvider()(storage)
        assert summaries == []


# ---------------------------------------------------------------------------
# Decline feedback
# ---------------------------------------------------------------------------

class TestDeclineFeedback:
    """Digest decline-with-feedback (FR-DIG-5)."""

    @pytest.mark.unit
    def test_decline_with_feedback_yields_summary(self) -> None:
        storage, cid, app = _storage_with_campaign()
        d = _add_decline(storage, app, "Too much travel — I only want remote roles.")

        summaries = FeedbackSummaryProvider()(storage)
        assert len(summaries) == 1
        s = summaries[0]
        assert s.run_id == f"feedback-decline-{d.id}"
        assert s.campaign_id == str(cid)
        assert "Too much travel" in s.text
        assert s.tool_calls == 0
        assert s.succeeded is True
        assert s.is_preference is True

    @pytest.mark.unit
    def test_decline_with_empty_text_skipped(self) -> None:
        storage, cid, app = _storage_with_campaign()
        _add_decline(storage, app, "")
        summaries = FeedbackSummaryProvider()(storage)
        assert summaries == []

    @pytest.mark.unit
    def test_decline_with_whitespace_text_skipped(self) -> None:
        storage, cid, app = _storage_with_campaign()
        _add_decline(storage, app, "   ")
        summaries = FeedbackSummaryProvider()(storage)
        assert summaries == []

    @pytest.mark.unit
    def test_multiple_declines_all_returned(self) -> None:
        storage, cid, app = _storage_with_campaign()
        d1 = _add_decline(storage, app, "Reason one")
        d2 = _add_decline(storage, app, "Reason two")

        summaries = FeedbackSummaryProvider()(storage)
        assert len(summaries) == 2
        run_ids = {s.run_id for s in summaries}
        assert run_ids == {f"feedback-decline-{d1.id}", f"feedback-decline-{d2.id}"}
        assert all(s.is_preference for s in summaries)
        assert all(s.tool_calls == 0 for s in summaries)

    @pytest.mark.unit
    def test_approve_decision_no_feedback_skipped(self) -> None:
        """APPROVE decisions with empty feedback_text produce no summary."""
        storage, cid, app = _storage_with_campaign()
        _add_approve(storage, app, "")
        summaries = FeedbackSummaryProvider()(storage)
        assert summaries == []

    @pytest.mark.unit
    def test_approve_with_text_yields_summary(self) -> None:
        """APPROVE decisions with non-empty feedback_text also yield a summary
        (the source code checks feedback_text, not DecisionType)."""
        storage, cid, app = _storage_with_campaign()
        _add_approve(storage, app, "Great candidate!")
        summaries = FeedbackSummaryProvider()(storage)
        assert len(summaries) == 1
        assert summaries[0].is_preference is True
        assert "Great candidate!" in summaries[0].text


# ---------------------------------------------------------------------------
# Revision feedback
# ---------------------------------------------------------------------------

class TestRevisionFeedback:
    """Résumé/answer revision feedback (FR-RESUME-8)."""

    @pytest.mark.unit
    def test_revision_turn_yields_summary(self) -> None:
        storage, cid, app = _storage_with_campaign()
        session = _add_revision(storage, app, cid, "Drop the buzzwords from the summary.")

        summaries = FeedbackSummaryProvider()(storage)
        assert len(summaries) == 1
        s = summaries[0]
        assert s.run_id == f"feedback-revision-{session.id}-0"
        assert s.campaign_id == str(cid)
        assert "Drop the buzzwords" in s.text
        assert s.tool_calls == 0
        assert s.succeeded is True
        assert s.is_preference is True

    @pytest.mark.unit
    def test_multiple_turns_all_yielded(self) -> None:
        storage, cid, app = _storage_with_campaign()
        session = _add_revision(storage, app, cid, "Drop buzzwords.", "Lead with Python.", "Make it concise.")

        summaries = FeedbackSummaryProvider()(storage)
        assert len(summaries) == 3
        texts = {s.text for s in summaries}
        assert any("buzzwords" in t for t in texts)
        assert any("Python" in t for t in texts)
        assert any("concise" in t for t in texts)
        assert all(s.is_preference for s in summaries)
        run_ids = {s.run_id for s in summaries}
        assert run_ids == {
            f"feedback-revision-{session.id}-0",
            f"feedback-revision-{session.id}-1",
            f"feedback-revision-{session.id}-2",
        }

    @pytest.mark.unit
    def test_empty_instruction_skipped(self) -> None:
        storage, cid, app = _storage_with_campaign()
        doc = GeneratedDocument(
            id=GeneratedDocumentId(new_id()),
            campaign_id=cid,
            application_id=app.id,
            type=DocumentType.RESUME,
        )
        storage.documents.add(doc)
        turned = tuple(t for t in (
            RevisionTurn(kind="free_text", instruction=""),
            RevisionTurn(kind="free_text", instruction="  "),
        ) if t.instruction.strip())
        if not turned:
            session = RevisionSession(
                id=RevisionSessionId(new_id()),
                material_id=doc.id,
                status=RevisionStatus.OPEN,
                turns=(),
            )
        else:
            session = RevisionSession(
                id=RevisionSessionId(new_id()),
                material_id=doc.id,
                status=RevisionStatus.OPEN,
                turns=turned,
            )
        storage.revisions.add(session)

        summaries = FeedbackSummaryProvider()(storage)
        assert summaries == []

    @pytest.mark.unit
    def test_no_revision_for_document_skipped(self) -> None:
        """Document without a revision session produces nothing."""
        storage, cid, app = _storage_with_campaign()
        doc = GeneratedDocument(
            id=GeneratedDocumentId(new_id()),
            campaign_id=cid,
            application_id=app.id,
            type=DocumentType.COVER_LETTER,
        )
        storage.documents.add(doc)

        summaries = FeedbackSummaryProvider()(storage)
        assert summaries == []

    @pytest.mark.unit
    def test_revision_turn_kind_reflected_in_text(self) -> None:
        """The turn kind ('add', 'subtract', 'free_text') appears in summary text."""
        storage, cid, app = _storage_with_campaign()
        doc = GeneratedDocument(
            id=GeneratedDocumentId(new_id()),
            campaign_id=cid,
            application_id=app.id,
            type=DocumentType.RESUME,
        )
        storage.documents.add(doc)
        session = RevisionSession(
            id=RevisionSessionId(new_id()),
            material_id=doc.id,
            status=RevisionStatus.OPEN,
            turns=(
                RevisionTurn(kind="add", instruction="Add Python experience."),
                RevisionTurn(kind="subtract", instruction="Remove outdated skills."),
            ),
        )
        storage.revisions.add(session)

        summaries = FeedbackSummaryProvider()(storage)
        assert len(summaries) == 2
        texts_combined = " ".join(s.text for s in summaries)
        assert "(add)" in texts_combined
        assert "(subtract)" in texts_combined


# ---------------------------------------------------------------------------
# Bounding
# ---------------------------------------------------------------------------

class TestBounding:
    """max_summaries cap (FR-MIND-13)."""

    @pytest.mark.unit
    def test_bounded_by_max(self) -> None:
        storage, cid, app = _storage_with_campaign()
        for i in range(10):
            _add_decline(storage, app, f"Reason {i}")

        summaries = FeedbackSummaryProvider(max_summaries=3)(storage)
        assert len(summaries) == 3

    @pytest.mark.unit
    def test_max_of_one_returns_single(self) -> None:
        storage, cid, app = _storage_with_campaign()
        for i in range(5):
            _add_decline(storage, app, f"Reason {i}")

        summaries = FeedbackSummaryProvider(max_summaries=1)(storage)
        assert len(summaries) == 1

    @pytest.mark.unit
    def test_fewer_items_than_max_returns_all(self) -> None:
        storage, cid, app = _storage_with_campaign()
        _add_decline(storage, app, "Reason A")
        _add_decline(storage, app, "Reason B")

        summaries = FeedbackSummaryProvider(max_summaries=100)(storage)
        assert len(summaries) == 2


# ---------------------------------------------------------------------------
# Topic generation
# ---------------------------------------------------------------------------

class TestTopics:
    """Topic assignment for feedback summaries."""

    @pytest.mark.unit
    def test_decline_topic_uses_job_title(self) -> None:
        storage, cid, app = _storage_with_campaign()
        _add_decline(storage, app, "Reason")

        summaries = FeedbackSummaryProvider()(storage)
        assert len(summaries) == 1
        # _topic_for_app(app, "declines") -> "preference-backend-engineer-declines"
        assert summaries[0].topic == "preference-backend-engineer-declines"

    @pytest.mark.unit
    def test_revision_topic_uses_document_type(self) -> None:
        storage, cid, app = _storage_with_campaign()
        _add_revision(storage, app, cid, "Make it better.")

        summaries = FeedbackSummaryProvider()(storage)
        assert len(summaries) == 1
        # _topic_for_doc(doc) -> doc.type.value is "resume" -> "preference-resume"
        assert summaries[0].topic == "preference-resume"


# ---------------------------------------------------------------------------
# Mixed feedback from same application
# ---------------------------------------------------------------------------

class TestMixed:
    """Multiple feedback sources from one application."""

    @pytest.mark.unit
    def test_decline_and_revision_both_returned(self) -> None:
        storage, cid, app = _storage_with_campaign()
        _add_decline(storage, app, "Too expensive")
        _add_revision(storage, app, cid, "Simplify the cover letter.")

        summaries = FeedbackSummaryProvider()(storage)
        assert len(summaries) == 2
        assert all(s.is_preference for s in summaries)
        assert all(s.tool_calls == 0 for s in summaries)

    @pytest.mark.unit
    def test_run_ids_are_distinct(self) -> None:
        """Decline and revision run_ids must be distinct for curator dedup."""
        storage, cid, app = _storage_with_campaign()
        d = _add_decline(storage, app, "Reason")
        session = _add_revision(storage, app, cid, "Edit this.")

        summaries = FeedbackSummaryProvider()(storage)
        run_ids = {s.run_id for s in summaries}
        assert run_ids == {f"feedback-decline-{d.id}", f"feedback-revision-{session.id}-0"}


# ---------------------------------------------------------------------------
# Multiple applications across campaigns
# ---------------------------------------------------------------------------

class TestMultiApp:
    """Multiple applications in a campaign."""

    @pytest.mark.unit
    def test_multiple_apps_collected(self) -> None:
        storage = InMemoryStorage()
        cid = CampaignId(new_id())
        storage.campaigns.add(Campaign(id=cid, name="Multi", active=True))

        app1 = Application(
            id=ApplicationId(new_id()),
            campaign_id=cid,
            posting_id=JobPostingId(new_id()),
            status=ApplicationState.SCORED,
            role_name="Engineer",
            job_title="Engineer",
            work_mode="remote",
            root_url="https://example.com/job/a",
        )
        storage.applications.add(app1)

        app2 = Application(
            id=ApplicationId(new_id()),
            campaign_id=cid,
            posting_id=JobPostingId(new_id()),
            status=ApplicationState.SCORED,
            role_name="Designer",
            job_title="Designer",
            work_mode="remote",
            root_url="https://example.com/job/b",
        )
        storage.applications.add(app2)

        _add_decline(storage, app1, "Not senior enough")
        _add_decline(storage, app2, "Wrong stack")

        summaries = FeedbackSummaryProvider()(storage)
        assert len(summaries) == 2


# ---------------------------------------------------------------------------
# now=None behavior
# ---------------------------------------------------------------------------

class TestNowArgument:
    """Optional ``now`` arg is accepted (scheduler passes it) but unused internally."""

    @pytest.mark.unit
    def test_accepts_now_without_changing_behavior(self) -> None:
        from datetime import datetime
        storage, cid, app = _storage_with_campaign()
        _add_decline(storage, app, "Feedback")

        summaries = FeedbackSummaryProvider()(storage, now=datetime(2025, 6, 1))
        assert len(summaries) == 1
        assert summaries[0].is_preference

