"""Idempotency + decline-fold-lock bug-sweep regression tests (bugfix-sweep-2)."""

from __future__ import annotations

from applicant.adapters.embedding.local_embedding import LocalEmbedding
from applicant.adapters.notification.apprise_notifier import AppriseNotifier
from applicant.adapters.storage.in_memory import InMemoryStorage
from applicant.application.services.learning_service import LearningService
from applicant.application.services.prefill_service import PrefillService
from applicant.application.services.submission_service import SubmissionService
from applicant.core.entities.application import Application
from applicant.core.entities.campaign import Campaign
from applicant.core.ids import ApplicationId, CampaignId, JobPostingId, new_id
from applicant.core.state_machine import ApplicationState


# --- IDEM-2: _emit_waiting must dedup by (application_id, kind) --------------
def test_idem2_emit_waiting_dedups_by_app_and_kind():
    """IDEM-2: re-driving a waiting app twice yields exactly one pending action of
    that kind (no pile-up of duplicate 'Final approval' / 'Missing detail' actions)."""
    storage = InMemoryStorage()
    cid = CampaignId(new_id())
    storage.campaigns.add(Campaign(id=cid, name="C"))
    svc = PrefillService(
        storage=storage,
        browser=None,
        detection=None,
        sandbox=None,
        credentials=None,
        notification=None,
    )
    app = Application(
        id=ApplicationId(new_id()),
        campaign_id=cid,
        posting_id=JobPostingId(new_id()),
        status=ApplicationState.AWAITING_FINAL_APPROVAL,
    )

    first = svc._emit_waiting(
        application=app, kind="final_approval", title="Final approval / submit",
        session_url="s://1",
    )
    second = svc._emit_waiting(
        application=app, kind="final_approval", title="Final approval / submit",
        session_url="s://1",
    )

    assert first == second  # same pending action returned, not a new one
    open_actions = storage.pending_actions.list_open(cid)
    final = [a for a in open_actions if a.kind == "final_approval"]
    assert len(final) == 1


# --- IDEM-3: record_submission must be idempotent ---------------------------
def _submittable_app():
    return Application(
        id=ApplicationId(new_id()),
        campaign_id=CampaignId(new_id()),
        posting_id=JobPostingId(new_id()),
        status=ApplicationState.AWAITING_FINAL_APPROVAL,
        role_name="Senior Engineer",
        job_title="Senior Engineer",
        work_mode="remote",
        root_url="https://acme.example/job/1",
    )


def test_idem3_record_submission_is_idempotent():
    """IDEM-3: calling record_submission twice for one app produces exactly one
    OutcomeEvent (re-driven submit after a dropped checkpoint must not double-count)."""
    from applicant.core.entities.outcome_event import OutcomeSource

    storage = InMemoryStorage()
    svc = SubmissionService(storage)
    app = _submittable_app()

    e1 = svc.record_submission(app, source=OutcomeSource.AUTO)
    e2 = svc.record_submission(app, source=OutcomeSource.AUTO)

    assert e1.id == e2.id  # the same event is returned, not a new one
    outcomes = storage.outcomes.list_for_application(app.id)
    submitted = [o for o in outcomes if o.type == "submitted"]
    assert len(submitted) == 1


# --- IDEM-1: digest email send is deduped per campaign+day ------------------
def test_idem1_send_email_dedups_by_key():
    """IDEM-1: a second send_email with the same dedup key is a no-op (one email)."""
    # Pin the clock to the key's own day so the rolling-window dedup prune
    # (LEAK-NOTIF-1, _SENT_EMAIL_RETENTION_DAYS) never ages the just-added key out:
    # real digest keys embed the CURRENT day, so the two same-day sends always fall
    # inside the window. (Without a pinned clock this test silently rots once the
    # wall clock drifts more than the retention window past the hard-coded date.)
    from datetime import UTC, datetime

    day = datetime(2026, 6, 16, 12, 0, tzinfo=UTC)
    notifier = AppriseNotifier(
        apprise_urls="mailto://user:pw@smtp.test", clock=lambda: day
    )
    key = "digest_email:camp-1:2026-06-16"
    assert notifier.send_email(subject="Digest", html="<p>1</p>", dedup_key=key) is True
    assert notifier.send_email(subject="Digest", html="<p>2</p>", dedup_key=key) is True
    emails = [c for c in notifier.captured() if c.channel == "email"]
    assert len(emails) == 1


# --- CONC-4: decline fold goes through the per-campaign lock -----------------
def test_conc4_concurrent_decline_fold_and_source_event_no_lost_update():
    """CONC-4: a decline fold + a concurrent source-event for one campaign both land
    in the persisted learning_state (the locked atomic path prevents a lost update)."""
    import threading

    storage = InMemoryStorage()
    cid = CampaignId(new_id())
    storage.campaigns.add(Campaign(id=cid, name="C"))
    learning = LearningService(storage, LocalEmbedding())

    barrier = threading.Barrier(2)

    def decline():
        barrier.wait()
        learning.ingest_decline_atomic(
            cid, feedback_text="too junior remote", criteria_delta={"seniority": "down"}
        )

    def source_event():
        barrier.wait()
        learning.record_source_event(cid, "linkedin", "approvals")

    t1 = threading.Thread(target=decline)
    t2 = threading.Thread(target=source_event)
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    model = learning.load_model(cid)
    # The decline fold's feature stats survived (not clobbered by the source event).
    assert any(k.startswith("feedback:") or k == "seniority" for k in model.feature_stats)
    # The source-event approval leg survived (not clobbered by the decline fold).
    assert model.source_yield_stats.get("linkedin", {}).get("approvals", 0) == 1
