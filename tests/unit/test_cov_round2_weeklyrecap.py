"""Weekly recap: aggregation + notification + weekly cadence (audit Top-25 #18).

Round 2, item #18: "Weekly recap notification + card (sent/interviews/offers, best
source) — reuse digest fan-out; digest_service.py." These prove, hermetically (an
injected clock, the offline default ``AppriseNotifier`` — no real network/DB):

* ``DigestService.build_weekly_recap`` counts REAL submissions (the durable
  submission-snapshot log, #372) inside a trailing-7-day window and excludes older
  ones;
* the best-performing source reuses ``LearningService.source_ranking`` (the SAME
  conversion-weighted ranking behind the Insights "Best sources" surface) rather
  than a second, divergent stat, and is ``None`` (not fabricated) when there is no
  recorded funnel data yet;
* interview/offer outcomes are gracefully degraded — never fabricated as zero — since
  nothing in the engine today records ``interview_invited``/``offer`` OutcomeEvents
  and the entity carries no timestamp to window them by week anyway;
* the composed message is first-person, white-labeled, and truthfully reflects a
  zero-application week without inventing content;
* delivery flows through the EXISTING notification fan-out (``NotificationService`` —
  the same in-app inbox + opt-in Discord/email path the daily digest already uses),
  not a second pipeline;
* the scheduler pushes the recap EXACTLY once per campaign per ISO week, gated on the
  automated-work gate and the ``WEEKLY_RECAP_SCHEDULE`` setting, and re-ticking the
  same week does NOT double-fire (idempotency guard) while a new ISO week fires again.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from applicant.adapters.embedding.local_embedding import LocalEmbedding
from applicant.adapters.notification.apprise_notifier import AppriseNotifier
from applicant.adapters.storage.in_memory import InMemoryStorage
from applicant.application.services.digest_service import RECAP_WINDOW_DAYS, DigestService
from applicant.application.services.learning_service import LearningService
from applicant.application.services.notification_service import NotificationService
from applicant.application.services.scheduler import Scheduler
from applicant.core.entities.application import Application
from applicant.core.entities.campaign import Campaign
from applicant.core.entities.discovery_source import DiscoverySource
from applicant.core.entities.job_posting import JobPosting
from applicant.core.entities.submission_snapshot import SubmissionSnapshot
from applicant.core.ids import (
    ApplicationId,
    CampaignId,
    DiscoverySourceId,
    JobPostingId,
    SubmissionSnapshotId,
    new_id,
)


def _wire(*, with_learning=True):
    storage = InMemoryStorage()
    notifier = AppriseNotifier()  # offline default: records in-app inbox, no network
    notif_svc = NotificationService(notifier)
    learning = LearningService(storage, LocalEmbedding()) if with_learning else None
    digest = DigestService(
        storage,
        notifier,
        learning=learning,
        notification_service=notif_svc,
    )
    return storage, digest, learning, notif_svc, notifier


def _campaign(storage, *, active=True) -> CampaignId:
    cid = CampaignId(new_id())
    storage.campaigns.add(Campaign(id=cid, name="C", active=active))
    return cid


def _submit(storage, campaign_id, *, captured_at: datetime) -> None:
    """Seed one real submission: a posting + application + submission snapshot."""
    pid = JobPostingId(new_id())
    storage.postings.add(
        JobPosting(
            id=pid,
            campaign_id=campaign_id,
            title="Engineer",
            company="Acme",
            source_url="https://acme.example/job",
            source_key="linkedin",
        )
    )
    aid = ApplicationId(new_id())
    storage.applications.add(
        Application(id=aid, campaign_id=campaign_id, posting_id=pid)
    )
    storage.submission_snapshots.add(
        SubmissionSnapshot(
            id=SubmissionSnapshotId(new_id()),
            application_id=aid,
            captured_at=captured_at,
        )
    )
    storage.commit()


class _Loop:
    def tick(self, campaign_id, now=None, **_):
        return None


class _Gate:
    def __init__(self, allowed=True):
        self.allowed = allowed

    def is_automated_work_allowed(self) -> bool:
        return self.allowed


# --- build_weekly_recap: applications-sent window -------------------------


@pytest.mark.unit
def test_recap_counts_submissions_inside_window_and_excludes_older_ones():
    storage, digest, _learning, _notif, _notifier = _wire()
    cid = _campaign(storage)
    now = datetime(2026, 6, 16, 9, 0, tzinfo=UTC)
    # Two submissions inside the trailing-7-day window...
    _submit(storage, cid, captured_at=now - timedelta(days=1))
    _submit(storage, cid, captured_at=now - timedelta(days=RECAP_WINDOW_DAYS - 1))
    # ...one exactly at the window's start edge (included, half-open [start, end))...
    _submit(storage, cid, captured_at=now - timedelta(days=RECAP_WINDOW_DAYS))
    # ...and one well outside it.
    _submit(storage, cid, captured_at=now - timedelta(days=30))

    recap = digest.build_weekly_recap(cid, now=now)
    assert recap["applications_sent"] == 3
    assert recap["window_end"] == now
    assert recap["window_start"] == now - timedelta(days=RECAP_WINDOW_DAYS)


@pytest.mark.unit
def test_recap_zero_applications_when_nothing_submitted():
    storage, digest, _learning, _notif, _notifier = _wire()
    cid = _campaign(storage)
    now = datetime(2026, 6, 16, 9, 0, tzinfo=UTC)
    recap = digest.build_weekly_recap(cid, now=now)
    assert recap["applications_sent"] == 0


# --- build_weekly_recap: best-performing source (reuse LearningService) ---


@pytest.mark.unit
def test_best_source_reuses_learning_source_ranking():
    storage, digest, learning, _notif, _notifier = _wire()
    cid = _campaign(storage)
    storage.campaigns.add(Campaign(id=cid, name="C"))  # ensure present for learning
    # linkedin converts; indeed has volume but never converts -> linkedin ranks first
    # (mirrors LearningService._conversion_score, the SAME ranking Insights reads).
    learning.record_funnel_atomic(
        cid,
        {
            "linkedin": {"matches": 4, "approvals": 2, "submissions": 1},
            "indeed": {"matches": 20, "approvals": 0, "submissions": 0},
        },
    )
    recap = digest.build_weekly_recap(cid, now=datetime(2026, 6, 16, tzinfo=UTC))
    assert recap["best_source"] == "linkedin"


@pytest.mark.unit
def test_best_source_is_none_when_no_funnel_data_recorded_yet():
    """A source can be listed/enabled (so it appears in the learned ranking) with a
    weight but ZERO recorded matches/approvals/submissions -> not fabricated as
    'best', even though it is the only (and thus top-ranked) entry."""
    storage, digest, _learning, _notif, _notifier = _wire()
    cid = _campaign(storage)
    storage.discovery_sources.upsert(
        DiscoverySource(
            id=DiscoverySourceId(new_id()),
            campaign_id=cid,
            source_key="linkedin",
            enabled=True,
            yield_stats={"weight": 0.0},  # listed, but no matches/approvals/submissions
        )
    )
    recap = digest.build_weekly_recap(cid, now=datetime(2026, 6, 16, tzinfo=UTC))
    assert recap["best_source"] is None


@pytest.mark.unit
def test_best_source_is_none_when_no_learning_service_wired():
    """Graceful degrade: no learning service -> no crash, no fabricated source."""
    storage, digest, _learning, _notif, _notifier = _wire(with_learning=False)
    cid = _campaign(storage)
    recap = digest.build_weekly_recap(cid, now=datetime(2026, 6, 16, tzinfo=UTC))
    assert recap["best_source"] is None
    assert recap["applications_sent"] == 0


# --- render_weekly_recap_message: voice + graceful degradation ------------


@pytest.mark.unit
def test_message_is_first_person_reports_real_count_and_best_source():
    storage, digest, learning, _notif, _notifier = _wire()
    cid = _campaign(storage)
    now = datetime(2026, 6, 16, tzinfo=UTC)
    _submit(storage, cid, captured_at=now - timedelta(days=2))
    _submit(storage, cid, captured_at=now - timedelta(days=3))
    learning.record_funnel_atomic(cid, {"linkedin": {"matches": 2, "submissions": 1}})

    msg = digest.render_weekly_recap_message(cid, recap=digest.build_weekly_recap(cid, now=now))
    assert msg["body"].startswith("This week I sent 2 applications on your behalf.")
    assert "linkedin" in msg["body"]
    assert msg["subject"] == "Your weekly recap"
    # White-label: never leaks FR-jargon into user-facing copy.
    assert "FR-" not in msg["body"]


@pytest.mark.unit
def test_message_degrades_gracefully_with_zero_applications_and_no_source():
    storage, digest, _learning, _notif, _notifier = _wire(with_learning=False)
    cid = _campaign(storage)
    msg = digest.render_weekly_recap_message(cid, recap=digest.build_weekly_recap(cid))
    assert msg["applications_sent"] == 0
    assert msg["best_source"] is None
    assert "didn't send any new applications" in msg["body"]
    # No crash, no fabricated best-source clause.
    assert "best-performing source" not in msg["body"]


@pytest.mark.unit
def test_message_never_fabricates_interview_or_offer_counts():
    """Interview/offer OutcomeEvents exist in the catalogue but nothing populates
    them (no route/service creates one) and the entity has no timestamp to window by
    week — the recap must omit that line entirely rather than claim '0 interviews'."""
    storage, digest, learning, _notif, _notifier = _wire()
    cid = _campaign(storage)
    now = datetime(2026, 6, 16, tzinfo=UTC)
    _submit(storage, cid, captured_at=now - timedelta(days=1))
    msg = digest.render_weekly_recap_message(cid, recap=digest.build_weekly_recap(cid, now=now))
    assert "interview" not in msg["body"].lower()
    assert "offer" not in msg["body"].lower()


# --- deliver_weekly_recap: reuses the EXISTING notification fan-out -------


@pytest.mark.unit
def test_deliver_pushes_through_existing_notification_fanout():
    storage, digest, learning, notif_svc, notifier = _wire()
    cid = _campaign(storage)
    now = datetime(2026, 6, 16, tzinfo=UTC)
    _submit(storage, cid, captured_at=now - timedelta(days=1))

    handle = digest.deliver_weekly_recap(cid, now=now)
    assert handle is not None
    inbox = notif_svc.list_inbox()
    assert len(inbox) == 1
    assert inbox[0].title == "Your weekly recap"
    assert "1 application" in inbox[0].body
    # Same fan-out path as the daily digest / status update: always in-app; no
    # forced external channel when nothing is opted in.
    fired_channels = {c.channel for c in notifier._captured}
    assert fired_channels == {"in_app"}


@pytest.mark.unit
def test_deliver_returns_none_when_no_notification_service_wired():
    storage = InMemoryStorage()
    notifier = AppriseNotifier()
    digest = DigestService(storage, notifier)  # no notification_service injected
    cid = _campaign(storage)
    assert digest.deliver_weekly_recap(cid) is None


# --- scheduler cadence: once per (campaign, ISO week), gated ---------------


@pytest.mark.unit
def test_weekly_recap_pushes_once_per_iso_week_and_is_idempotent_on_retick():
    storage, digest, learning, notif_svc, notifier = _wire()
    cid = _campaign(storage)
    now = datetime(2026, 6, 16, 9, 0, tzinfo=UTC)  # a Tuesday
    _submit(storage, cid, captured_at=now - timedelta(days=1))

    sched = Scheduler(
        storage=storage,
        agent_loop=_Loop(),
        digest_service=digest,
        notification_service=notif_svc,
        setup_service=_Gate(allowed=True),
        weekly_recap_schedule="weekly",
    )
    out1 = sched.tick(now)
    assert out1["weekly_recaps"] == [str(cid)]
    assert len(notif_svc.list_inbox()) == 1

    # Re-tick later the SAME ISO week -> no second push.
    out2 = sched.tick(now + timedelta(days=2))
    assert out2["weekly_recaps"] == []
    assert len(notif_svc.list_inbox()) == 1

    # A NEW ISO week (7 days later) pushes again.
    out3 = sched.tick(now + timedelta(days=7))
    assert out3["weekly_recaps"] == [str(cid)]
    assert len(notif_svc.list_inbox()) == 2


@pytest.mark.unit
def test_weekly_recap_noop_when_disabled_by_default():
    storage, digest, _learning, notif_svc, _notifier = _wire()
    _campaign(storage)
    sched = Scheduler(
        storage=storage,
        agent_loop=_Loop(),
        digest_service=digest,
        notification_service=notif_svc,
        setup_service=_Gate(allowed=True),
        # weekly_recap_schedule intentionally omitted -> defaults to "off"
    )
    out = sched.tick(datetime(2026, 6, 16, 9, 0, tzinfo=UTC))
    assert out["weekly_recaps"] == []
    assert notif_svc.list_inbox() == []


@pytest.mark.unit
def test_weekly_recap_noop_when_automated_work_gate_closed():
    storage, digest, _learning, notif_svc, _notifier = _wire()
    _campaign(storage)
    sched = Scheduler(
        storage=storage,
        agent_loop=_Loop(),
        digest_service=digest,
        notification_service=notif_svc,
        setup_service=_Gate(allowed=False),
        weekly_recap_schedule="weekly",
    )
    out = sched.tick(datetime(2026, 6, 16, 9, 0, tzinfo=UTC))
    assert out["weekly_recaps"] == []
    assert notif_svc.list_inbox() == []


def test_weekly_recap_schedule_is_a_settings_field():
    """Deploy parity: WEEKLY_RECAP_SCHEDULE is read through Settings (like its
    STATUS_UPDATE_SCHEDULE / ESSENTIALS_NUDGE_SCHEDULE siblings), not a raw
    os.getenv — so the documented env var + the compose passthrough reach the engine."""
    from applicant.app.config import Settings

    assert Settings().weekly_recap_schedule == "off"  # dormant by default
    assert Settings(WEEKLY_RECAP_SCHEDULE="weekly").weekly_recap_schedule == "weekly"
