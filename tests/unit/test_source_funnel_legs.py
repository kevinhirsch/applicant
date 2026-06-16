"""Source-yield funnel legs are now recorded (FR-DISC-5 / FR-LEARN-6).

Before: only the ``matches`` leg was recorded; approvals + submissions were computed
but discarded. These prove the approval path (digest) and submission path now fold
their legs into the per-source funnel so the learned weight reflects real conversion.
"""

from __future__ import annotations

from applicant.adapters.embedding.local_embedding import LocalEmbedding
from applicant.adapters.notification.apprise_notifier import AppriseNotifier
from applicant.adapters.storage.in_memory import InMemoryStorage
from applicant.application.services.criteria_service import CriteriaService
from applicant.application.services.digest_service import DigestService
from applicant.application.services.learning_service import LearningService
from applicant.application.services.notification_service import NotificationService
from applicant.application.services.pending_actions_service import PendingActionsService
from applicant.application.services.scoring_service import ScoringService
from applicant.application.services.submission_service import SubmissionService
from applicant.core.entities.application import Application
from applicant.core.entities.campaign import Campaign
from applicant.core.entities.job_posting import JobPosting
from applicant.core.entities.outcome_event import OutcomeSource
from applicant.core.ids import ApplicationId, CampaignId, JobPostingId, new_id
from applicant.core.state_machine import ApplicationState


def _seed(storage):
    cid = CampaignId(new_id())
    storage.campaigns.add(Campaign(id=cid, name="C"))
    pid = JobPostingId(new_id())
    storage.postings.add(
        JobPosting(
            id=pid,
            campaign_id=cid,
            title="Senior Python Engineer",
            company="Acme",
            source_url="https://acme.test/job",
            source_key="jobspy:indeed",
            description="python",
        )
    )
    storage.commit()
    return cid, pid


def test_digest_approval_records_approvals_leg():
    storage = InMemoryStorage()
    embedding = LocalEmbedding()
    learning = LearningService(storage, embedding)
    notifier = AppriseNotifier()
    digest = DigestService(
        storage,
        notifier,
        ScoringService(storage, llm=None, embedding=embedding, threshold=0),
        learning=learning,
        criteria=CriteriaService(storage, llm=None),
        notification_service=NotificationService(notifier),
        pending_actions=PendingActionsService(storage),
    )
    cid, pid = _seed(storage)
    # Approving a digest row (keyed on the posting id) records the approvals leg.
    digest.approve(ApplicationId(str(pid)))
    src = storage.discovery_sources.get(cid, "jobspy:indeed")
    assert src is not None
    assert src.yield_stats.get("approvals", 0) == 1


def test_submission_records_submissions_leg():
    storage = InMemoryStorage()
    embedding = LocalEmbedding()
    learning = LearningService(storage, embedding)
    cid, pid = _seed(storage)
    aid = ApplicationId(new_id())
    storage.applications.add(
        Application(
            id=aid,
            campaign_id=cid,
            posting_id=pid,
            status=ApplicationState.AWAITING_FINAL_APPROVAL,
        )
    )
    storage.commit()
    svc = SubmissionService(storage, browser=None, learning=learning)
    app = storage.applications.get(aid)
    svc.record_submission(app, source=OutcomeSource.MANUAL)
    src = storage.discovery_sources.get(cid, "jobspy:indeed")
    assert src is not None
    assert src.yield_stats.get("submissions", 0) == 1


def test_record_source_event_ignores_unknown_leg():
    storage = InMemoryStorage()
    learning = LearningService(storage, LocalEmbedding())
    cid = CampaignId(new_id())
    storage.campaigns.add(Campaign(id=cid, name="C"))
    storage.commit()
    # Unknown leg is a no-op (no crash, no stat).
    learning.record_source_event(cid, "jobspy:indeed", "bogus")
    assert storage.discovery_sources.get(cid, "jobspy:indeed") is None
