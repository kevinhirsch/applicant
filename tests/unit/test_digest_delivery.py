"""Digest delivery + decline-with-feedback round-trip (FR-DIG-2/5, FR-FB-1, FR-LEARN-3).

Covers the email/webpage/Discord-ready delivery and the close-the-loop wiring that
folds a decline into LearningService + the next run's criteria.
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
from applicant.core.entities.application import Application
from applicant.core.entities.campaign import Campaign
from applicant.core.entities.job_posting import JobPosting
from applicant.core.entities.search_criteria import SearchCriteria
from applicant.core.ids import (
    ApplicationId,
    CampaignId,
    JobPostingId,
    new_id,
)


def _wire():
    storage = InMemoryStorage()
    embedding = LocalEmbedding()
    notifier = AppriseNotifier(discord_webhook_url="https://discord.test/wh")
    learning = LearningService(storage, embedding)
    criteria = CriteriaService(storage, llm=None)
    notif_svc = NotificationService(notifier)
    pending = PendingActionsService(storage)
    scoring = ScoringService(storage, llm=None, embedding=embedding, threshold=0)
    digest = DigestService(
        storage,
        notifier,
        scoring,
        learning=learning,
        criteria=criteria,
        notification_service=notif_svc,
        pending_actions=pending,
    )
    return storage, digest, learning, criteria, pending, notifier


def _seed_campaign(storage, *, with_posting=True):
    cid = CampaignId(new_id())
    storage.campaigns.add(Campaign(id=cid, name="C"))
    if with_posting:
        pid = JobPostingId(new_id())
        storage.postings.add(
            JobPosting(
                id=pid,
                campaign_id=cid,
                title="Senior Python Engineer",
                company="Acme",
                source_url="https://acme.test/job",
                work_mode="remote",
                description="python fastapi",
                source_key="jobspy:indeed",
            )
        )
    storage.commit()
    return cid


def test_deliver_builds_payloads_and_pings_discord():
    storage, digest, *_ , notifier = _wire()
    cid = _seed_campaign(storage)
    crit = SearchCriteria(campaign_id=cid, titles=("engineer",), keywords=("python",))
    result = digest.deliver(cid, crit)
    assert result["payload"]["rows"], "viable role should be in the digest"
    assert result["email"]["html"].startswith("<h1>")
    # Discord-ready ping queued (FR-DIG-2).
    assert result["notify_handle"]
    # Each viable row materializes a pending digest-approval (FR-UI-3).
    assert any(a.kind == "digest_approval" for a in storage.pending_actions.list_open(cid))


def test_deliver_sends_email_body_to_email_channel():
    # FR-DIG-2: the rendered digest email is actually SENT through the notifier's
    # email channel (not pull-only), in addition to the webpage + Discord ping.
    storage = InMemoryStorage()
    embedding = LocalEmbedding()
    # Email channel configured (apprise_urls) so the email send has a target.
    notifier = AppriseNotifier(
        discord_webhook_url="https://discord.test/wh",
        apprise_urls="mailto://user:pass@smtp.test",
    )
    learning = LearningService(storage, embedding)
    criteria = CriteriaService(storage, llm=None)
    notif_svc = NotificationService(notifier)
    pending = PendingActionsService(storage)
    scoring = ScoringService(storage, llm=None, embedding=embedding, threshold=0)
    digest = DigestService(
        storage,
        notifier,
        scoring,
        learning=learning,
        criteria=criteria,
        notification_service=notif_svc,
        pending_actions=pending,
    )
    cid = _seed_campaign(storage)
    crit = SearchCriteria(campaign_id=cid, titles=("engineer",), keywords=("python",))
    result = digest.deliver(cid, crit)

    assert result["email_sent"] is True
    # The notifier captured an EMAIL dispatch carrying the rendered HTML body.
    email_sends = [c for c in notifier.captured() if c.channel == "email"]
    assert email_sends, "the digest email was dispatched to the email channel"
    assert email_sends[0].body == result["email"]["html"]
    assert email_sends[0].title == result["email"]["subject"]


def test_deliver_without_email_channel_does_not_send():
    # Offline-safe default lane (Discord-only notifier, no email channel): no email.
    storage, digest, *_, notifier = _wire()
    cid = _seed_campaign(storage)
    result = digest.deliver(cid)
    assert result["email_sent"] is False
    assert not [c for c in notifier.captured() if c.channel == "email"]


def test_empty_day_email_and_note():
    storage, digest, *_ = _wire()
    cid = _seed_campaign(storage, with_posting=False)
    email = digest.render_email(cid)
    assert "no new matches" in email["subject"].lower()
    payload = digest.build_digest_payload(cid)
    assert payload["empty"] and payload["note"]
    assert "Searched" in payload["note"]


def test_decline_round_trips_into_learning_and_criteria():
    storage, digest, learning, criteria, _pending, _ = _wire()
    cid = _seed_campaign(storage, with_posting=False)
    # Seed criteria so the learned adjustment can persist.
    criteria.edit_criteria(cid, changes={"keywords": ["python"]})
    aid = ApplicationId(new_id())
    storage.applications.add(
        Application(id=aid, campaign_id=cid, posting_id=JobPostingId(""))
    )
    storage.commit()

    digest.decline(aid, feedback_text="too junior", criteria_delta={"keywords": ["senior"]})

    # Learning model recorded the decline feedback (FR-LEARN-3).
    model = learning.load_model(cid)
    assert any("feedback" in k or k == "keywords" for k in model.feature_stats)
    # Next-run criteria biased by the structured delta (FR-DIG-5, FR-CRIT-3).
    updated = criteria.get_criteria(cid)
    assert "senior" in updated.keywords
    assert updated.learned_adjustments.get("summary")


def test_approve_expires_other_channels():
    storage, digest, *_rest, notifier = _wire()
    cid = _seed_campaign(storage, with_posting=False)
    aid = ApplicationId(new_id())
    storage.applications.add(
        Application(id=aid, campaign_id=cid, posting_id=JobPostingId(""))
    )
    storage.commit()
    # Queue an approval notification keyed by application id.
    NotificationService(notifier).notify_decision(str(aid), title="Approve?", body="role")
    key = f"decision:{aid}"
    assert notifier.is_active(key)
    digest.approve(aid)
    assert not notifier.is_active(key)
