"""The outcome loop's missing half (design-audit Top-25 #5 / systemic theme #3).

The engine already had a working, keyword-based REJECTION detector
(``PostSubmissionService.scan_email_for_rejection`` -> ``process_rejection_signal``
-> ``detect_outcome``) -- but it had ZERO callers anywhere (no router, no scheduled
job), so the whole email-scanning capability was dead code, rejection included.
And even though ``OutcomeEvent`` already recognized ``interview_invited``/``offer``
as valid types, nothing ever auto-emitted them, and no notification fired for
either -- the "🎉 you got an interview" moment this item is about never happened.

This file proves the three additions built to close that gap:

1. **Detection**: ``scan_email_for_interview``/``scan_email_for_offer`` mirror
   ``scan_email_for_rejection``'s keyword-confidence shape and record the
   ``OutcomeEvent`` directly on a confident match (no parallel signal-audit-trail
   table -- ``RejectionSignal`` is rejection-specific by name/shape and was not
   force-generalized). ``PostSubmissionService.scan_email`` orchestrates all three
   with rejection-first precedence so one email records at most one outcome.
2. **Celebration**: recording ``interview_invited``/``offer`` -- via EITHER the
   manual tracker path (``record_manual_outcome``) OR the new auto-scan path --
   fires a real notification through the SAME ``NotificationPort.notify()`` fan-out
   the digest/weekly-recap already use, deduped on the outcome-event id.
3. **Learning hook (nice-to-have)**: a recorded positive outcome folds a positive
   taste signal through ``LearningService.fold_decision_atomic``, mirroring
   ``DigestService._learn_from_approval``.

Explicitly OUT of scope (unchanged, not tested here): automatic email-to-
application matching / wiring the workspace's live email inbox. Those need
their own dedicated design pass (mis-attributing an email risks recording a
fake outcome against the wrong application).

Hermetic: ``InMemoryStorage``, the real offline ``AppriseNotifier`` (records to
an in-app inbox, no network), real ``NotificationService``/``LearningService``.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from applicant.adapters.embedding.local_embedding import LocalEmbedding
from applicant.adapters.notification.apprise_notifier import AppriseNotifier
from applicant.adapters.storage.in_memory import InMemoryStorage
from applicant.app.main import create_app
from applicant.application.services.learning_service import LearningService
from applicant.application.services.notification_service import NotificationService
from applicant.application.services.post_submission_service import PostSubmissionService
from applicant.core.entities.application import Application
from applicant.core.entities.campaign import Campaign
from applicant.core.entities.job_posting import JobPosting
from applicant.core.ids import ApplicationId, CampaignId, JobPostingId, new_id
from applicant.core.state_machine import ApplicationState


def _wire(*, with_learning=True):
    storage = InMemoryStorage()
    notifier = AppriseNotifier()
    notif_svc = NotificationService(notifier)
    learning = LearningService(storage, LocalEmbedding()) if with_learning else None
    svc = PostSubmissionService(storage, notif_svc, learning=learning)
    return storage, svc, notif_svc, notifier, learning


def _seed_app(storage, *, status=ApplicationState.AWAITING_RESPONSE, company="Acme Corp",
              title="Backend Engineer", work_mode="remote", source_key="linkedin"):
    cid = CampaignId(new_id())
    storage.campaigns.add(Campaign(id=cid, name="c"))
    posting = JobPosting(
        id=JobPostingId(new_id()),
        campaign_id=cid,
        title=title,
        company=company,
        source_url="https://example.com/job",
        work_mode=work_mode,
        source_key=source_key,
    )
    storage.postings.add(posting)
    app = Application(
        id=ApplicationId(new_id()),
        campaign_id=cid,
        posting_id=posting.id,
        status=status,
    )
    storage.applications.add(app)
    return app, posting


# --- (1) detection: interview / offer keyword-confidence scanners --------------


@pytest.mark.unit
class TestInterviewDetection:
    def test_confident_match_records_interview_invited(self):
        storage, svc, notif_svc, notifier, _ = _wire()
        app, _ = _seed_app(storage)

        event = svc.scan_email_for_interview(
            "Next steps for your application",
            "We would like to schedule a call for a phone screen -- this is an interview.",
            app.id,
        )

        assert event is not None
        assert event.type == "interview_invited"
        assert event.source.value == "auto"
        stored = list(storage.outcomes.list_for_application(app.id))
        assert any(e.type == "interview_invited" for e in stored)
        # Positive signal never touches §7 status (same contract as the manual path).
        assert storage.applications.get(app.id).status == ApplicationState.AWAITING_RESPONSE

    def test_single_weak_keyword_is_a_graceful_no_op(self):
        storage, svc, *_ = _wire()
        app, _ = _seed_app(storage)

        event = svc.scan_email_for_interview("Hi", "Thanks for your interview interest.", app.id)

        assert event is None
        assert list(storage.outcomes.list_for_application(app.id)) == []

    def test_no_match_at_all_is_a_graceful_no_op(self):
        storage, svc, *_ = _wire()
        app, _ = _seed_app(storage)

        event = svc.scan_email_for_interview("Newsletter", "Here is our monthly update.", app.id)

        assert event is None

    def test_unknown_application_returns_none(self):
        storage, svc, *_ = _wire()

        event = svc.scan_email_for_interview(
            "Next steps", "Let's schedule a call for a phone screen interview.", ApplicationId(new_id())
        )

        assert event is None


@pytest.mark.unit
class TestOfferDetection:
    def test_confident_match_records_offer(self):
        storage, svc, *_ = _wire()
        app, _ = _seed_app(storage)

        event = svc.scan_email_for_offer(
            "We are pleased to offer you the role",
            "Please find attached your offer letter. We are excited to extend this job offer.",
            app.id,
        )

        assert event is not None
        assert event.type == "offer"
        assert event.source.value == "auto"
        assert storage.applications.get(app.id).status == ApplicationState.AWAITING_RESPONSE

    def test_single_weak_keyword_is_a_graceful_no_op(self):
        storage, svc, *_ = _wire()
        app, _ = _seed_app(storage)

        event = svc.scan_email_for_offer("Hi", "We have a job offer for you soon, stay tuned.", app.id)

        assert event is None


# --- keyword-collision / precedence checks --------------------------------------


@pytest.mark.unit
class TestKeywordCollisions:
    """The three keyword lists must not shadow each other (design-audit #5)."""

    def test_keyword_lists_do_not_literally_overlap(self):
        rejection_kws = [
            "unfortunately",
            "regret to inform",
            "not moving forward",
            "other candidates",
            "not selected",
            "position has been filled",
            "will not be proceeding",
        ]
        interview_kws = PostSubmissionService.INTERVIEW_KEYWORDS
        offer_kws = PostSubmissionService.OFFER_KEYWORDS
        for a in rejection_kws:
            for b in interview_kws + offer_kws:
                assert a not in b and b not in a, (a, b)
        for a in interview_kws:
            for b in offer_kws:
                assert a not in b and b not in a, (a, b)

    def test_rejection_wins_over_a_stray_interview_mention(self):
        """A rejection email that references a past interview must not ALSO
        fire an interview signal -- rejection is checked first and short-
        circuits scan_email precisely to prevent this."""
        storage, svc, *_ = _wire()
        app, _ = _seed_app(storage)

        result = svc.scan_email(
            app.id,
            subject="Update on your application",
            body=(
                "Unfortunately, following your interview, we regret to inform you "
                "that we will not be moving forward with other candidates for this role."
            ),
        )

        assert result["outcome_type"] == "rejected"
        assert result["recorded"] is True
        types = {e.type for e in storage.outcomes.list_for_application(app.id)}
        assert types == {"rejected"}
        assert "interview_invited" not in types

    def test_offer_wins_over_a_recap_mention_of_interview(self):
        """When a single email confidently matches BOTH the interview and the
        offer keyword lists (e.g. an offer email that recaps the interview
        process), OFFER must win -- offer is checked before interview in
        scan_email's precedence order, since it is the stronger/later-stage
        signal and the two must never both fire for one email."""
        storage, svc, *_ = _wire()
        app, _ = _seed_app(storage)

        result = svc.scan_email(
            app.id,
            subject="Your offer",
            body=(
                "Following your phone screen and interview, next steps are set: "
                "we are pleased to offer you the role. Please see the attached "
                "offer letter -- we are excited to extend this job offer, and "
                "welcome to the team."
            ),
        )

        assert result["outcome_type"] == "offer"
        types = {e.type for e in storage.outcomes.list_for_application(app.id)}
        assert types == {"offer"}

    def test_ambiguous_email_is_a_graceful_no_op(self):
        storage, svc, *_ = _wire()
        app, _ = _seed_app(storage)

        result = svc.scan_email(app.id, subject="Newsletter", body="Here is our monthly update.")

        assert result is None
        assert list(storage.outcomes.list_for_application(app.id)) == []

    def test_scan_email_unknown_application_returns_none(self):
        storage, svc, *_ = _wire()

        result = svc.scan_email(ApplicationId(new_id()), subject="x", body="y")

        assert result is None


# --- (2) celebratory notification: fires + dedups -------------------------------


@pytest.mark.unit
class TestCelebratoryNotification:
    def test_manual_interview_outcome_fires_a_celebratory_notification(self):
        storage, svc, notif_svc, notifier, _ = _wire()
        app, posting = _seed_app(storage, company="Acme Corp")

        svc.record_manual_outcome(app.id, "interview_invited")

        inbox = notif_svc.list_inbox()
        assert len(inbox) == 1
        assert "Acme Corp" in inbox[0].body
        assert "interview" in inbox[0].title.lower() or "🎉" in inbox[0].title

    def test_manual_offer_outcome_fires_a_celebratory_notification(self):
        storage, svc, notif_svc, notifier, _ = _wire()
        app, posting = _seed_app(storage, company="Beta LLC")

        svc.record_manual_outcome(app.id, "offer")

        inbox = notif_svc.list_inbox()
        assert len(inbox) == 1
        assert "Beta LLC" in inbox[0].body

    def test_auto_scan_interview_also_fires_the_same_celebration(self):
        """Both recording paths funnel through the SAME hook -- one delivery
        pipeline, not two."""
        storage, svc, notif_svc, notifier, _ = _wire()
        app, posting = _seed_app(storage, company="Gamma Inc")

        svc.scan_email_for_interview(
            "Next steps", "Let's schedule a call for a phone screen interview.", app.id
        )

        inbox = notif_svc.list_inbox()
        assert len(inbox) == 1
        assert "Gamma Inc" in inbox[0].body

    def test_rejected_outcome_does_not_celebrate(self):
        storage, svc, notif_svc, notifier, _ = _wire()
        app, _ = _seed_app(storage)

        svc.record_manual_outcome(app.id, "rejected")

        assert notif_svc.list_inbox() == []

    def test_notify_positive_outcome_dedups_on_the_outcome_event_id(self):
        """A retry/replay calling the notify step again for the SAME event id
        must not double-notify (design-audit #5's dedup requirement)."""
        notifier = AppriseNotifier()
        notif_svc = NotificationService(notifier)

        first = notif_svc.notify_positive_outcome(
            "outcome-123", outcome_type="interview_invited", company="Acme Corp"
        )
        second = notif_svc.notify_positive_outcome(
            "outcome-123", outcome_type="interview_invited", company="Acme Corp"
        )

        assert first is not None
        assert second is None  # deduped -- no second delivery
        assert len(notif_svc.list_inbox()) == 1

    def test_two_distinct_outcome_events_each_celebrate_once(self):
        """Not over-suppressed: a genuinely different event id still notifies."""
        notifier = AppriseNotifier()
        notif_svc = NotificationService(notifier)

        notif_svc.notify_positive_outcome("outcome-a", outcome_type="offer", company="Acme")
        notif_svc.notify_positive_outcome("outcome-b", outcome_type="offer", company="Acme")

        assert len(notif_svc.list_inbox()) == 2

    def test_missing_notification_service_degrades_gracefully(self):
        """PostSubmissionService(storage) with no notifier (existing test
        convention) must not raise when a positive outcome is recorded."""
        storage = InMemoryStorage()
        svc = PostSubmissionService(storage)
        app, _ = _seed_app(storage)

        event = svc.record_manual_outcome(app.id, "interview_invited")

        assert event.type == "interview_invited"


# --- (3) learning hook (nice-to-have) --------------------------------------------


@pytest.mark.unit
class TestLearningHook:
    def test_positive_outcome_up_weights_the_posting_features(self):
        storage, svc, notif_svc, notifier, learning = _wire(with_learning=True)
        app, posting = _seed_app(storage, title="Staff Engineer", work_mode="remote", source_key="linkedin")

        svc.record_manual_outcome(app.id, "offer")

        model = learning.load_model(app.campaign_id)
        assert model.feature_stats.get(f"role:{posting.title.lower()}", {}).get("staff engineer:approve") == 1
        assert model.feature_stats.get("work_mode:remote", {}).get("remote:approve") == 1
        assert model.feature_stats.get("source:linkedin", {}).get("linkedin:approve") == 1

    def test_rejected_outcome_does_not_fold_the_learning_hook(self):
        storage, svc, notif_svc, notifier, learning = _wire(with_learning=True)
        app, posting = _seed_app(storage)

        svc.record_manual_outcome(app.id, "rejected")

        model = learning.load_model(app.campaign_id)
        assert model.feature_stats == {}

    def test_missing_learning_collaborator_degrades_gracefully(self):
        storage, svc, *_ = _wire(with_learning=False)
        app, _ = _seed_app(storage)

        event = svc.record_manual_outcome(app.id, "offer")

        assert event.type == "offer"  # no raise, no-op


# --- router: the new scan-email endpoint ----------------------------------------


@pytest.fixture
def client():
    with TestClient(create_app()) as c:
        r = c.post(
            "/api/setup/llm",
            json={"provider": "ollama", "base_url": "http://localhost:11434/v1", "model": "llama3.1"},
        )
        assert r.status_code == 204
        yield c


def _registered_paths(app) -> set[str]:
    paths: set[str] = set()
    for r in app.routes:
        p = getattr(r, "path", None)
        if p:
            paths.add(p)
        orig = getattr(r, "original_router", None)
        if orig is not None:
            for sub in getattr(orig, "routes", []):
                sp = getattr(sub, "path", None)
                if sp:
                    paths.add(sp)
    return paths


def _seed_router(container, cid, aid, *, status=ApplicationState.AWAITING_RESPONSE):
    from applicant.core.entities.job_posting import JobPosting as _JP

    container.storage.campaigns.add(Campaign(id=CampaignId(cid), name="Tracker"))
    posting = _JP(
        id=JobPostingId(f"posting-{aid}"),
        campaign_id=CampaignId(cid),
        title="Engineer",
        company="RouterCo",
        source_url="https://example.com",
    )
    container.storage.postings.add(posting)
    app = Application(
        id=ApplicationId(aid),
        campaign_id=CampaignId(cid),
        posting_id=posting.id,
        status=status,
    )
    container.storage.applications.add(app)
    return app


@pytest.mark.unit
class TestScanEmailRouter:
    def test_scan_email_route_is_registered(self, client):
        paths = _registered_paths(client.app)
        assert "/api/post-submission/applications/{application_id}/scan-email" in paths

    def test_confident_offer_email_is_detected_and_recorded(self, client):
        container = client.app.state.container
        _seed_router(container, "c-scan-1", "a-scan-1")

        r = client.post(
            "/api/post-submission/applications/a-scan-1/scan-email",
            json={
                "subject": "We are pleased to offer you the role",
                "body": "Please see your offer letter -- we are excited to extend this job offer.",
            },
        )

        assert r.status_code == 200
        body = r.json()
        assert body["detected"] is True
        assert body["outcome_type"] == "offer"
        assert body["recorded"] is True

        board = client.get("/api/post-submission/c-scan-1").json()
        assert board["applications"][0]["signals"] == ["offer"]

    def test_no_match_email_reports_not_detected(self, client):
        container = client.app.state.container
        _seed_router(container, "c-scan-2", "a-scan-2")

        r = client.post(
            "/api/post-submission/applications/a-scan-2/scan-email",
            json={"subject": "Newsletter", "body": "Monthly update."},
        )

        assert r.status_code == 200
        assert r.json() == {"application_id": "a-scan-2", "detected": False}

    def test_unknown_application_is_404(self, client):
        r = client.post(
            "/api/post-submission/applications/does-not-exist/scan-email",
            json={"subject": "x", "body": "y"},
        )

        assert r.status_code == 404

    def test_llm_gate_blocks_scan_email_when_not_configured(self):
        with TestClient(create_app()) as c:
            r = c.post(
                "/api/post-submission/applications/a-1/scan-email",
                json={"subject": "x", "body": "y"},
            )
            assert r.status_code == 409
