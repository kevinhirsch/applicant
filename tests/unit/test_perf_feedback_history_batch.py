"""Regression coverage for performance lens 03 (round 2): ``FeedbackSummaryProvider``
(the curation-tick's feedback-summary source, ``application/services/
feedback_history.py``, FR-LEARN-3) looped every application in a campaign and, for
each one, called ``storage.decisions.list_for_application(app.id)`` AND
``storage.documents.list_for_application(app.id)``, then for EACH of that
application's documents called ``storage.revisions.get_for_material(doc.id)`` — an
N+1 (actually N x (2+D)) that runs on every scheduled curation tick.

The fix adds two new batch repository reads (``DecisionRepository.list_for_campaign``
and ``RevisionSessionRepository.list_for_materials``, alongside the
already-existing ``GeneratedDocumentRepository.list_for_campaign``) and groups the
rows by application/material id in Python once per campaign, so the per-application
loop is a dict lookup instead of 2+D storage round-trips.

FAIL-BEFORE: on the pre-fix tree (verified by hand — file-copy the pre-fix
``feedback_history.py``/``repositories.py``/``in_memory.py``/``storage.py`` (ports)
back in, rerun, see the call-count assertions fail because each per-application call
happened instead of the batched ones, then restore) this pins the batched reads AND
that the resulting ``RunSummary`` output (decline text + revision instructions) is
byte-identical to before.
"""

from __future__ import annotations

import pytest

from applicant.adapters.storage.in_memory import InMemoryStorage
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


class _CountingRepo:
    """Wraps a real in-memory repo, counting per-application/per-material calls."""

    def __init__(self, inner, *, per_app_method: str, batch_method: str):
        self._inner = inner
        self._per_app_method = per_app_method
        self._batch_method = batch_method
        self.per_app_calls = 0
        self.batch_calls = 0

    def __getattr__(self, name):
        if name == self._per_app_method:
            self.per_app_calls += 1
        elif name == self._batch_method:
            self.batch_calls += 1
        return getattr(self._inner, name)


def _seed(storage) -> tuple[CampaignId, list[Application]]:
    cid = CampaignId(new_id())
    storage.campaigns.add(Campaign(id=cid, name="Search", active=True))
    apps = []
    for i in range(3):
        app = Application(
            id=ApplicationId(new_id()), campaign_id=cid,
            posting_id=JobPostingId(new_id()), status=ApplicationState.SCORED,
            job_title=f"Engineer {i}",
        )
        storage.applications.add(app)
        apps.append(app)

        storage.decisions.add(
            Decision(
                id=DecisionId(new_id()), application_id=app.id,
                type=DecisionType.DECLINE, feedback_text=f"Not remote enough #{i}",
            )
        )

        doc = GeneratedDocument(
            id=GeneratedDocumentId(new_id()), campaign_id=cid, application_id=app.id,
            type=DocumentType.RESUME, content="body",
        )
        storage.documents.add(doc)
        storage.revisions.add(
            RevisionSession(
                id=RevisionSessionId(new_id()), material_id=doc.id,
                status=RevisionStatus.OPEN,
                turns=(RevisionTurn(kind="add", instruction=f"Add Python #{i}"),),
            )
        )
    storage.commit()
    return cid, apps


@pytest.mark.unit
def test_feedback_history_batches_decisions_documents_revisions():
    storage = InMemoryStorage()
    cid, apps = _seed(storage)

    decisions_counting = _CountingRepo(
        storage.decisions, per_app_method="list_for_application", batch_method="list_for_campaign"
    )
    documents_counting = _CountingRepo(
        storage.documents, per_app_method="list_for_application", batch_method="list_for_campaign"
    )
    revisions_counting = _CountingRepo(
        storage.revisions, per_app_method="get_for_material", batch_method="list_for_materials"
    )
    storage.decisions = decisions_counting
    storage.documents = documents_counting
    storage.revisions = revisions_counting

    summaries = FeedbackSummaryProvider()(storage)

    assert decisions_counting.per_app_calls == 0, "must not fetch decisions per application"
    assert decisions_counting.batch_calls == 1
    assert documents_counting.per_app_calls == 0, "must not fetch documents per application"
    assert documents_counting.batch_calls == 1
    assert revisions_counting.per_app_calls == 0, "must not fetch revisions per document"
    assert revisions_counting.batch_calls == 1

    # Behavior parity: one decline summary + one revision summary per application.
    decline_summaries = [s for s in summaries if s.run_id.startswith("feedback-decline-")]
    revision_summaries = [s for s in summaries if s.run_id.startswith("feedback-revision-")]
    assert len(decline_summaries) == 3
    assert len(revision_summaries) == 3
    decline_texts = {s.text for s in decline_summaries}
    assert decline_texts == {
        "You declined a match and said: Not remote enough #0",
        "You declined a match and said: Not remote enough #1",
        "You declined a match and said: Not remote enough #2",
    }
    revision_texts = {s.text for s in revision_summaries}
    assert revision_texts == {
        "You revised generated material (add): Add Python #0",
        "You revised generated material (add): Add Python #1",
        "You revised generated material (add): Add Python #2",
    }
    assert all(s.is_preference for s in summaries)


@pytest.mark.unit
def test_feedback_history_respects_max_summaries_cap_after_batching():
    storage = InMemoryStorage()
    _seed(storage)  # 3 apps x 2 feedback items = 6 potential summaries

    summaries = FeedbackSummaryProvider(max_summaries=2)(storage)

    assert len(summaries) == 2
