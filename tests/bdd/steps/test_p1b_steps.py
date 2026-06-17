"""Step bindings for Phase 1 part B acceptance scenarios (master spec §10).

Maps the §10 anchors — Discord-first escalation ladder with 30s hold + web pre-empt,
Channel setup gates automated work, Decline-with-feedback into learning — to the real
notifier/services + core rules so the scenarios genuinely pass. The ladder uses a
deterministic injected clock (no real sleeps). HTTP scenarios open the LLM gate via
the setup endpoint exactly as the app would.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from pytest_bdd import given, scenarios, then, when

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
from applicant.core.ids import ApplicationId, CampaignId, JobPostingId, new_id
from applicant.ports.driven.notification import Notification, NotificationUrgency

scenarios(
    "../features/p1_notification_ladder.feature",
    "../features/p1_channel_setup_gate.feature",
    "../features/p1_decline_learning.feature",
)


class _Clock:
    def __init__(self) -> None:
        self.now = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now

    def tick(self, seconds: float) -> None:
        self.now = self.now + timedelta(seconds=seconds)


@pytest.fixture
def p1bctx() -> dict:
    return {}


def _open_gate(client) -> None:
    r = client.post(
        "/api/setup/llm",
        json={"provider": "ollama", "base_url": "http://localhost:11434/v1", "model": "llama3.1"},
    )
    assert r.status_code == 204


# --- notification ladder ---------------------------------------------------
@given("a configured notifier driven by a deterministic clock")
def configured_notifier(p1bctx):
    clock = _Clock()
    p1bctx["clock"] = clock
    p1bctx["notifier"] = AppriseNotifier(
        discord_webhook_url="https://discord.test/wh",
        apprise_urls="mailto://u:p@smtp.test",
        clock=clock,
    )


@given("a configured notifier where the user is verifiably present in the web UI")
def notifier_with_presence(p1bctx):
    clock = _Clock()
    p1bctx["clock"] = clock
    p1bctx["notifier"] = AppriseNotifier(
        discord_webhook_url="https://discord.test/wh",
        apprise_urls="mailto://u:p@smtp.test",
        clock=clock,
        presence=lambda: True,
    )


@given("a configured notifier during quiet hours")
def notifier_quiet(p1bctx):
    clock = _Clock()
    clock.now = datetime(2026, 1, 1, 3, 0, tzinfo=UTC)
    p1bctx["clock"] = clock
    p1bctx["notifier"] = AppriseNotifier(
        discord_webhook_url="https://discord.test/wh",
        apprise_urls="mailto://u:p@smtp.test",
        clock=clock,
        quiet_hours=(22, 7),
    )


@when("a web-pre-emptable approval is queued")
def queue_preemptable(p1bctx):
    p1bctx["notifier"].notify(
        Notification(title="Approve?", body="role", dedup_key="ladder", web_preemptable=True)
    )


@then("the in-app channel fires immediately and Discord is held")
def in_app_first(p1bctx):
    assert p1bctx["notifier"].sent_channels("ladder") == ["in_app"]


@when("thirty seconds elapse and the ladder advances")
def advance_30s(p1bctx):
    p1bctx["clock"].tick(30)
    p1bctx["notifier"].advance()


@then("Discord has fired but email has not")
def discord_not_email(p1bctx):
    sent = p1bctx["notifier"].sent_channels("ladder")
    assert "discord" in sent and "email" not in sent


@when("the configurable email timeout elapses and the ladder advances")
def advance_email(p1bctx):
    p1bctx["clock"].tick(15 * 60)
    p1bctx["notifier"].advance()


@then("email has fired")
def email_fired(p1bctx):
    assert "email" in p1bctx["notifier"].sent_channels("ladder")


@when("a web-pre-emptable approval is queued and the hold elapses")
def queue_then_hold(p1bctx):
    p1bctx["notifier"].notify(
        Notification(title="Approve?", body="role", dedup_key="pre", web_preemptable=True)
    )
    p1bctx["clock"].tick(30)
    p1bctx["notifier"].advance()


@then("the in-app surface is used and Discord is not pushed")
def preempted(p1bctx):
    sent = p1bctx["notifier"].sent_channels("pre")
    assert "in_app" in sent and "discord" not in sent


@when("an approval is queued and the user acts on the web portal")
def queue_then_act(p1bctx):
    svc = NotificationService(p1bctx["notifier"])
    svc.notify_decision("app-x", title="Approve?", body="role")
    p1bctx["svc"] = svc
    svc.acted("app-x")


@then("the decision is no longer pending on any channel")
def not_pending(p1bctx):
    assert not p1bctx["notifier"].is_active("decision:app-x")
    p1bctx["clock"].tick(60 * 60)
    assert p1bctx["notifier"].advance() == []


@when("an immediate error notification is queued")
def queue_error(p1bctx):
    p1bctx["notifier"].notify(
        Notification(
            title="boom", body="failure", urgency=NotificationUrgency.IMMEDIATE, dedup_key="err"
        )
    )


@then("every configured channel fires at once")
def all_channels(p1bctx):
    sent = set(p1bctx["notifier"].sent_channels("err"))
    assert {"discord", "in_app", "email"} <= sent


# --- channel setup gate ----------------------------------------------------
@given("the LLM gate has been opened through the wizard")
def llm_gate_opened(p1bctx, app_client):
    _open_gate(app_client)
    p1bctx["client"] = app_client


@when("Discord and email channels are configured through the API")
def configure_channels(p1bctx):
    r = p1bctx["client"].post(
        "/api/setup/channels",
        json={
            "discord_webhook_url": "https://discord.test/api/webhooks/a/b",
            "apprise_urls": "mailto://u:p@smtp.test",
        },
    )
    assert r.status_code == 204


@then("the wizard reports the channels step complete")
def channels_step_complete(p1bctx):
    status = p1bctx["client"].get("/api/setup/status").json()
    assert "channels" in status["steps_complete"]


@then("the configured notifier reports Discord and email channels")
def notifier_reports_channels(p1bctx):
    channels = p1bctx["client"].app.state.container.notification.configured_channels()
    assert "discord" in channels and "email" in channels


@then("automated work is not yet allowed")
def work_not_allowed(p1bctx):
    status = p1bctx["client"].get("/api/setup/status").json()
    assert status["automated_work_allowed"] is False


@then("automated work is still gated on remaining setup")
def work_still_gated(p1bctx):
    # Onboarding is still incomplete, so automated work remains blocked
    # (FR-ONBOARD-2). Channels are optional now and do not affect this.
    status = p1bctx["client"].get("/api/setup/status").json()
    assert status["automated_work_allowed"] is False


# --- decline-with-feedback into learning -----------------------------------
def _wire_digest():
    storage = InMemoryStorage()
    embedding = LocalEmbedding()
    notifier = AppriseNotifier(discord_webhook_url="https://discord.test/wh")
    learning = LearningService(storage, embedding)
    criteria = CriteriaService(storage, llm=None)
    pending = PendingActionsService(storage)
    notif_svc = NotificationService(notifier)
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
    return storage, digest, learning, criteria, pending


@given("a campaign with seeded criteria and a surfaced application")
def seeded_campaign(p1bctx):
    storage, digest, learning, criteria, pending = _wire_digest()
    cid = CampaignId(new_id())
    storage.campaigns.add(Campaign(id=cid, name="C"))
    storage.commit()
    criteria.edit_criteria(cid, changes={"keywords": ["python"]})
    aid = ApplicationId(new_id())
    storage.applications.add(Application(id=aid, campaign_id=cid, posting_id=JobPostingId("")))
    storage.commit()
    p1bctx.update(
        storage=storage,
        digest=digest,
        learning=learning,
        criteria=criteria,
        campaign_id=cid,
        application_id=aid,
    )


@when("the user declines the application with feedback and a criteria delta")
def decline_app(p1bctx):
    p1bctx["digest"].decline(
        p1bctx["application_id"],
        feedback_text="too junior",
        criteria_delta={"keywords": ["senior"]},
    )


@then("the decline is folded into the campaign learning model")
def decline_folded(p1bctx):
    model = p1bctx["learning"].load_model(p1bctx["campaign_id"])
    assert model.feature_stats, "learning model should record the decline"


@then("the next-run criteria reflect the structured delta")
def criteria_reflect_delta(p1bctx):
    updated = p1bctx["criteria"].get_criteria(p1bctx["campaign_id"])
    assert "senior" in updated.keywords


@given("a campaign with a viable discovered posting")
def campaign_with_posting(p1bctx):
    storage, digest, learning, criteria, pending = _wire_digest()
    cid = CampaignId(new_id())
    storage.campaigns.add(Campaign(id=cid, name="C"))
    storage.postings.add(
        JobPosting(
            id=JobPostingId(new_id()),
            campaign_id=cid,
            title="Senior Python Engineer",
            company="Acme",
            source_url="https://acme.test/job",
            work_mode="remote",
            description="python",
            source_key="jobspy:indeed",
        )
    )
    storage.commit()
    p1bctx.update(storage=storage, digest=digest, pending=pending, campaign_id=cid)
    p1bctx["criteria_obj"] = SearchCriteria(campaign_id=cid, titles=("engineer",), keywords=("python",))


@when("the daily digest is delivered")
def deliver_digest(p1bctx):
    p1bctx["result"] = p1bctx["digest"].deliver(p1bctx["campaign_id"], p1bctx["criteria_obj"])


@then("an email payload and a Discord ready ping are produced")
def email_and_ping(p1bctx):
    result = p1bctx["result"]
    assert result["email"]["html"]
    assert result["notify_handle"]


@then("a digest-approval item appears in the pending-actions portal")
def pending_has_approval(p1bctx):
    items = p1bctx["pending"].list_pending(p1bctx["campaign_id"])
    assert any(i.kind == "digest_approval" for i in items)
