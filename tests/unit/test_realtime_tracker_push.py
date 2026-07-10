"""RT Phase 2 ``tracker`` push seam (realtime-websocket.md).

Recording an outcome mutates BOTH the Tracker board and the owner's Results
funnel/learning data, so ``PostSubmissionService._record_outcome_event`` — the ONE
seam every outcome path funnels through — fans a downstream ``notif``/``tracker``
frame over the realtime registry. The front-door Results/Today surfaces refetch off
that push instead of a poll (the poll stays as the WS-down fallback). BE->FE
surfacing only: the frame carries no action verb and authorizes nothing (the
``notif`` channel is upstream-denied — covered in ``test_realtime_notif_push.py``).
"""

from __future__ import annotations

from applicant.adapters.storage.in_memory import InMemoryStorage
from applicant.application.services.post_submission_service import PostSubmissionService
from applicant.core.entities.application import Application
from applicant.core.ids import ApplicationId, CampaignId, JobPostingId, new_id
from applicant.core.state_machine import ApplicationState


def _app(cid, status=ApplicationState.AWAITING_RESPONSE):
    return Application(
        id=ApplicationId(new_id()),
        campaign_id=cid,
        posting_id=JobPostingId(new_id()),
        status=status,
        root_url="https://acme.myworkdayjobs.com/job/1",
    )


def _service(storage, published):
    return PostSubmissionService(
        storage, realtime=lambda mtype, data: published.append((mtype, data))
    )


def test_recording_a_manual_outcome_fans_a_tracker_push():
    # A rejected outcome has no notification of its own, so WITHOUT this push its
    # Tracker/Results mutation would be invisible to the front-door until the next poll.
    published: list[tuple[str, dict]] = []
    storage = InMemoryStorage()
    cid = CampaignId(new_id())
    app = _app(cid, status=ApplicationState.AWAITING_RESPONSE)
    storage.applications.add(app)
    svc = _service(storage, published)

    svc.record_manual_outcome(app.id, "rejected")

    assert ("tracker", {"event": "rejected"}) in published


def test_recording_a_positive_outcome_also_fans_a_tracker_push():
    # A positive outcome (interview/offer) already fires a celebratory notification;
    # the tracker push fires too (a duplicate refetch is harmless) so Results/Today
    # refetch through the SAME seam every outcome type uses.
    published: list[tuple[str, dict]] = []
    storage = InMemoryStorage()
    cid = CampaignId(new_id())
    app = _app(cid, status=ApplicationState.AWAITING_RESPONSE)
    storage.applications.add(app)
    svc = _service(storage, published)

    svc.record_manual_outcome(app.id, "interview_invited")

    assert ("tracker", {"event": "interview_invited"}) in published


def test_post_submission_without_realtime_is_unchanged():
    # No publisher injected (legacy construction / unit tests) => no push, no raise.
    storage = InMemoryStorage()
    cid = CampaignId(new_id())
    app = _app(cid, status=ApplicationState.AWAITING_RESPONSE)
    storage.applications.add(app)
    svc = PostSubmissionService(storage)  # realtime defaults to None

    event = svc.record_manual_outcome(app.id, "rejected")
    assert event is not None and event.type == "rejected"


def test_tracker_push_never_breaks_outcome_recording():
    # A transport hiccup in the publisher must NOT break the write — the outcome is
    # the authoritative record either way (mirrors the pending/notif seams' posture).
    def _boom(_mtype, _data):
        raise RuntimeError("transport down")

    storage = InMemoryStorage()
    cid = CampaignId(new_id())
    app = _app(cid, status=ApplicationState.AWAITING_RESPONSE)
    storage.applications.add(app)
    svc = PostSubmissionService(storage, realtime=_boom)

    event = svc.record_manual_outcome(app.id, "rejected")
    assert event is not None and event.type == "rejected"
